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
        if missing_increment <= 1e-9:
            continue

        required_issued_total = consumed_qty + missing_increment
        additional_issue = max(required_issued_total - issued_qty, 0.0)
        if additional_issue <= 1e-9:
            additional_issue = 0.0

        stock_used = min(additional_issue, max(stock_quantity, 0.0))
        purchase_qty = max(additional_issue - stock_used, 0.0)

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
                        quantity_ordered,quantity_received,unit_price
                    )
                    SELECT id,%s,%s,%s,%s,%s
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
                    material_id,object_id,purchase_qty,unit_price,
                    purchase_qty,material_id,
                ),
            ))

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
