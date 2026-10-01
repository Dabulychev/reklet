from core.db import run_query
from core.formatting import safe_float, safe_int
from database.migrations import ensure_material_planning_tables, ensure_object_item_material_costs


EPS = 1e-9


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


def _supplier_for_material(material_id):
    supplier = run_query(
        """
        SELECT
            ms.supplier_id,
            COALESCE(NULLIF(ms.purchase_price,0),m.cost_per_unit,0)::numeric AS unit_price
        FROM reklet.material_suppliers ms
        JOIN reklet.materials m ON m.id=ms.material_id
        WHERE ms.material_id=%s
        ORDER BY ms.is_preferred DESC,ms.id
        LIMIT 1
        """,
        (material_id,),
        fetch=True,
    )

    if not supplier.empty:
        return safe_int(supplier.iloc[0]["supplier_id"]), safe_float(supplier.iloc[0]["unit_price"])

    supplier_id = _fallback_supplier_id()
    price_df = run_query(
        "SELECT COALESCE(cost_per_unit,0) AS cost_per_unit FROM reklet.materials WHERE id=%s",
        (material_id,),
        fetch=True,
    )
    unit_price = safe_float(price_df.iloc[0]["cost_per_unit"]) if not price_df.empty else 0.0
    return supplier_id, unit_price


def build_auto_material_reconciliation_statements(object_id, production_items):
    """Build manager-shortcut material postings without leaving warehouse work hanging.

    Rules:
    * the manager may complete an operation without a prior production request;
    * when a production request exists, its linked purchase/receipt is completed
      instead of creating a second independent purchase;
    * a newly created automatic purchase is linked to the production request when
      one exists;
    * warehouse issue is reconciled independently from material consumption, so a
      historical consumption row cannot hide a missing production-transfer posting;
    * fully supplied production requests are marked completed;
    * reservations belonging to a fully completed object are released.
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
        if req.empty:
            continue

        for _, row in req.iterrows():
            material_id = safe_int(row["material_id"])
            qpu = safe_float(row["quantity_per_unit"])
            waste = safe_float(row["waste_coefficient"], 1.0)
            unit_cost = safe_float(row["unit_cost"])
            target_qty = produced_qty * qpu * waste
            if material_id <= 0 or target_qty <= EPS:
                continue

            bucket = material_targets.setdefault(
                material_id,
                {"target_total": 0.0, "items": []},
            )
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
        target_total = float(bucket["target_total"])

        # IMPORTANT: issue reconciliation is independent from consumption.
        # If consumption already exists but the warehouse transfer is missing,
        # the missing transfer must still be created.
        additional_issue = max(target_total - issued_qty, 0.0)

        # Determine whether this material is already covered by production requests.
        item_ids = [safe_int(item_id) for item_id, _, _ in bucket["items"]]
        request_df = run_query(
            """
            SELECT r.id AS request_id,
                   r.object_item_id,
                   r.quantity_requested,
                   r.quantity_supplied,
                   r.status
            FROM reklet.material_production_requests r
            WHERE r.object_id=%s
              AND r.material_id=%s
              AND r.object_item_id = ANY(%s)
              AND r.status IN ('sent','purchasing','ready')
            ORDER BY r.id
            """,
            (object_id, material_id, item_ids),
            fetch=True,
        )
        request_ids = [safe_int(v) for v in request_df["request_id"].tolist()] if not request_df.empty else []

        # A manager action fulfills the existing warehouse workflow instead of
        # creating a duplicate purchase. Complete all linked outstanding receipts.
        received_from_linked_orders = 0.0
        if request_ids:
            linked_po = run_query(
                """
                SELECT
                    poi.id AS purchase_item_id,
                    poi.purchase_order_id,
                    poi.material_id,
                    poi.quantity_ordered,
                    poi.quantity_received,
                    COALESCE(poi.unit_price,0)::numeric AS unit_price,
                    po.supplier_id
                FROM reklet.purchase_order_items poi
                JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
                WHERE poi.production_request_id=ANY(%s)
                  AND po.status<>'cancelled'
                  AND poi.quantity_received<poi.quantity_ordered
                ORDER BY poi.purchase_order_id,poi.id
                """,
                (request_ids,),
                fetch=True,
            )

            for _, po_row in linked_po.iterrows():
                outstanding = max(
                    safe_float(po_row["quantity_ordered"]) - safe_float(po_row["quantity_received"]),
                    0.0,
                )
                if outstanding <= EPS:
                    continue

                purchase_item_id = safe_int(po_row["purchase_item_id"])
                purchase_order_id = safe_int(po_row["purchase_order_id"])
                supplier_id = safe_int(po_row["supplier_id"])
                unit_price = safe_float(po_row["unit_price"])

                statements.extend([
                    (
                        """
                        INSERT INTO reklet.material_transactions(
                            material_id,supplier_id,object_id,operation_type,
                            quantity,unit_price,transaction_type
                        ) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')
                        """,
                        (material_id,supplier_id,object_id,outstanding,unit_price),
                    ),
                    (
                        "UPDATE reklet.purchase_order_items SET quantity_received=quantity_received+%s WHERE id=%s",
                        (outstanding,purchase_item_id),
                    ),
                    (
                        "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",
                        (outstanding,material_id),
                    ),
                ])
                statements.append((
                    """
                    UPDATE reklet.purchase_orders po
                    SET status=CASE
                        WHEN NOT EXISTS(
                            SELECT 1 FROM reklet.purchase_order_items poi
                            WHERE poi.purchase_order_id=po.id
                              AND poi.quantity_received<poi.quantity_ordered
                        ) THEN 'received'
                        WHEN EXISTS(
                            SELECT 1 FROM reklet.purchase_order_items poi
                            WHERE poi.purchase_order_id=po.id
                              AND poi.quantity_received>0
                        ) THEN 'partial'
                        ELSE 'ordered'
                    END
                    WHERE po.id=%s
                    """,
                    (purchase_order_id,),
                ))
                received_from_linked_orders += outstanding

            # Mark the production requests themselves as closed by the manager's
            # direct completion action. Their quantities are no longer outstanding.
            statements.append((
                """
                UPDATE reklet.material_production_requests
                SET quantity_supplied=quantity_requested,
                    status='completed',
                    updated_at=timezone('utc'::text,now())
                WHERE id=ANY(%s)
                """,
                (request_ids,),
            ))

        # If the manager's direct completion needs more than current stock plus
        # already-linked receipts, create one automatic purchase for the shortfall.
        stock_after_linked = stock_quantity + received_from_linked_orders
        shortage_after_linked = max(additional_issue - stock_after_linked, 0.0)

        if shortage_after_linked > EPS:
            supplier_id, unit_price = _supplier_for_material(material_id)
            linked_request_id = request_ids[0] if request_ids else None

            statements.append((
                """
                WITH new_po AS (
                    INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                    VALUES (%s,'received','Автоматическая закупка из Управления объектами')
                    RETURNING id,supplier_id
                )
                INSERT INTO reklet.purchase_order_items(
                    purchase_order_id,object_id,material_id,
                    quantity_ordered,quantity_received,unit_price,production_request_id
                )
                SELECT id,%s,%s,%s,%s,%s,%s
                FROM new_po
                """,
                (
                    supplier_id,
                    object_id,material_id,shortage_after_linked,shortage_after_linked,
                    unit_price,linked_request_id,
                ),
            ))
            statements.extend([
                (
                    """
                    INSERT INTO reklet.material_transactions(
                        material_id,supplier_id,object_id,operation_type,
                        quantity,unit_price,transaction_type
                    ) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')
                    """,
                    (material_id,supplier_id,object_id,shortage_after_linked,unit_price),
                ),
                (
                    "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",
                    (shortage_after_linked,material_id),
                ),
            ])

        # Finally make the warehouse-to-production transfer cover the complete
        # material target. This is what removes the visible remaining need.
        if additional_issue > EPS:
            statements.extend([
                (
                    """
                    INSERT INTO reklet.material_transactions(
                        material_id,object_id,operation_type,quantity,transaction_type
                    ) VALUES (%s,%s,'production_transfer',%s,'OUT')
                    """,
                    (material_id,object_id,additional_issue),
                ),
                (
                    "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                    (additional_issue,material_id),
                ),
            ])

        # Fill only the missing historical consumption rows. Existing consumption
        # must never be duplicated.
        remaining_to_write = target_total
        for item_id, target_qty, unit_cost in bucket["items"]:
            if remaining_to_write <= EPS:
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

            if write_qty > EPS:
                statements.append((
                    """
                    INSERT INTO reklet.material_consumption(
                        object_item_id,object_id,material_id,quantity,unit_cost_snapshot
                    ) VALUES (%s,%s,%s,%s,%s)
                    """,
                    (item_id,object_id,material_id,write_qty,unit_cost),
                ))
                remaining_to_write -= write_qty

    # When the object itself is fully completed, there must be no live reservation
    # left for it. Keep the release in the transaction history, then delete the
    # current reservation row.
    completed_object = run_query(
        """
        SELECT NOT EXISTS (
            SELECT 1
            FROM reklet.object_items oi
            WHERE oi.object_id=%s
              AND COALESCE(oi.quantity_needed,0)>0
              AND COALESCE(oi.qty_installed,0)<COALESCE(oi.quantity_needed,0)
        ) AS is_completed
        """,
        (object_id,),
        fetch=True,
    )
    if not completed_object.empty and bool(completed_object.iloc[0]["is_completed"]):
        reservations = run_query(
            """
            SELECT object_id,material_id,quantity_reserved
            FROM reklet.material_reservations
            WHERE object_id=%s
              AND quantity_reserved>0
            """,
            (object_id,),
            fetch=True,
        )
        for _, reservation in reservations.iterrows():
            material_id = safe_int(reservation["material_id"])
            quantity_reserved = safe_float(reservation["quantity_reserved"])
            if quantity_reserved <= EPS:
                continue
            statements.append((
                """
                INSERT INTO reklet.material_reservation_transactions(
                    object_id,material_id,operation_type,quantity
                ) VALUES (%s,%s,'release',%s)
                """,
                (object_id,material_id,quantity_reserved),
            ))
            statements.append((
                "DELETE FROM reklet.material_reservations WHERE object_id=%s AND material_id=%s",
                (object_id,material_id),
            ))

    return statements
