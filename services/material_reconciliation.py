from core.db import run_query
from core.formatting import safe_float, safe_int
from database.migrations import ensure_material_planning_tables, ensure_object_item_material_costs


def _fallback_supplier_id():
    name = 'ООО «Поставщик»'
    found = run_query(
        "SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1",
        (name,),
        fetch=True,
    )
    if not found.empty:
        return safe_int(found.iloc[0]["id"])

    created = run_query(
        """
        INSERT INTO reklet.suppliers(name,type,conditions)
        VALUES (%s,'material_supplier','Условный поставщик по умолчанию')
        RETURNING id
        """,
        (name,),
        fetch=True,
    )
    return safe_int(created.iloc[0]["id"])


def build_auto_material_reconciliation_statements(object_id, production_items):
    """Create missing warehouse postings for production already reached.

    IMPORTANT HISTORY RULE:
    material requirements for quantities that have already reached production
    are read only from object_item_material_costs, which is the frozen snapshot
    for that object item. A material added to the product template later is
    therefore invisible to historical reconciliation.

    New production is handled by the production module from the current
    product specification, so newly added materials still apply to future
    production.
    """
    ensure_material_planning_tables()
    ensure_object_item_material_costs(object_id)

    requested = {}
    for item_id, produced_qty in production_items:
        item_id = safe_int(item_id)
        produced_qty = float(produced_qty or 0)
        if item_id > 0 and produced_qty > 0:
            requested[item_id] = max(requested.get(item_id, 0.0), produced_qty)

    if not requested:
        return []

    material_targets = {}

    for item_id, produced_qty in requested.items():
        req = run_query(
            """
            SELECT
                oimc.material_id,
                COALESCE(oimc.quantity_per_unit,0)::numeric AS quantity_per_unit,
                COALESCE(oimc.waste_coefficient,1)::numeric AS waste_coefficient,
                COALESCE(oimc.unit_cost,0)::numeric AS unit_cost
            FROM reklet.object_item_material_costs oimc
            WHERE oimc.object_item_id=%s
            """,
            (item_id,),
            fetch=True,
        )

        # No snapshot means there is no historical material definition to
        # reconcile. This deliberately avoids inventing a historical material
        # requirement from today's product template.
        if req.empty:
            continue

        for _, row in req.iterrows():
            material_id = safe_int(row["material_id"])
            qpu = safe_float(row["quantity_per_unit"])
            waste = safe_float(row["waste_coefficient"], 1.0)
            unit_cost = safe_float(row["unit_cost"])
            target_qty = produced_qty * qpu * waste
            if material_id <= 0 or target_qty <= 1e-9:
                continue

            bucket = material_targets.setdefault(material_id, {"target_total": 0.0, "items": []})
            bucket["target_total"] += target_qty
            bucket["items"].append((item_id, target_qty, unit_cost))

    if not material_targets:
        return []

    statements = []

    for material_id, bucket in material_targets.items():
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
                COALESCE((SELECT stock_quantity FROM reklet.materials WHERE id=%s),0)::numeric AS stock_quantity
            """,
            (object_id,material_id,object_id,material_id,material_id),
            fetch=True,
        )
        if current.empty:
            continue

        row = current.iloc[0]
        consumed_qty = safe_float(row["consumed_qty"])
        issued_qty = safe_float(row["issued_qty"])
        stock_quantity = safe_float(row["stock_quantity"])

        missing_increment = bucket["target_total"]

        # Do not duplicate item-level historical consumption.
        existing_item_consumption = 0.0
        for item_id, target_qty, _unit_cost in bucket["items"]:
            existing_item = run_query(
                """
                SELECT COALESCE(SUM(quantity),0)::numeric AS qty
                FROM reklet.material_consumption
                WHERE object_item_id=%s AND material_id=%s
                """,
                (item_id, material_id),
                fetch=True,
            )
            if not existing_item.empty:
                existing_item_consumption += safe_float(existing_item.iloc[0]["qty"])

        missing_increment = max(missing_increment - existing_item_consumption, 0.0)

        item_ids = [
            safe_int(item_id)
            for item_id, _target_qty, _unit_cost in bucket["items"]
            if safe_int(item_id) > 0
        ]

        # A manager action must reconcile an existing production-to-warehouse
        # request instead of creating a second independent request path.
        # There can be more than one historical/open request for the same
        # material, so work with all matching object items in this material bucket.
        active_requests = run_query(
            """
            SELECT id, object_item_id, quantity_requested, quantity_supplied, status
            FROM reklet.material_production_requests
            WHERE object_id=%s
              AND object_item_id=ANY(%s)
              AND material_id=%s
              AND status IN ('sent','purchasing','ready')
            ORDER BY id
            """,
            (object_id, item_ids, material_id),
            fetch=True,
        )
        request_ids = (
            [safe_int(r["id"]) for _, r in active_requests.iterrows()]
            if not active_requests.empty else []
        )

        # If the requested material has already been issued by an earlier
        # manager/warehouse action, repair stale request status before leaving
        # this bucket. This also fixes the known state where quantity_supplied
        # equals quantity_requested but status is still 'ready'.
        if request_ids and issued_qty >= bucket["target_total"] - 1e-9:
            for _, request_row in active_requests.iterrows():
                requested_qty = safe_float(request_row["quantity_requested"])
                supplied_qty = safe_float(request_row["quantity_supplied"])
                if requested_qty > 0 and supplied_qty + 1e-9 >= requested_qty:
                    statements.append((
                        "UPDATE reklet.material_production_requests SET quantity_supplied=quantity_requested,status='completed',updated_at=timezone('utc'::text,now()) WHERE id=%s",
                        (safe_int(request_row["id"]),),
                    ))

        if missing_increment <= 1e-9:
            continue

        required_issued_total = consumed_qty + missing_increment
        additional_issue = max(required_issued_total - issued_qty, 0.0)
        if additional_issue <= 1e-9:
            continue

        linked_purchase_items = None
        if request_ids:
            linked_purchase_items = run_query(
                """
                SELECT
                    poi.id AS purchase_item_id,
                    poi.purchase_order_id,
                    poi.quantity_ordered,
                    poi.quantity_received,
                    poi.unit_price,
                    po.supplier_id
                FROM reklet.purchase_order_items poi
                JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
                WHERE poi.production_request_id = ANY(%s)
                  AND po.status<>'cancelled'
                  AND poi.quantity_received < poi.quantity_ordered
                ORDER BY poi.id
                """,
                (request_ids,),
                fetch=True,
            )

        stock_used = min(additional_issue, max(stock_quantity, 0.0))
        remaining_to_source = max(additional_issue - stock_used, 0.0)

        # If an open production request has an outstanding supplier order,
        # the manager's command may complete the receipt immediately.  This
        # closes the existing procurement path instead of creating a duplicate
        # automatic purchase. Any unused quantity on the supplier order remains
        # open/partial and may later become normal stock.
        if remaining_to_source > 1e-9 and linked_purchase_items is not None and not linked_purchase_items.empty:
            for _, po_row in linked_purchase_items.iterrows():
                if remaining_to_source <= 1e-9:
                    break
                outstanding = max(
                    safe_float(po_row["quantity_ordered"]) - safe_float(po_row["quantity_received"]),
                    0.0,
                )
                receive_qty = min(remaining_to_source, outstanding)
                if receive_qty <= 1e-9:
                    continue

                statements.append((
                    """
                    INSERT INTO reklet.material_transactions(
                        material_id,supplier_id,object_id,operation_type,
                        quantity,unit_price,transaction_type
                    ) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')
                    """,
                    (
                        material_id,
                        safe_int(po_row["supplier_id"]),
                        object_id,
                        receive_qty,
                        safe_float(po_row["unit_price"]),
                    ),
                ))
                statements.append((
                    """
                    UPDATE reklet.purchase_order_items
                    SET quantity_received=LEAST(quantity_ordered,quantity_received+%s)
                    WHERE id=%s
                    """,
                    (receive_qty, safe_int(po_row["purchase_item_id"])),
                ))
                statements.append((
                    "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",
                    (receive_qty, material_id),
                ))
                statements.append((
                    """
                    UPDATE reklet.purchase_orders po
                    SET status=CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM reklet.purchase_order_items x
                            WHERE x.purchase_order_id=po.id
                              AND x.quantity_received<x.quantity_ordered
                        ) THEN 'partial'
                        ELSE 'received'
                    END
                    WHERE po.id=%s AND po.status<>'cancelled'
                    """,
                    (safe_int(po_row["purchase_order_id"]),),
                ))
                remaining_to_source -= receive_qty

        purchase_qty = max(remaining_to_source, 0.0)

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

            if supplier.empty:
                supplier_id = _fallback_supplier_id()
                price_df = run_query(
                    "SELECT COALESCE(cost_per_unit,0) AS cost_per_unit FROM reklet.materials WHERE id=%s",
                    (material_id,),
                    fetch=True,
                )
                unit_price = safe_float(price_df.iloc[0]["cost_per_unit"]) if not price_df.empty else 0.0
            else:
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
                        purchase_order_id,object_id,material_id,
                        quantity_ordered,quantity_received,unit_price,production_request_id
                    )
                    SELECT id,%s,%s,%s,%s,%s,%s
                    FROM new_po
                    RETURNING id
                ), tx AS (
                    INSERT INTO reklet.material_transactions(
                        material_id,supplier_id,object_id,operation_type,
                        quantity,unit_price,transaction_type
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
                    object_id,material_id,purchase_qty,purchase_qty,unit_price,
                    request_ids[0] if request_ids else None,
                    material_id,object_id,purchase_qty,unit_price,
                    purchase_qty,material_id,
                ),
            ))

        # Complete the production-to-warehouse request(s) that this manager
        # command has now satisfied. If the action only covers part of a request,
        # keep the remainder open; if it covers the full request, close it.
        if request_ids:
            remaining_for_requests = additional_issue
            for _, request_row in active_requests.iterrows():
                if remaining_for_requests <= 1e-9:
                    break
                request_id = safe_int(request_row["id"])
                request_remaining = max(
                    safe_float(request_row["quantity_requested"])
                    - safe_float(request_row["quantity_supplied"]),
                    0.0,
                )
                supply_increment = min(remaining_for_requests, request_remaining)
                if request_remaining <= 1e-9:
                    statements.append((
                        "UPDATE reklet.material_production_requests SET quantity_supplied=quantity_requested,status='completed',updated_at=timezone('utc'::text,now()) WHERE id=%s",
                        (request_id,),
                    ))
                    continue
                if supply_increment > 1e-9:
                    statements.append((
                        """
                        UPDATE reklet.material_production_requests
                        SET quantity_supplied=LEAST(quantity_requested,quantity_supplied+%s),
                            status=CASE
                                WHEN quantity_supplied+%s>=quantity_requested THEN 'completed'
                                ELSE 'ready'
                            END,
                            updated_at=timezone('utc'::text,now())
                        WHERE id=%s
                        """,
                        (supply_increment, supply_increment, request_id),
                    ))
                    remaining_for_requests -= supply_increment

        if additional_issue > 1e-9:
            statements.append((
                """
                INSERT INTO reklet.material_transactions(
                    material_id,object_id,operation_type,quantity,transaction_type
                ) VALUES (%s,%s,'production_transfer',%s,'OUT')
                """,
                (material_id, object_id, additional_issue),
            ))
            statements.append((
                "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                (additional_issue, material_id),
            ))

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
                    (item_id,object_id,material_id,write_qty,unit_cost),
                ))
                remaining_to_write -= write_qty

    return statements
