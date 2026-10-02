import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_int, safe_float
from core.printing import render_print_html
from database.migrations import ensure_material_planning_tables, ensure_stage_movement_tables, ensure_task_three_tables
from repositories.clients import get_clients
from repositories.objects import get_objects, get_object_items
from repositories.products import get_templates
from services.object_management import calculate_object_management_change
from services.material_reconciliation import build_auto_material_reconciliation_statements


EPS = 1e-9


def _fmt_qty(value, decimals=2):
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return "0.00"



def _render_create_object_workspace():
    clients = get_clients()
    client_map = {str(row["name"]): int(row["id"]) for _, row in clients.iterrows()} if not clients.empty else {}
    st.markdown("#### Создать новый объект")
    if not client_map:
        st.warning("Сначала необходимо создать заказчика.")
        return

    with st.form("workspace_create_object"):
        client_name = st.selectbox("Заказчик", list(client_map.keys()))
        object_name = st.text_input("Название объекта")
        address = st.text_input("Адрес объекта")
        phone = st.text_input("Телефон")
        contact_person = st.text_input("Контактное лицо")
        notes = st.text_area("Примечания")
        c1, c2 = st.columns(2)
        with c1:
            distance = st.number_input("Расстояние до объекта (км)", min_value=0.0, value=0.0)
            contract_date = st.date_input("Дата договора", value=None)
            production_start = st.date_input("Начало производства", value=None)
            production_end = st.date_input("Окончание производства", value=None)
        with c2:
            installation_date = st.date_input("Дата монтажа", value=None)
            installation_end = st.date_input("Окончание монтажа", value=None)

        if st.form_submit_button("Создать объект", use_container_width=True):
            if not object_name.strip():
                st.warning("Необходимо указать название объекта.")
                return
            run_query(
                """
                INSERT INTO reklet.objects
                (client_id, object_name, address, phone, contact_person, notes,
                 transport_distance_km, delivery_cost, contract_date,
                 production_start_date, production_end_date, installation_date, installation_end_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s)
                """,
                (client_map[client_name], object_name.strip(), address or None, phone or None,
                 contact_person or None, notes or None, distance,
                 contract_date, production_start, production_end, installation_date, installation_end)
            )
            st.success("Объект создан.")
            st.rerun()

def _get_selected_object():
    objects = get_objects().sort_values("id", ascending=False).copy()
    clients = get_clients()
    if objects.empty:
        return None, None

    customer_names = (
        sorted(
            objects["client_name"].fillna("").astype(str).str.strip()
            .loc[lambda s: s != ""].unique().tolist()
        )
        if not objects.empty else []
    )
    customer_options = ["— Выберите заказчика —"] + customer_names

    selected_customer = st.selectbox(
        "Заказчик",
        customer_options,
        key="workspace_customer",
    )
    if selected_customer == "— Выберите заказчика —":
        return None, None

    filtered = objects[
        objects["client_name"].fillna("").astype(str).str.strip().eq(selected_customer)
    ].copy()
    if filtered.empty:
        st.info("У выбранного заказчика нет объектов.")
        return None, None

    object_options = [
        f"{int(row['id'])} — {str(row['object_name'] or '').strip()}"
        for _, row in filtered.iterrows()
    ]
    selected_object = st.selectbox(
        "Объект",
        object_options,
        key="workspace_object",
    )
    object_id = int(selected_object.split(" — ", 1)[0])
    object_row = filtered[filtered["id"].eq(object_id)].iloc[0].copy()
    return object_id, object_row


def _get_item_state(object_id, object_item_id):
    df = get_object_items(object_id)
    if df.empty:
        return None
    rows = df[df["id"].eq(object_item_id)]
    if rows.empty:
        return None
    return rows.iloc[0].copy()


def _get_item_materials(object_item_id):
    return run_query(
        """
        SELECT
            m.id AS material_id,
            m.name AS material_name,
            u.name AS unit_name,
            COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)::numeric AS quantity_per_unit,
            COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1)::numeric AS waste_coefficient,
            COALESCE(oimc.unit_cost, m.cost_per_unit, 0)::numeric AS unit_cost,
            COALESCE(m.stock_quantity, 0)::numeric AS stock_quantity
        FROM reklet.object_items oi
        JOIN reklet.product_template_materials ptm
          ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
        JOIN reklet.materials m
          ON m.id = ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc
          ON oimc.object_item_id = oi.id
         AND oimc.material_id = ptm.material_id
        LEFT JOIN reklet.units u
          ON u.id = m.unit_id
        WHERE oi.id=%s
        ORDER BY m.name
        """,
        (object_item_id,),
        fetch=True,
    )


def _get_material_supply(material_id, object_id, object_item_id):
    request_df = run_query(
        """
        SELECT
            COALESCE(SUM(r.quantity_requested),0)::numeric AS requested,
            COALESCE(SUM(r.quantity_supplied),0)::numeric AS supplied,
            COUNT(*) FILTER (WHERE r.status IN ('sent','purchasing','ready')) AS open_requests
        FROM reklet.material_production_requests r
        WHERE (r.object_item_id=%s OR r.object_id=%s)
          AND r.material_id=%s
        """,
        (object_item_id, object_id, material_id),
        fetch=True,
    )
    purchase_df = run_query(
        """
        SELECT
            COALESCE(SUM(poi.quantity_ordered),0)::numeric AS ordered,
            COALESCE(SUM(poi.quantity_received),0)::numeric AS received
        FROM reklet.purchase_order_items poi
        LEFT JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
        WHERE po.status<>'cancelled'
          AND poi.material_id=%s
          AND (poi.object_id=%s OR poi.production_request_id IN (
              SELECT r.id
              FROM reklet.material_production_requests r
              WHERE r.object_item_id=%s OR r.object_id=%s
          ))
        """,
        (material_id, object_id, object_item_id, object_id),
        fetch=True,
    )
    rr = request_df.iloc[0] if not request_df.empty else {}
    pp = purchase_df.iloc[0] if not purchase_df.empty else {}
    return {
        "requested": safe_float(rr.get("requested", 0)),
        "supplied": safe_float(rr.get("supplied", 0)),
        "open_requests": safe_int(rr.get("open_requests", 0)),
        "ordered": safe_float(pp.get("ordered", 0)),
        "received": safe_float(pp.get("received", 0)),
    }


def _render_materials(object_id, object_item_id, item):
    materials = _get_item_materials(object_item_id)
    st.markdown("#### Материалы")
    if materials.empty:
        st.info("Для этого изделия нет спецификации материалов.")
        return

    rows = []
    produced_qty = (
        safe_float(item.get("qty_production", 0))
        + safe_float(item.get("qty_ready", 0))
        + safe_float(item.get("qty_shipped", 0))
        + safe_float(item.get("qty_arrived", 0))
        + safe_float(item.get("qty_installing", 0))
        + safe_float(item.get("qty_installed", 0))
    )
    for _, row in materials.iterrows():
        qpu = safe_float(row["quantity_per_unit"])
        waste = safe_float(row["waste_coefficient"], 1.0)
        stock = safe_float(row["stock_quantity"])
        required_total = safe_float(item.get("quantity_needed", 0)) * qpu * waste
        produced_need = produced_qty * qpu * waste
        consumed = run_query(
            """
            SELECT COALESCE(SUM(quantity),0)::numeric AS qty
            FROM reklet.material_consumption
            WHERE object_item_id=%s AND material_id=%s
            """,
            (object_item_id, safe_int(row["material_id"])),
            fetch=True,
        )
        consumed_qty = safe_float(consumed.iloc[0]["qty"]) if not consumed.empty else 0.0
        supply = _get_material_supply(safe_int(row["material_id"]), object_id, object_item_id)
        short_for_production = max(produced_need - consumed_qty, 0.0)
        open_purchase = max(supply["ordered"] - supply["received"], 0.0)
        rows.append({
            "Материал": row["material_name"],
            "Единица": row["unit_name"] or "",
            "Потребность": required_total,
            "На текущий этап": produced_need,
            "Списано в производство": consumed_qty,
            "Осталось на этап": short_for_production,
            "На складе": stock,
            "Заказано": supply["ordered"],
            "Получено": supply["received"],
            "Ожидается": open_purchase,
        })

    view = pd.DataFrame(rows)
    for col in view.columns[2:]:
        view[col] = pd.to_numeric(view[col], errors="coerce").fillna(0.0).round(2)
    st.dataframe(view, width="stretch", hide_index=True)
    render_print_html(
        f"Материалы — {str(item.get('item_name') or '').strip()}",
        view,
        f"print_workspace_materials_{object_item_id}",
    )


def _render_history(object_id, object_item_id):
    st.markdown("#### История")
    history = run_query(
        """
        SELECT tx_date, section_name, operation_name, quantity
        FROM (
            SELECT
                pt.created_at AS tx_date,
                'Производство' AS section_name,
                pt.operation_type AS operation_name,
                pt.quantity,
                pt.id AS sort_id
            FROM reklet.production_transactions pt
            WHERE pt.object_id=%s AND pt.object_item_id=%s

            UNION ALL

            SELECT
                fgt.created_at,
                'Готовая продукция',
                fgt.operation_type,
                fgt.quantity,
                fgt.id
            FROM reklet.finished_goods_transactions fgt
            WHERE fgt.object_id=%s AND fgt.object_item_id=%s

            UNION ALL

            SELECT
                tt.created_at,
                'Транспорт',
                tt.operation_type,
                tt.quantity,
                tt.id
            FROM reklet.transport_transactions tt
            WHERE tt.object_id=%s AND tt.object_item_id=%s

            UNION ALL

            SELECT
                it.created_at,
                'Монтаж',
                it.operation_type,
                it.quantity,
                it.id
            FROM reklet.installation_transactions it
            WHERE it.object_id=%s AND it.object_item_id=%s
        ) q
        ORDER BY tx_date DESC, sort_id DESC
        """,
        (object_id, object_item_id, object_id, object_item_id,
         object_id, object_item_id, object_id, object_item_id),
        fetch=True,
    )
    if history.empty:
        st.info("Движений по этому изделию ещё нет.")
        return
    view = history.copy()
    view["tx_date"] = pd.to_datetime(view["tx_date"], errors="coerce").dt.strftime("%d.%m.%Y %H:%M")
    view.columns = ["Дата", "Раздел", "Действие", "Количество"]
    st.dataframe(view, width="stretch", hide_index=True)


def _apply_stage_action(object_id, item, action_name, quantity):
    old_state = {
        "order": safe_float(item.get("quantity_needed", 0)),
        "new": safe_float(item.get("qty_new", 0)),
        "production": safe_float(item.get("qty_production", 0)),
        "ready": safe_float(item.get("qty_ready", 0)),
        "shipped": safe_float(item.get("qty_shipped", 0)),
        "arrived": safe_float(item.get("qty_arrived", 0)),
        "installing": safe_float(item.get("qty_installing", 0)),
        "installed": safe_float(item.get("qty_installed", 0)),
    }

    kwargs = {
        "correction": 0.0,
        "manufactured_action": 0.0,
        "shipped_action": 0.0,
        "delivered_action": 0.0,
        "installed_action": 0.0,
    }
    if action_name == "Изготовить":
        kwargs["manufactured_action"] = quantity
    elif action_name == "Отгрузить":
        kwargs["shipped_action"] = quantity
    elif action_name == "Доставить":
        kwargs["delivered_action"] = quantity
    elif action_name == "Установить":
        kwargs["installed_action"] = quantity
    elif action_name == "Изменить заказ":
        kwargs["correction"] = quantity

    result = calculate_object_management_change(old_state, **kwargs)
    if result.get("error"):
        return None, result["error"]

    return {
        "old": old_state,
        "new": result["state"],
        "commands": result["commands"],
        "item_id": safe_int(item["id"]),
        "item_name": str(item.get("item_name") or "").strip(),
        "actions": kwargs,
    }, None


def _build_stage_statements(change, object_id):
    item_id = change["item_id"]
    new = change["new"]
    statements = []

    production_completed = (
        new["ready"] + new["shipped"] + new["arrived"] +
        new["installing"] + new["installed"]
    )
    production_status = (
        "completed" if new["new"] <= EPS and new["production"] <= EPS and new["order"] > EPS
        else "in_progress" if production_completed > EPS or new["production"] > EPS
        else "not_started"
    )
    installation_status = (
        "completed" if new["installed"] + EPS >= new["order"] and new["order"] > EPS
        else "in_progress" if new["installed"] > EPS
        else "not_started"
    )

    statements.append((
        """
        UPDATE reklet.object_items
        SET quantity_needed=%s,
            quantity=%s,
            qty_new=%s,
            qty_production=%s,
            qty_ready=%s,
            qty_shipped=%s,
            qty_arrived=%s,
            qty_installing=%s,
            qty_installed=%s,
            production_status=%s,
            production_progress_pct=CASE WHEN %s>0 THEN LEAST(100,ROUND(%s::numeric/%s*100)) ELSE 0 END,
            installation_status=%s,
            installation_progress_pct=CASE WHEN %s>0 THEN LEAST(100,ROUND(%s::numeric/%s*100)) ELSE 0 END
        WHERE id=%s AND object_id=%s
        """,
        (
            new["order"], new["order"], new["new"], new["production"],
            new["ready"], new["shipped"], new["arrived"],
            new["installing"], new["installed"], production_status,
            new["order"], production_completed, new["order"],
            installation_status, new["order"], new["installed"], new["order"],
            item_id, object_id,
        ),
    ))

    for kind, qty in change["commands"]:
        if kind == "production":
            statements.extend([
                (
                    "INSERT INTO reklet.production_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'completed',%s)",
                    (item_id, object_id, qty),
                ),
                (
                    "INSERT INTO reklet.finished_goods(object_item_id,object_id,quantity,status) VALUES (%s,%s,%s,'ready')",
                    (item_id, object_id, qty),
                ),
                (
                    "INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'ready',%s)",
                    (item_id, object_id, qty),
                ),
            ])
        elif kind == "ship":
            statements.extend([
                (
                    """
                    WITH ready_rows AS (
                        SELECT id, quantity,
                               COALESCE(SUM(quantity) OVER (ORDER BY created_at,id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS prev_quantity
                        FROM reklet.finished_goods
                        WHERE object_item_id=%s AND status='ready' AND quantity>0
                    ), updates AS (
                        SELECT id, GREATEST(quantity - GREATEST(LEAST(%s-prev_quantity,quantity),0),0) AS new_quantity
                        FROM ready_rows
                        WHERE prev_quantity < %s
                    )
                    UPDATE reklet.finished_goods fg
                    SET quantity=updates.new_quantity,
                        status=CASE WHEN updates.new_quantity=0 THEN 'shipped' ELSE 'ready' END
                    FROM updates
                    WHERE fg.id=updates.id
                    """,
                    (item_id, qty, qty),
                ),
                (
                    "INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'ship',%s)",
                    (item_id, object_id, qty),
                ),
                (
                    "INSERT INTO reklet.transport_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'ship',%s)",
                    (item_id, object_id, qty),
                ),
            ])
        elif kind == "arrive":
            statements.extend([
                (
                    """
                    WITH shipped_rows AS (
                        SELECT id, quantity,
                               COALESCE(SUM(quantity) OVER (ORDER BY created_at,id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS prev_quantity
                        FROM reklet.finished_goods
                        WHERE object_item_id=%s AND status='shipped' AND quantity>0
                    ), updates AS (
                        SELECT id, GREATEST(quantity - GREATEST(LEAST(%s-prev_quantity,quantity),0),0) AS new_quantity
                        FROM shipped_rows
                        WHERE prev_quantity < %s
                    )
                    UPDATE reklet.finished_goods fg
                    SET quantity=updates.new_quantity,
                        status=CASE WHEN updates.new_quantity=0 THEN 'arrived' ELSE 'shipped' END
                    FROM updates
                    WHERE fg.id=updates.id
                    """,
                    (item_id, qty, qty),
                ),
                (
                    "INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'arrive',%s)",
                    (item_id, object_id, qty),
                ),
                (
                    "INSERT INTO reklet.transport_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'arrive',%s)",
                    (item_id, object_id, qty),
                ),
            ])
        elif kind == "install":
            statements.extend([
                (
                    """
                    WITH arrived_rows AS (
                        SELECT id, quantity,
                               COALESCE(SUM(quantity) OVER (ORDER BY created_at,id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS prev_quantity
                        FROM reklet.finished_goods
                        WHERE object_item_id=%s AND status='arrived' AND quantity>0
                    ), updates AS (
                        SELECT id, GREATEST(quantity - GREATEST(LEAST(%s-prev_quantity,quantity),0),0) AS new_quantity
                        FROM arrived_rows
                        WHERE prev_quantity < %s
                    )
                    UPDATE reklet.finished_goods fg
                    SET quantity=updates.new_quantity,
                        status=CASE WHEN updates.new_quantity=0 THEN 'installed' ELSE 'arrived' END
                    FROM updates
                    WHERE fg.id=updates.id
                    """,
                    (item_id, qty, qty),
                ),
                (
                    "INSERT INTO reklet.installation_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'complete',%s)",
                    (item_id, object_id, qty),
                ),
            ])
    return statements


def _execute_change(object_id, change):
    statements = []

    produced_qty = (
        change["new"]["production"]
        + change["new"]["ready"]
        + change["new"]["shipped"]
        + change["new"]["arrived"]
        + change["new"]["installing"]
        + change["new"]["installed"]
    )
    if produced_qty > EPS:
        statements.extend(
            build_auto_material_reconciliation_statements(
                object_id,
                [(change["item_id"], produced_qty)],
            )
        )

    statements.extend(_build_stage_statements(change, object_id))

    # A production request is an internal workflow record, not a mandatory
    # user step. When the material has actually been supplied to production,
    # close any linked open request automatically. If no request exists,
    # nothing is created here.
    statements.append((
        """
        UPDATE reklet.material_production_requests r
        SET quantity_supplied=LEAST(
                r.quantity_requested,
                GREATEST(
                    r.quantity_supplied,
                    COALESCE((
                        SELECT SUM(mc.quantity)::numeric
                        FROM reklet.material_consumption mc
                        WHERE mc.object_item_id=r.object_item_id
                          AND mc.material_id=r.material_id
                    ),0)
                )
            ),
            status=CASE
                WHEN LEAST(
                    r.quantity_requested,
                    GREATEST(
                        r.quantity_supplied,
                        COALESCE((
                            SELECT SUM(mc.quantity)::numeric
                            FROM reklet.material_consumption mc
                            WHERE mc.object_item_id=r.object_item_id
                              AND mc.material_id=r.material_id
                        ),0)
                    )
                ) >= r.quantity_requested - 0.000001
                THEN 'completed'
                ELSE r.status
            END,
            updated_at=timezone('utc'::text,now())
        WHERE r.object_item_id=%s
          AND r.status IN ('sent','purchasing','ready')
        """,
        (change["item_id"],),
    ))

    correction = change["actions"].get("correction", 0)
    if correction or produced_qty > EPS:
        # The snapshot is created once and then kept stable for historical reconciliation.
        statements.append((
            """
            INSERT INTO reklet.object_item_material_costs(
                object_item_id,material_id,quantity_per_unit,waste_coefficient,unit_cost
            )
            SELECT oi.id,ptm.material_id,
                   COALESCE(ptm.quantity_per_unit,0),
                   COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                   COALESCE(m.cost_per_unit,0)
            FROM reklet.object_items oi
            JOIN reklet.product_template_materials ptm
              ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
            JOIN reklet.materials m ON m.id=ptm.material_id
            WHERE oi.id=%s
            ON CONFLICT (object_item_id,material_id) DO NOTHING
            """,
            (change["item_id"],),
        ))

    run_transaction(statements)


def _render_item_action_bar(object_id, item):
    st.markdown("#### Действие")
    stage_options = ["Изготовить", "Отгрузить", "Доставить", "Установить", "Изменить заказ"]
    action = st.selectbox(
        "Что сделать",
        stage_options,
        key=f"workspace_action_{item['id']}",
    )

    current = {
        "order": safe_float(item.get("quantity_needed", 0)),
        "new": safe_float(item.get("qty_new", 0)),
        "production": safe_float(item.get("qty_production", 0)),
        "ready": safe_float(item.get("qty_ready", 0)),
        "shipped": safe_float(item.get("qty_shipped", 0)),
        "arrived": safe_float(item.get("qty_arrived", 0)),
        "installed": safe_float(item.get("qty_installed", 0)),
    }
    if action == "Изготовить":
        maximum = current["new"] + current["production"]
        help_text = f"Доступно для изготовления: {_fmt_qty(maximum)}"
        min_value = 0.0
    elif action == "Отгрузить":
        maximum = current["ready"] + current["production"] + current["new"]
        help_text = f"Можно отгрузить до: {_fmt_qty(maximum)}"
        min_value = 0.0
    elif action == "Доставить":
        maximum = current["shipped"] + current["ready"] + current["production"] + current["new"]
        help_text = f"Можно доставить до: {_fmt_qty(maximum)}"
        min_value = 0.0
    elif action == "Установить":
        maximum = current["arrived"] + current["shipped"] + current["ready"] + current["production"] + current["new"]
        help_text = f"Можно установить до: {_fmt_qty(maximum)}"
        min_value = 0.0
    else:
        help_text = "Положительное число увеличит заказ, отрицательное — уменьшит необработанную часть."
        min_value = None

    qty_col, action_col = st.columns([2, 1], gap="small")
    with qty_col:
        if action == "Изменить заказ":
            quantity = st.number_input(
                "Изменение количества",
                value=0.0,
                step=1.0,
                format="%.0f",
                help=help_text,
                key=f"workspace_action_qty_{item['id']}",
            )
        else:
            quantity = st.number_input(
                "Количество",
                min_value=min_value,
                value=0.0,
                step=1.0,
                format="%.2f",
                help=help_text,
                key=f"workspace_action_qty_{item['id']}",
            )
    with action_col:
        st.write("")
        execute = st.button(
            "Применить",
            key=f"workspace_execute_{item['id']}",
            type="primary",
            use_container_width=True,
        )

    if not execute:
        return
    if abs(quantity) <= EPS:
        st.warning("Укажите количество.")
        return

    change, error = _apply_stage_action(object_id, item, action, quantity)
    if error:
        st.error(error)
        return

    st.session_state[f"workspace_pending_change_{item['id']}"] = change
    st.rerun()


def _render_pending_change(object_id, item):
    key = f"workspace_pending_change_{item['id']}"
    change = st.session_state.get(key)
    if not change:
        return False

    st.warning("Подтвердить изменение?")
    old = change["old"]
    new = change["new"]
    rows = [
        ["Заказ", old["order"], new["order"]],
        ["Не изготовлено", old["new"], new["new"]],
        ["В производстве", old["production"], new["production"]],
        ["Готово на складе", old["ready"], new["ready"]],
        ["В пути", old["shipped"], new["shipped"]],
        ["На объекте", old["arrived"], new["arrived"]],
        ["Установлено", old["installed"], new["installed"]],
    ]
    preview = pd.DataFrame(rows, columns=["Показатель", "Было", "Станет"])
    st.dataframe(preview, width="stretch", hide_index=True)

    c1, c2 = st.columns(2, gap="small")
    with c1:
        confirm = st.button("Подтвердить", key=f"workspace_confirm_{item['id']}", type="primary", use_container_width=True)
    with c2:
        cancel = st.button("Отмена", key=f"workspace_cancel_{item['id']}", use_container_width=True)

    if cancel:
        st.session_state.pop(key, None)
        st.rerun()
    if confirm:
        try:
            _execute_change(object_id, change)
            st.session_state.pop(key, None)
            st.success("Изменение выполнено.")
            st.rerun()
        except Exception as exc:
            st.error("Изменение не выполнено. Транзакция отменена.")
            st.code(str(exc))
    return True


def _render_add_item(object_id, object_row):
    st.markdown("#### Добавить изделие в объект")
    templates = get_templates()
    client_name = str(object_row.get("client_name") or "").strip()
    if client_name:
        templates = templates[
            templates["client_name"].fillna("").astype(str).str.strip().eq(client_name)
        ].copy()
    if templates.empty:
        st.info("У заказчика нет доступных изделий.")
        return

    label_to_id = {
        f"{int(row['id'])} — {str(row['name'] or '').strip()}": int(row["id"])
        for _, row in templates.iterrows()
    }
    selected = st.selectbox(
        "Изделие",
        list(label_to_id.keys()),
        key=f"workspace_add_template_{object_id}",
    )
    qty = st.number_input(
        "Количество",
        min_value=1,
        value=1,
        step=1,
        key=f"workspace_add_qty_{object_id}",
    )
    if st.button("Добавить", key=f"workspace_add_button_{object_id}", use_container_width=True):
        template_id = label_to_id[selected]
        existing = get_object_items(object_id)
        statements = []
        if not existing.empty:
            same = existing[
                existing.apply(
                    lambda r: safe_int(r.get("product_template_id") if pd.notna(r.get("product_template_id")) else r.get("template_id")) == template_id,
                    axis=1,
                )
            ]
        else:
            same = existing
        if same.empty:
            statements.append((
                """
                INSERT INTO reklet.object_items(
                    object_id,product_template_id,template_id,quantity_needed,
                    item_name,quantity,qty_new,status,production_status,installation_status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'New','not_started','not_started')
                """,
                (object_id, template_id, template_id, int(qty), str(selected.split(" — ", 1)[1]), int(qty), int(qty)),
            ))
        else:
            item_id = safe_int(same.iloc[0]["id"])
            statements.append((
                """
                UPDATE reklet.object_items
                SET quantity_needed=COALESCE(quantity_needed,0)+%s,
                    quantity=COALESCE(quantity,0)+%s,
                    qty_new=COALESCE(qty_new,0)+%s
                WHERE id=%s AND object_id=%s
                """,
                (int(qty), int(qty), int(qty), item_id, object_id),
            ))
        try:
            run_transaction(statements)
            st.success("Изделие добавлено в объект.")
            st.rerun()
        except Exception as exc:
            st.error("Изделие не добавлено.")
            st.code(str(exc))


def render_workspace():
    ensure_material_planning_tables()
    ensure_task_three_tables()
    ensure_stage_movement_tables()

    st.header("Рабочее место")
    st.caption("Вся работа по заказу выполняется из одного контекста: заказчик → объект → изделие.")

    with st.expander("Создать новый объект", expanded=False):
        _render_create_object_workspace()

    object_id, object_row = _get_selected_object()
    if object_id is None:
        return

    items = get_object_items(object_id)
    active_items = items.copy()
    if not active_items.empty:
        numeric = active_items[
            ["quantity_needed", "qty_new", "qty_production", "qty_ready", "qty_shipped", "qty_arrived", "qty_installing", "qty_installed"]
        ].apply(pd.to_numeric, errors="coerce").fillna(0)
        active_items = active_items[numeric.ne(0).any(axis=1)].copy()

    object_name = str(object_row.get("object_name") or "").strip()
    client_name = str(object_row.get("client_name") or "").strip()

    st.markdown(f"### {object_name}")
    st.caption(f"Заказчик: {client_name} · Адрес: {str(object_row.get('address') or '').strip()}")

    total_order = safe_float(active_items["quantity_needed"].sum()) if not active_items.empty else 0.0
    installed = safe_float(active_items["qty_installed"].sum()) if not active_items.empty else 0.0
    in_production = safe_float(active_items["qty_production"].sum()) if not active_items.empty else 0.0
    ready = safe_float(active_items["qty_ready"].sum()) if not active_items.empty else 0.0
    in_transit = safe_float(active_items["qty_shipped"].sum()) if not active_items.empty else 0.0

    m1, m2, m3, m4, m5 = st.columns(5, gap="small")
    m1.metric("Изделий", _fmt_qty(total_order, 0))
    m2.metric("В производстве", _fmt_qty(in_production, 0))
    m3.metric("Готово", _fmt_qty(ready, 0))
    m4.metric("В пути", _fmt_qty(in_transit, 0))
    m5.metric("Установлено", _fmt_qty(installed, 0))

    st.markdown("---")
    st.markdown("#### Изделия объекта")
    if active_items.empty:
        st.info("В объекте пока нет изделий.")
        _render_add_item(object_id, object_row)
        return

    item_view = active_items[[
        "id", "item_name", "quantity_needed", "qty_new", "qty_production",
        "qty_ready", "qty_shipped", "qty_arrived", "qty_installed",
    ]].copy()
    item_view.columns = [
        "ID", "Изделие", "Заказ", "Осталось изготовить", "В производстве",
        "Готово", "В пути", "На объекте", "Установлено",
    ]
    st.dataframe(item_view, width="stretch", hide_index=True)

    item_options = [
        f"{int(row['id'])} — {str(row['item_name'] or '').strip()}"
        for _, row in active_items.iterrows()
    ]
    selected_item_label = st.selectbox(
        "Изделие для работы",
        item_options,
        key=f"workspace_item_{object_id}",
    )
    item_id = int(selected_item_label.split(" — ", 1)[0])
    item = _get_item_state(object_id, item_id)
    if item is None:
        st.warning("Изделие не найдено.")
        return

    st.markdown("---")
    st.markdown(f"### {str(item.get('item_name') or '').strip()}")
    st.caption(
        " → ".join([
            f"Заказ {_fmt_qty(item.get('quantity_needed',0),0)}",
            f"Производство {_fmt_qty(item.get('qty_production',0),0)}",
            f"Готово {_fmt_qty(item.get('qty_ready',0),0)}",
            f"В пути {_fmt_qty(item.get('qty_shipped',0),0)}",
            f"На объекте {_fmt_qty(item.get('qty_arrived',0),0)}",
            f"Установлено {_fmt_qty(item.get('qty_installed',0),0)}",
        ])
    )

    if not _render_pending_change(object_id, item):
        _render_item_action_bar(object_id, item)

    tab1, tab2, tab3 = st.tabs(["Материалы", "История", "Данные"])
    with tab1:
        _render_materials(object_id, item_id, item)
    with tab2:
        _render_history(object_id, item_id)
    with tab3:
        data = pd.DataFrame({
            "Показатель": [
                "ID", "Количество по заказу", "Осталось изготовить",
                "В производстве", "Готово", "В пути", "На объекте",
                "Установлено", "Производство", "Монтаж",
            ],
            "Значение": [
                safe_int(item.get("id")),
                safe_float(item.get("quantity_needed")),
                safe_float(item.get("qty_new")),
                safe_float(item.get("qty_production")),
                safe_float(item.get("qty_ready")),
                safe_float(item.get("qty_shipped")),
                safe_float(item.get("qty_arrived")),
                safe_float(item.get("qty_installed")),
                str(item.get("production_status") or ""),
                str(item.get("installation_status") or ""),
            ],
        })
        st.dataframe(data, width="stretch", hide_index=True)
        render_print_html(
            f"Изделие — {str(item.get('item_name') or '').strip()}",
            data,
            f"print_workspace_item_{item_id}",
        )

    st.markdown("---")
    _render_add_item(object_id, object_row)
