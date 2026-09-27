from core.db import run_query
from core.formatting import safe_int, safe_float
from database.migrations import (
    ensure_material_planning_tables,
    ensure_object_item_material_costs,
)




def build_auto_material_reconciliation_statements(object_id, production_items):
    """Reconcile warehouse material postings for production already reached by an item.

    production_items: iterable of (object_item_id, planned_produced_quantity).

    The key rule is idempotency: the warehouse is brought only to the quantity
    required by the planned production stage, using existing material_consumption
    and production_transfer history as the amount already covered. This also
    backfills legacy items that were already in transit/installation before the
    warehouse workflow was introduced.
    """
    ensure_material_planning_tables()
    ensure_object_item_material_costs(object_id)

    # Normalize duplicate item requests. The planned quantity is the final amount
    # that has already passed through / entered production after the management action.
    requested = {}
    for item_id, produced_qty in production_items:
        item_id = safe_int(item_id)
        produced_qty = float(produced_qty or 0)
        if item_id > 0 and produced_qty > 0:
            requested[item_id] = max(requested.get(item_id, 0.0), produced_qty)

    if not requested:
        return []

    material_targets = {}
    item_material_targets = {}

    for item_id, produced_qty in requested.items():
        req = run_query(
            """
            SELECT
                ptm.material_id,
                COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)::numeric AS quantity_per_unit,
                COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1)::numeric AS waste_coefficient,
                COALESCE(oimc.unit_cost, m.cost_per_unit, 0)::numeric AS unit_cost
            FROM reklet.object_items oi
            JOIN reklet.product_template_materials ptm
              ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
            JOIN reklet.materials m
              ON m.id = ptm.material_id
            LEFT JOIN reklet.object_item_material_costs oimc
              ON oimc.object_item_id = oi.id
             AND oimc.material_id = ptm.material_id
            WHERE oi.id=%s
            """,
            (item_id,),
            fetch=True,
        )
        if req.empty:
            continue

        item_rows = []
        for _, rr in req.iterrows():
            material_id = safe_int(rr["material_id"])
            quantity_per_unit = safe_float(rr["quantity_per_unit"])
            waste = safe_float(rr["waste_coefficient"], 1.0)
            unit_cost = safe_float(rr["unit_cost"])
            target_qty = produced_qty * quantity_per_unit * waste
            if material_id <= 0 or target_qty <= 1e-9:
                continue

            item_rows.append((material_id, target_qty, unit_cost))
            bucket = material_targets.setdefault(material_id, {
                "target_total": 0.0,
                "items": []
            })
            bucket["target_total"] += target_qty
            bucket["items"].append((item_id, target_qty, unit_cost))

        item_material_targets[item_id] = item_rows

    if not material_targets:
        return []

    statements = []

    # We first determine how much each material is missing at object level.
    # production_transfer is object-level in the existing schema, therefore it is
    # the correct pool to compare against the total target for this reconciliation.
    for material_id, bucket in material_targets.items():
        target_increment = bucket["target_total"]

        current = run_query(
            """
            WITH consumed AS (
                SELECT COALESCE(SUM(quantity),0)::numeric AS qty
                FROM reklet.material_consumption
                WHERE object_id=%s AND material_id=%s
            ),
            issued AS (
                SELECT COALESCE(SUM(quantity),0)::numeric AS qty
                FROM reklet.material_transactions
                WHERE object_id=%s
                  AND material_id=%s
                  AND operation_type='production_transfer'
                  AND transaction_type='OUT'
            )
            SELECT
                (SELECT qty FROM consumed) AS consumed_qty,
                (SELECT qty FROM issued) AS issued_qty,
                COALESCE((
                    SELECT SUM(r.quantity_reserved)
                    FROM reklet.material_reservations r
                    WHERE r.object_id=%s AND r.material_id=%s
                ),0)::numeric AS object_reserved,
                COALESCE((
                    SELECT SUM(r.quantity_reserved)
                    FROM reklet.material_reservations r
                    WHERE r.material_id=%s
                ),0)::numeric AS total_reserved,
                COALESCE((SELECT m.stock_quantity FROM reklet.materials m WHERE m.id=%s),0)::numeric AS stock_quantity
            """,
            (
                object_id, material_id,
                object_id, material_id,
                object_id, material_id,
                material_id,
                material_id,
            ),
            fetch=True,
        )
        if current.empty:
            continue

        row = current.iloc[0]
        consumed_qty = safe_float(row["consumed_qty"])
        issued_qty = safe_float(row["issued_qty"])
        object_reserved = safe_float(row["object_reserved"])
        total_reserved = safe_float(row["total_reserved"])
        stock_quantity = safe_float(row["stock_quantity"])

        # Existing consumption plus this reconciliation target is the amount that
        # must be represented as consumed for the object/item history.
        missing_consumption = max(target_increment, 0.0)

        # If this helper is called repeatedly for the same stage, consumption history
        # already covers part/all of the target and must not be inserted again.
        # Sum existing consumption for the exact changed items only.
        existing_item_consumption = 0.0
        for item_id, target_qty, _unit_cost in bucket["items"]:
            consumed_item = run_query(
                """
                SELECT COALESCE(SUM(quantity),0)::numeric AS qty
                FROM reklet.material_consumption
                WHERE object_item_id=%s AND material_id=%s
                """,
                (item_id, material_id),
                fetch=True,
            )
            if not consumed_item.empty:
                existing_item_consumption += safe_float(consumed_item.iloc[0]["qty"])

        missing_increment = max(target_increment - existing_item_consumption, 0.0)
        if missing_increment <= 1e-9:
            # The target item/material consumption already exists. No warehouse
            # quantity needs to be generated for it.
            continue

        # Existing object-level transfers can already cover this material even when
        # item-level consumption history is missing (legacy data). We only create an
        # additional physical transfer for the uncovered amount.
        additional_issue = max(missing_increment - max(issued_qty - consumed_qty, 0.0), 0.0)

        # The simpler and safer object-level coverage rule for legacy records is:
        # total issued must be at least total consumed + this missing item increment.
        required_issued_total = consumed_qty + missing_increment
        additional_issue = max(required_issued_total - issued_qty, 0.0)

        reserve_needed = max(additional_issue - object_reserved, 0.0)
        free_stock = max(stock_quantity - total_reserved, 0.0)
        reserve_from_stock = min(reserve_needed, free_stock)
        purchase_qty = max(reserve_needed - reserve_from_stock, 0.0)

        if reserve_from_stock > 1e-9:
            statements.append((
                """
                INSERT INTO reklet.material_reservations(object_id,material_id,quantity_reserved)
                SELECT %s,%s,%s
                WHERE %s > 1e-9
                ON CONFLICT(object_id,material_id)
                DO UPDATE SET quantity_reserved = reklet.material_reservations.quantity_reserved + EXCLUDED.quantity_reserved,
                              updated_at = timezone('utc'::text,now())
                """,
                (object_id, material_id, reserve_from_stock, reserve_from_stock),
            ))

        if purchase_qty > 1e-9:
            supplier = run_query(
                """
                SELECT
                    ms.supplier_id,
                    COALESCE(NULLIF(ms.purchase_price,0),m.cost_per_unit,0)::numeric AS unit_price
                FROM reklet.material_suppliers ms
                JOIN reklet.materials m ON m.id=ms.material_id
                WHERE ms.material_id=%s
                ORDER BY ms.is_preferred DESC, ms.id
                LIMIT 1
                """,
                (material_id,),
                fetch=True,
            )

            if not supplier.empty:
                supplier_id = safe_int(supplier.iloc[0]["supplier_id"])
                unit_price = safe_float(supplier.iloc[0]["unit_price"])
                statements.append((
                    """
                    WITH new_po AS (
                        INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                        VALUES (%s,'received','Автоматическая закупка из Управления объектами')
                        RETURNING id,supplier_id
                    ), new_item AS (
                        INSERT INTO reklet.purchase_order_items(
                            purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price
                        )
                        SELECT id,%s,%s,%s,%s,%s
                        FROM new_po
                        RETURNING id
                    ), tx AS (
                        INSERT INTO reklet.material_transactions(
                            material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type
                        )
                        SELECT %s,supplier_id,%s,'purchase',%s,%s,'IN'
                        FROM new_po
                        RETURNING material_id
                    )
                    UPDATE reklet.materials
                    SET stock_quantity=COALESCE(stock_quantity,0)+%s
                    WHERE id=%s
                    """,
                    (
                        supplier_id,
                        object_id, material_id, purchase_qty, purchase_qty, unit_price,
                        material_id, object_id, purchase_qty, unit_price,
                        purchase_qty, material_id,
                    ),
                ))
            else:
                # No supplier is linked to this material: use the technical fallback
                # supplier required by the warehouse rules.
                statements.append((
                    """
                    WITH existing_supplier AS (
                        SELECT id
                        FROM reklet.suppliers
                        WHERE name=%s
                        ORDER BY id
                        LIMIT 1
                    ), created_supplier AS (
                        INSERT INTO reklet.suppliers(name,type,category,conditions)
                        SELECT %s,'material_supplier','Служебный','Условный поставщик по умолчанию'
                        WHERE NOT EXISTS (SELECT 1 FROM existing_supplier)
                        RETURNING id
                    ), supplier AS (
                        SELECT id FROM existing_supplier
                        UNION ALL
                        SELECT id FROM created_supplier
                        LIMIT 1
                    ), new_po AS (
                        INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                        SELECT id,'received','Автоматическая закупка из Управления объектами'
                        FROM supplier
                        RETURNING id,supplier_id
                    ), new_item AS (
                        INSERT INTO reklet.purchase_order_items(
                            purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price
                        )
                        SELECT id,%s,%s,%s,%s,%s
                        FROM new_po
                        RETURNING id
                    ), tx AS (
                        INSERT INTO reklet.material_transactions(
                            material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type
                        )
                        SELECT %s,supplier_id,%s,'purchase',%s,%s,'IN'
                        FROM new_po
                        RETURNING material_id
                    )
                    UPDATE reklet.materials
                    SET stock_quantity=COALESCE(stock_quantity,0)+%s
                    WHERE id=%s
                    """,
                    (
                        'ООО «Поставщик»', 'ООО «Поставщик»',
                        object_id, material_id, purchase_qty, purchase_qty,
                        safe_float(run_query(
                            "SELECT cost_per_unit FROM reklet.materials WHERE id=%s",
                            (material_id,), fetch=True
                        ).iloc[0]["cost_per_unit"]),
                        material_id, object_id, purchase_qty,
                        safe_float(run_query(
                            "SELECT cost_per_unit FROM reklet.materials WHERE id=%s",
                            (material_id,), fetch=True
                        ).iloc[0]["cost_per_unit"]),
                        purchase_qty, material_id,
                    ),
                ))

        newly_reserved = reserve_from_stock + purchase_qty
        if newly_reserved > 1e-9:
            statements.append((
                """
                INSERT INTO reklet.material_reservations(object_id,material_id,quantity_reserved)
                SELECT %s,%s,%s
                WHERE %s > 1e-9
                ON CONFLICT(object_id,material_id)
                DO UPDATE SET quantity_reserved = reklet.material_reservations.quantity_reserved + EXCLUDED.quantity_reserved,
                              updated_at = timezone('utc'::text,now())
                """,
                (object_id, material_id, newly_reserved, newly_reserved),
            ))

        if reserve_from_stock > 1e-9:
            statements.append((
                "INSERT INTO reklet.material_reservation_transactions(object_id,material_id,operation_type,quantity) VALUES (%s,%s,'reserve',%s)",
                (object_id, material_id, reserve_from_stock),
            ))
        if purchase_qty > 1e-9:
            statements.append((
                "INSERT INTO reklet.material_reservation_transactions(object_id,material_id,operation_type,quantity) VALUES (%s,%s,'reserve',%s)",
                (object_id, material_id, purchase_qty),
            ))

        if additional_issue > 1e-9:
            statements.append((
                "INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",
                (material_id, object_id, additional_issue),
            ))
            statements.append((
                "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                (additional_issue, material_id),
            ))

            resulting_reserve = max(object_reserved + newly_reserved - additional_issue, 0.0)
            if resulting_reserve <= 1e-9:
                statements.append((
                    "DELETE FROM reklet.material_reservations WHERE object_id=%s AND material_id=%s",
                    (object_id, material_id),
                ))
            else:
                statements.append((
                    "UPDATE reklet.material_reservations SET quantity_reserved=%s,updated_at=timezone('utc'::text,now()) WHERE object_id=%s AND material_id=%s",
                    (resulting_reserve, object_id, material_id),
                ))

        # Finally, write item-level consumption only for the missing historical part.
        # This makes the reconciliation idempotent on every later-stage management action.
        remaining_to_write = missing_increment
        for item_id, target_qty, unit_cost in bucket["items"]:
            if remaining_to_write <= 1e-9:
                break
            existing_item = run_query(
                """
                SELECT COALESCE(SUM(quantity),0)::numeric AS qty
                FROM reklet.material_consumption
                WHERE object_item_id=%s AND material_id=%s
                """,
                (item_id, material_id),
                fetch=True,
            )
            existing_qty = safe_float(existing_item.iloc[0]["qty"]) if not existing_item.empty else 0.0
            item_missing = max(target_qty - existing_qty, 0.0)
            write_qty = min(item_missing, remaining_to_write)
            if write_qty > 1e-9:
                statements.append((
                    """
                    INSERT INTO reklet.material_consumption(
                        object_item_id,object_id,material_id,quantity,unit_cost_snapshot
                    ) VALUES (%s,%s,%s,%s,%s)
                    """,
                    (item_id, object_id, material_id, write_qty, unit_cost),
                ))
                remaining_to_write -= write_qty

    return statements
