import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.dates import as_date
from core.formatting import safe_int, safe_float
from core.printing import render_print_html
from core.ui import render_button_nav
from core.instructions import render_page_instruction
from database.migrations import ensure_stage_movement_tables
from repositories.clients import get_clients
from repositories.objects import get_objects, get_object_items
from repositories.products import get_templates
from services.object_management import calculate_object_management_change
from services.material_reconciliation import build_auto_material_reconciliation_statements


def select_object_by_customer(prefix):
    clients = get_clients()
    objects = get_objects().sort_values("id", ascending=False).copy()

    if clients.empty:
        st.info("Заказчики отсутствуют.")
        return None, None
    if objects.empty:
        st.info("Объектов нет.")
        return None, None

    client_rows = clients[["id", "name"]].copy()
    client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
    client_rows = client_rows[client_rows["name"] != ""].drop_duplicates(subset=["id"])
    client_options = [
        f"{int(r['id'])} — {r['name']}"
        for _, r in client_rows.iterrows()
    ]

    selected_client = st.selectbox(
        "Заказчик",
        ["— Выберите заказчика —"] + client_options,
        index=0,
        key=f"{prefix}_customer_select"
    )

    if selected_client == "— Выберите заказчика —":
        st.info("Сначала выберите заказчика.")
        return None, None

    client_id = int(selected_client.split(" — ")[0])
    client_objects = objects[
        pd.to_numeric(objects["client_id"], errors="coerce").eq(client_id)
    ].copy()

    if client_objects.empty:
        st.info("У выбранного заказчика нет объектов.")
        return None, None

    object_options = [
        f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
        for _, r in client_objects.iterrows()
    ]

    selected_object = st.selectbox(
        "Объект",
        ["— Выберите объект —"] + object_options,
        index=0,
        key=f"{prefix}_object_select_{client_id}"
    )

    if selected_object == "— Выберите объект —":
        st.info("Теперь выберите объект.")
        return None, None

    object_id = int(selected_object.split(" — ")[0])
    object_row = client_objects[client_objects["id"] == object_id].iloc[0]
    return object_id, object_row



def _render_object_data(object_id):
                    clients = get_clients()
                    client_rows = clients[["id", "name"]].copy()
                    client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
                    client_rows = client_rows[client_rows["name"] != ""]
                    object_data = run_query(
                        """
                        SELECT
                            o.id,
                            o.client_id,
                            c.name AS client_name,
                            o.object_name,
                            o.address,
                            o.transport_distance_km,
                            o.created_at,
                            o.phone,
                            o.contact_person,
                            o.notes,
                            o.contract_date,
                            o.production_start_date,
                            o.production_end_date,
                            o.installation_date,
                            o.installation_end_date
                        FROM reklet.objects o
                        LEFT JOIN reklet.clients c ON c.id = o.client_id
                        WHERE o.id = %s
                        """,
                        (object_id,), fetch=True
                    )

                    if object_data.empty:
                        st.warning("Выбранный объект не найден.")
                    else:
                        original = object_data.iloc[0].copy()

                        original_dates = {
                            "contract_date": as_date(original.get("contract_date")),
                            "production_start_date": as_date(original.get("production_start_date")),
                            "production_end_date": as_date(original.get("production_end_date")),
                            "installation_date": as_date(original.get("installation_date")),
                            "installation_end_date": as_date(original.get("installation_end_date")),
                        }

                        client_name_to_id = {
                            str(r["name"]).strip(): int(r["id"])
                            for _, r in client_rows.iterrows()
                        }
                        client_names = list(client_name_to_id.keys())

                        # Печатное представление сохраняем, но в вертикальном виде.
                        object_view = pd.DataFrame({
                            "Поле": [
                                "ID", "ID заказчика", "Заказчик", "Объект", "Адрес",
                                "Расстояние до объекта, км", "Телефон", "Контактное лицо",
                                "Примечания", "Дата договора", "Начало производства",
                                "Окончание производства", "Дата монтажа", "Окончание монтажа", "Создан"
                            ],
                            "Значение": [
                                safe_int(original.get("id")), safe_int(original.get("client_id")),
                                str(original.get("client_name") or "").strip(),
                                str(original.get("object_name") or "").strip(),
                                str(original.get("address") or "").strip(),
                                safe_float(original.get("transport_distance_km")),
                                str(original.get("phone") or "").strip(),
                                str(original.get("contact_person") or "").strip(),
                                str(original.get("notes") or "").strip(),
                                original_dates["contract_date"], original_dates["production_start_date"],
                                original_dates["production_end_date"], original_dates["installation_date"],
                                original_dates["installation_end_date"],
                                str(original.get("created_at") or "") if pd.notna(original.get("created_at")) else "",
                            ],
                        })
                        render_print_html(
                            f"Данные объекта — {str(original.get('object_name') or '').strip()}",
                            object_view,
                            f"print_object_data_{object_id}",
                            subtitle=f"Заказчик: {str(original.get('client_name') or '').strip()}"
                        )

                        # Вертикальная форма: параметр слева, значение справа.
                        with st.form(f"object_data_form_{object_id}", clear_on_submit=False):
                            c1, c2 = st.columns([1, 2], gap="small")
                            with c1: st.markdown("**ID**")
                            with c2:
                                st.text_input("ID", value=str(safe_int(original.get("id"))), disabled=True,
                                              label_visibility="collapsed", key=f"obj_id_{object_id}")

                            c1, c2 = st.columns([1, 2], gap="small")
                            with c1: st.markdown("**ID заказчика**")
                            with c2:
                                st.text_input("ID заказчика", value=str(safe_int(original.get("client_id"))), disabled=True,
                                              label_visibility="collapsed", key=f"obj_client_id_{object_id}")

                            current_client_name = str(original.get("client_name") or "").strip()
                            c1, c2 = st.columns([1, 2], gap="small")
                            with c1: st.markdown("**Заказчик**")
                            with c2:
                                edited_client_name = st.selectbox(
                                    "Заказчик", client_names,
                                    index=client_names.index(current_client_name) if current_client_name in client_names else 0,
                                    key=f"obj_client_name_{object_id}", label_visibility="collapsed"
                                )

                            fields = [
                                ("Объект", "obj_name", str(original.get("object_name") or "").strip()),
                                ("Адрес", "obj_address", str(original.get("address") or "").strip()),
                                ("Телефон", "obj_phone", str(original.get("phone") or "").strip()),
                                ("Контактное лицо", "obj_contact", str(original.get("contact_person") or "").strip()),
                                ("Примечания", "obj_notes", str(original.get("notes") or "").strip()),
                            ]
                            edited_text = {}
                            for label, key_name, value in fields:
                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown(f"**{label}**")
                                with c2:
                                    edited_text[key_name] = st.text_input(
                                        label, value=value, label_visibility="collapsed",
                                        key=f"{key_name}_{object_id}"
                                    )

                            c1, c2 = st.columns([1, 2], gap="small")
                            with c1: st.markdown("**Расстояние до объекта, км**")
                            with c2:
                                edited_distance = st.number_input(
                                    "Расстояние до объекта, км", min_value=0.0,
                                    value=max(0.0, safe_float(original.get("transport_distance_km"))), step=0.1,
                                    label_visibility="collapsed", key=f"obj_distance_{object_id}"
                                )

                            date_fields = [
                                ("Дата договора", "contract_date", f"obj_contract_{object_id}"),
                                ("Начало производства", "production_start_date", f"obj_prod_start_{object_id}"),
                                ("Окончание производства", "production_end_date", f"obj_prod_end_{object_id}"),
                                ("Дата монтажа", "installation_date", f"obj_install_{object_id}"),
                                ("Окончание монтажа", "installation_end_date", f"obj_install_end_{object_id}"),
                            ]
                            edited_dates = {}
                            for label, field_name, field_key in date_fields:
                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown(f"**{label}**")
                                with c2:
                                    default_date = original_dates[field_name]
                                    edited_dates[field_name] = st.date_input(
                                        label, value=default_date,
                                        label_visibility="collapsed", key=field_key
                                    )

                            c1, c2 = st.columns([1, 2], gap="small")
                            with c1: st.markdown("**Создан**")
                            with c2:
                                st.text_input(
                                    "Создан",
                                    value=str(original.get("created_at") or "") if pd.notna(original.get("created_at")) else "",
                                    disabled=True, label_visibility="collapsed", key=f"obj_created_{object_id}"
                                )

                            execute_object_data = st.form_submit_button("Выполнить", use_container_width=True)

                        pending_key = f"object_data_pending_{object_id}"

                        if execute_object_data:
                            new_client_name = str(edited_client_name or "").strip()
                            new_object_name = str(edited_text["obj_name"] or "").strip()
                            new_distance = safe_float(edited_distance)
                            errors = []

                            if new_client_name not in client_name_to_id:
                                errors.append("Необходимо выбрать существующего заказчика.")
                            if not new_object_name:
                                errors.append("Название объекта не может быть пустым.")
                            if new_distance < 0:
                                errors.append("Расстояние до объекта не может быть отрицательным.")

                            new_values = {
                                "client_id": client_name_to_id.get(new_client_name),
                                "object_name": new_object_name,
                                "address": edited_text["obj_address"].strip() or None,
                                "transport_distance_km": new_distance,
                                "phone": edited_text["obj_phone"].strip() or None,
                                "contact_person": edited_text["obj_contact"].strip() or None,
                                "notes": edited_text["obj_notes"].strip() or None,
                                "contract_date": edited_dates["contract_date"],
                                "production_start_date": edited_dates["production_start_date"],
                                "production_end_date": edited_dates["production_end_date"],
                                "installation_date": edited_dates["installation_date"],
                                "installation_end_date": edited_dates["installation_end_date"],
                            }

                            comparisons = [
                                ("client_id", "Заказчик", str(original.get("client_name") or "").strip(), new_client_name),
                                ("object_name", "Объект", str(original.get("object_name") or "").strip(), new_values["object_name"]),
                                ("address", "Адрес", str(original.get("address") or "").strip(), new_values["address"] or ""),
                                ("transport_distance_km", "Расстояние до объекта, км", safe_float(original.get("transport_distance_km")), new_values["transport_distance_km"]),
                                ("phone", "Телефон", str(original.get("phone") or "").strip(), new_values["phone"] or ""),
                                ("contact_person", "Контактное лицо", str(original.get("contact_person") or "").strip(), new_values["contact_person"] or ""),
                                ("notes", "Примечания", str(original.get("notes") or "").strip(), new_values["notes"] or ""),
                                ("contract_date", "Дата договора", original_dates["contract_date"], new_values["contract_date"]),
                                ("production_start_date", "Начало производства", original_dates["production_start_date"], new_values["production_start_date"]),
                                ("production_end_date", "Окончание производства", original_dates["production_end_date"], new_values["production_end_date"]),
                                ("installation_date", "Дата монтажа", original_dates["installation_date"], new_values["installation_date"]),
                                ("installation_end_date", "Окончание монтажа", original_dates["installation_end_date"], new_values["installation_end_date"]),
                            ]
                            changes = []
                            for key, label, old_val, new_val in comparisons:
                                if key == "transport_distance_km":
                                    old_cmp = round(float(old_val or 0), 6)
                                    new_cmp = round(float(new_val or 0), 6)
                                elif key in {"contract_date", "production_start_date", "production_end_date", "installation_date", "installation_end_date"}:
                                    old_cmp = old_val.isoformat() if old_val else None
                                    new_cmp = new_val.isoformat() if new_val else None
                                else:
                                    old_cmp = str(old_val or "")
                                    new_cmp = str(new_val or "")
                                if old_cmp != new_cmp:
                                    changes.append({
                                        "Поле": label,
                                        "Было": old_val if old_val not in (None, "") else "—",
                                        "Станет": new_val if new_val not in (None, "") else "—",
                                    })

                            if errors:
                                for err in errors:
                                    st.error(err)
                            elif changes:
                                st.session_state[pending_key] = {
                                    "object_id": object_id,
                                    "values": new_values,
                                    "changes": changes,
                                }
                            else:
                                st.info("Изменений нет.")

                        pending = st.session_state.get(pending_key)
                        if pending:
                            st.markdown("---")
                            st.subheader("Подтверждение изменений")
                            st.dataframe(pd.DataFrame(pending["changes"]), width="stretch", hide_index=True)
                            c1, c2 = st.columns(2)
                            with c1:
                                confirm_changes = st.button(
                                    "Подтвердить", key=f"confirm_object_data_{object_id}",
                                    type="primary", use_container_width=True
                                )
                            with c2:
                                cancel_changes = st.button(
                                    "Отмена", key=f"cancel_object_data_{object_id}", use_container_width=True
                                )

                            if confirm_changes:
                                v = pending["values"]
                                try:
                                    run_transaction([
                                        (
                                            """
                                            UPDATE reklet.objects
                                            SET client_id=%s,
                                                object_name=%s,
                                                address=%s,
                                                transport_distance_km=%s,
                                                phone=%s,
                                                contact_person=%s,
                                                notes=%s,
                                                contract_date=%s,
                                                production_start_date=%s,
                                                production_end_date=%s,
                                                installation_date=%s,
                                                installation_end_date=%s
                                            WHERE id=%s
                                            """,
                                            (
                                                v["client_id"], v["object_name"], v["address"],
                                                v["transport_distance_km"], v["phone"], v["contact_person"],
                                                v["notes"], v["contract_date"], v["production_start_date"],
                                                v["production_end_date"], v["installation_date"],
                                                v["installation_end_date"], object_id
                                            )
                                        )
                                    ])
                                    st.session_state.pop(pending_key, None)
                                    st.success("Данные объекта изменены.")
                                    st.rerun()
                                except Exception as e:
                                    st.error("Изменения не сохранены. Транзакция отменена.")
                                    st.code(str(e))

                            if cancel_changes:
                                st.session_state.pop(pending_key, None)
                                st.rerun()

                        # Existing safe deletion block remains in its closed expander.
                        with st.expander("Безопасное удаление объекта"):
                            st.warning(
                                "Удаление необратимо. Объект можно удалить только если в системе нет "
                                "изделий, готовой продукции и истории производства, отгрузки, доставки, материалов или монтажа."
                            )
                            delete_confirm = st.checkbox(
                                "Я подтверждаю удаление выбранного объекта.",
                                key=f"confirm_delete_object_{object_id}"
                            )
                            if st.button(
                                "Удалить объект",
                                key=f"delete_object_{object_id}",
                                disabled=not delete_confirm,
                                use_container_width=True
                            ):
                                refs = run_query(
                                    """
                                    SELECT
                                        (SELECT COUNT(*) FROM reklet.object_items WHERE object_id=%s) AS object_items,
                                        (SELECT COUNT(*) FROM reklet.production_transactions WHERE object_id=%s) AS production_transactions,
                                        (SELECT COUNT(*) FROM reklet.finished_goods WHERE object_id=%s) AS finished_goods,
                                        (SELECT COUNT(*) FROM reklet.finished_goods_transactions WHERE object_id=%s) AS finished_goods_transactions,
                                        (SELECT COUNT(*) FROM reklet.transport_transactions WHERE object_id=%s) AS transport_transactions,
                                        (SELECT COUNT(*) FROM reklet.installation_transactions WHERE object_id=%s) AS installation_transactions,
                                        (SELECT COUNT(*) FROM reklet.material_transactions WHERE object_id=%s) AS material_transactions,
                                        (SELECT COUNT(*) FROM reklet.material_reservations WHERE object_id=%s) AS material_reservations,
                                        (SELECT COUNT(*) FROM reklet.purchase_order_items WHERE object_id=%s) AS purchase_order_items,
                                        (SELECT COUNT(*) FROM reklet.material_consumption WHERE object_id=%s) AS material_consumption
                                    """,
                                    (object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id),
                                    fetch=True
                                ).iloc[0]

                                ref_labels = {
                                    "object_items": "изделия объекта",
                                    "production_transactions": "история производства",
                                    "finished_goods": "готовая продукция",
                                    "finished_goods_transactions": "история движения готовой продукции",
                                    "transport_transactions": "история транспортировки",
                                    "installation_transactions": "история монтажа",
                                    "material_transactions": "движения материалов по объекту",
                                    "material_reservations": "резерв материалов по объекту",
                                    "purchase_order_items": "закупки материалов по объекту",
                                    "material_consumption": "списание материалов в производстве",
                                }
                                blocking_refs = [
                                    label for key, label in ref_labels.items()
                                    if int(refs.get(key, 0) or 0) > 0
                                ]
                                if blocking_refs:
                                    st.error(
                                        "Удаление запрещено. Связанные данные: " + ", ".join(blocking_refs) + "."
                                    )
                                else:
                                    try:
                                        run_query("DELETE FROM reklet.objects WHERE id=%s", (object_id,))
                                        st.success("Объект безопасно удалён.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Удаление не выполнено. База данных не изменилась.")
                                        st.code(str(e))



def _render_add_items(object_id, object_row):
        client_name = str(object_row.get("client_name", "") or "").strip()
        object_name = str(object_row.get("object_name", "") or "").strip()

        st.subheader(f"Добавить изделия в объект: {object_name}")
        st.caption(f"Заказчик: {client_name}")

        templates = get_templates()
        if client_name:
            templates = templates[
                templates["client_name"].fillna("").astype(str).str.strip().eq(client_name)
            ].copy()
        else:
            templates = templates.iloc[0:0].copy()

        if templates.empty:
            st.info("Для заказчика этого объекта ещё не созданы изделия.")
        else:
            # Показываем общее уже заказанное количество и отдельно
            # количество, которое пользователь хочет добавить сейчас.
            current_items_for_add = get_object_items(object_id)
            ordered_by_template = {}
            if not current_items_for_add.empty:
                for _, existing in current_items_for_add.iterrows():
                    template_value = (
                        existing.get("product_template_id")
                        if pd.notna(existing.get("product_template_id"))
                        else existing.get("template_id")
                    )
                    if pd.notna(template_value):
                        ordered_by_template[safe_int(template_value)] = safe_int(
                            existing.get("quantity_needed")
                        )

            add_df = templates[["id", "name", "client_name", "category"]].copy()
            add_df.insert(0, "Выбрать", False)
            add_df["Заказано"] = (
                add_df["id"].map(ordered_by_template).fillna(0).astype(int)
            )
            add_df["Количество"] = 0
            add_df.columns = [
                "Выбрать", "ID", "Изделие", "Заказчик", "Категория",
                "Заказано", "Количество"
            ]

            with st.form(f"add_items_form_{object_id}", clear_on_submit=False):
                edited_add = st.data_editor(
                    add_df,
                    key=f"add_items_editor_{object_id}",
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Выбрать": st.column_config.CheckboxColumn("Выбрать"),
                        "ID": st.column_config.NumberColumn("ID", disabled=True),
                        "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                        "Заказчик": st.column_config.TextColumn("Заказчик", disabled=True),
                        "Категория": st.column_config.TextColumn("Категория", disabled=True),
                        "Заказано": st.column_config.NumberColumn("Заказано", disabled=True, format="%d"),
                        "Количество": st.column_config.NumberColumn("Количество", min_value=0, step=1, format="%d"),
                    },
                    disabled=["ID", "Изделие", "Заказчик", "Категория", "Заказано"],
                )
                execute_add = st.form_submit_button("Добавить выбранные изделия", use_container_width=True)

            if execute_add:
                selected_rows = edited_add[
                    edited_add["Выбрать"].fillna(False)
                    & (pd.to_numeric(edited_add["Количество"], errors="coerce").fillna(0) > 0)
                ].copy()

                if selected_rows.empty:
                    st.warning("Выберите хотя бы одно изделие и укажите количество.")
                else:
                    # Не делаем st.rerun(): после выполнения остаёмся в этом же разделе и объекте.
                    statements = []
                    for _, r in selected_rows.iterrows():
                        template_id = safe_int(r["ID"])
                        qty = safe_int(r["Количество"])
                        item_name = str(r["Изделие"] or "").strip()

                        # Сначала увеличиваем существующую строку.
                        statements.append((
                            """
                            UPDATE reklet.object_items
                            SET quantity = COALESCE(quantity,0) + %s,
                                quantity_needed = COALESCE(quantity_needed,0) + %s,
                                qty_new = COALESCE(qty_new,0) + %s
                            WHERE object_id=%s
                              AND (product_template_id=%s OR template_id=%s)
                            """,
                            (qty, qty, qty, object_id, template_id, template_id)
                        ))

                        # Если строки нет — создаём её.
                        statements.append((
                            """
                            INSERT INTO reklet.object_items
                                (object_id, product_template_id, template_id,
                                 quantity_needed, item_name, quantity, qty_new, status)
                            SELECT %s,%s,%s,%s,%s,%s,%s,'New'
                            WHERE NOT EXISTS (
                                SELECT 1
                                FROM reklet.object_items
                                WHERE object_id=%s
                                  AND (product_template_id=%s OR template_id=%s)
                            )
                            """,
                            (
                                object_id, template_id, template_id,
                                qty, item_name, qty, qty,
                                object_id, template_id, template_id
                            )
                        ))
                        statements.append((
                            """
                            INSERT INTO reklet.object_item_material_costs
                                (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                            SELECT oi.id,
                                   ptm.material_id,
                                   COALESCE(ptm.quantity_per_unit,0),
                                   COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                                   COALESCE(m.cost_per_unit,0)
                            FROM reklet.object_items oi
                            JOIN reklet.product_template_materials ptm
                              ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                            JOIN reklet.materials m ON m.id=ptm.material_id
                            WHERE oi.object_id=%s
                              AND (oi.product_template_id=%s OR oi.template_id=%s)
                            ON CONFLICT (object_item_id,material_id) DO NOTHING
                            """,
                            (object_id, template_id, template_id)
                        ))

                    try:
                        run_transaction(statements)
                        # Проверяем результат сразу, не полагаясь на состояние интерфейса.
                        saved = get_object_items(object_id)
                        saved_ids = set()
                        for _, rr in saved.iterrows():
                            if pd.notna(rr.get("product_template_id")):
                                saved_ids.add(int(rr["product_template_id"]))
                            if pd.notna(rr.get("template_id")):
                                saved_ids.add(int(rr["template_id"]))

                        expected_ids = {safe_int(x) for x in selected_rows["ID"].tolist()}
                        if expected_ids.issubset(saved_ids):
                            st.success(f"Добавлено изделий: {len(selected_rows)}.")
                            # Сбрасываем состояние редактора, чтобы после
                            # выполнения таблица заново получила актуальное
                            # значение «Заказано», а «Количество» стало 0.
                            st.session_state.pop(f"add_items_editor_{object_id}", None)
                            st.rerun()
                        else:
                            st.error("Операция выполнена не полностью: не все изделия появились в составе объекта.")
                    except Exception as e:
                        st.error(f"Не удалось добавить изделия: {e}")

        st.markdown("---")
        current_items = get_object_items(object_id)
        st.subheader("Изделия объекта")
        if current_items.empty:
            st.info("Для этого объекта ещё не созданы изделия.")
        else:
            display_items = current_items.copy()
            stage_columns = [
                "quantity", "qty_production", "qty_ready", "qty_shipped",
                "qty_arrived", "qty_installing", "qty_installed"
            ]
            numeric = display_items[stage_columns].apply(pd.to_numeric, errors="coerce").fillna(0)
            active_mask = numeric.ne(0).any(axis=1)
            display_items = display_items.loc[active_mask].copy()

            if display_items.empty:
                st.info("В составе объекта нет актуальных изделий.")
            else:
                view = display_items[["id", "item_name", "quantity", "qty_production", "qty_ready", "qty_shipped", "qty_arrived", "qty_installing", "qty_installed"]].copy()
                view.columns = ["ID", "Изделие", "Количество", "Производство", "Готовая продукция", "Отгружено", "Прибыло", "Монтаж", "Смонтировано"]
                st.dataframe(view, width="stretch", hide_index=True)


def _render_object_management():
        objects = get_objects().sort_values("id", ascending=False).copy()
        clients = get_clients()
        ensure_stage_movement_tables()

        if objects.empty:
            st.info("Объектов нет.")
        else:
            client_options = ["Все заказчики"] + (
                clients["name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].sort_values().unique().tolist()
                if not clients.empty else []
            )
            selected_client = st.selectbox(
                "Заказчик",
                client_options,
                key="management_client_filter"
            )

            filtered_objects = objects.copy()
            if selected_client != "Все заказчики":
                client_ids = clients[
                    clients["name"].fillna("").astype(str).str.strip().eq(selected_client)
                ]["id"].tolist()
                filtered_objects = filtered_objects[
                    filtered_objects["client_id"].isin(client_ids)
                ].copy()

            if filtered_objects.empty:
                st.info("У выбранного заказчика нет объектов.")
            else:
                object_options = [
                    f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
                    for _, r in filtered_objects.iterrows()
                ]
                object_map = {
                    label: int(label.split(" — ")[0]) for label in object_options
                }
                selected_object_label = st.selectbox(
                    "Объект",
                    object_options,
                    key="management_object_filter"
                )
                object_id = object_map[selected_object_label]
                object_row = filtered_objects[filtered_objects["id"] == object_id].iloc[0]

                templates = get_templates()
                client_name = str(object_row.get("client_name", "") or "").strip()
                if client_name:
                    templates = templates[
                        templates["client_name"].fillna("").astype(str).str.strip().eq(client_name)
                    ].copy()
                else:
                    templates = templates.iloc[0:0].copy()

                current = get_object_items(object_id)
                current_map = {}
                if not current.empty:
                    for _, r in current.iterrows():
                        tid = r["product_template_id"] if pd.notna(r["product_template_id"]) else r["template_id"]
                        if pd.notna(tid):
                            current_map[int(tid)] = r

                # One row per product. Existing object items are retained even if
                # the product template is no longer present in the client filter.
                template_rows = {int(t["id"]): t for _, t in templates.iterrows()}
                product_ids = sorted(set(template_rows) | set(current_map))

                rows = []
                for tid in product_ids:
                    t = template_rows.get(tid)
                    old = current_map.get(tid)
                    name = str(
                        (t["name"] if t is not None else old.get("item_name", ""))
                        or ""
                    ).strip()

                    ordered = safe_int(old["quantity_needed"]) if old is not None else 0
                    qty_production = safe_int(old["qty_production"]) if old is not None else 0
                    qty_ready = safe_int(old["qty_ready"]) if old is not None else 0
                    qty_shipped = safe_int(old["qty_shipped"]) if old is not None else 0
                    qty_arrived = safe_int(old["qty_arrived"]) if old is not None else 0
                    qty_installing = safe_int(old["qty_installing"]) if old is not None else 0
                    qty_installed = safe_int(old["qty_installed"]) if old is not None else 0

                    # Keep the quantity identity derived from the physical stages.
                    # Older records may have stale qty_new values; deriving it here
                    # prevents the management screen from displaying a false remainder.
                    physical_allocated = (
                        qty_production + qty_ready + qty_shipped +
                        qty_arrived + qty_installing + qty_installed
                    )
                    qty_new = max(ordered - physical_allocated, 0)
                    remaining_manufacture = qty_new

                    rows.append({
                        "ID": tid,
                        "Изделие": name,
                        "1.1 Всего": ordered,
                        "1.2 Коррекция": 0,
                        "2.1 Осталось изготовить": remaining_manufacture,
                        "2.2 Изготовлено": 0,
                        "3.2 Прибыло": qty_ready,
                        "3.3 Отгружено": 0,
                        "3.4 Осталось": qty_ready,
                        "4.1 В пути": qty_shipped,
                        "4.2 Доставлен": 0,
                        "5.1 Получено": qty_arrived,
                        "5.2 Установлено": 0,
                        "5.4 Всего установлено": qty_installed,
                        "_qty_new": qty_new,
                        "_qty_production": qty_production,
                        "_qty_ready": qty_ready,
                        "_qty_shipped": qty_shipped,
                        "_qty_arrived": qty_arrived,
                        "_qty_installing": qty_installing,
                        "_qty_installed": qty_installed,
                    })

                if not rows:
                    st.info("Для этого заказчика ещё не созданы изделия.")
                else:
                    management_df = pd.DataFrame(rows)
                    editor_columns = [
                        "ID", "Изделие",
                        "1.1 Всего", "1.2 Коррекция",
                        "2.1 Осталось изготовить", "2.2 Изготовлено",
                        "3.2 Прибыло", "3.3 Отгружено", "3.4 Осталось",
                        "4.1 В пути", "4.2 Доставлен",
                        "5.1 Получено", "5.2 Установлено", "5.4 Всего установлено"
                    ]
                    editor_df = management_df[editor_columns].copy()

                    with st.form(f"object_management_form_{object_id}", clear_on_submit=True):
                        edited_management = st.data_editor(
                            editor_df,
                            key=f"object_management_editor_{object_id}",
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "ID": st.column_config.NumberColumn("№", disabled=True),
                                "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                                "1.1 Всего": st.column_config.NumberColumn("Заказ-Всего", disabled=True, format="%d"),
                                "1.2 Коррекция": st.column_config.NumberColumn("Заказ-Коррекция", min_value=-100000, step=1, format="%d"),
                                "2.1 Осталось изготовить": st.column_config.NumberColumn("Производство-Осталось изготовить", disabled=True, format="%d"),
                                "2.2 Изготовлено": st.column_config.NumberColumn("Производство-Изготовлено", min_value=0, step=1, format="%d"),
                                "3.2 Прибыло": st.column_config.NumberColumn("Склад-Прибыло", disabled=True, format="%d"),
                                "3.3 Отгружено": st.column_config.NumberColumn("Склад-Отгружено", min_value=0, step=1, format="%d"),
                                "3.4 Осталось": st.column_config.NumberColumn("Склад-Осталось", disabled=True, format="%d"),
                                "4.1 В пути": st.column_config.NumberColumn("Транспорт-В пути", disabled=True, format="%d"),
                                "4.2 Доставлен": st.column_config.NumberColumn("Транспорт-Доставлен", min_value=0, step=1, format="%d"),
                                "5.1 Получено": st.column_config.NumberColumn("Объект-Получено", disabled=True, format="%d"),
                                "5.2 Установлено": st.column_config.NumberColumn("Объект-Установлено", min_value=0, step=1, format="%d"),
                                "5.4 Всего установлено": st.column_config.NumberColumn("Объект-Всего установлено", disabled=True, format="%d"),
                            },
                            disabled=[
                                "ID", "Изделие",
                                "1.1 Всего", "2.1 Осталось изготовить",
                                "3.2 Прибыло", "3.4 Осталось",
                                "4.1 В пути", "5.1 Получено", "5.4 Всего установлено"
                            ],
                        )
                        management_execute = st.form_submit_button(
                            "Выполнить",
                            use_container_width=True
                        )

                    management_print = editor_df[[
                        "ID", "Изделие", "1.1 Всего", "2.1 Осталось изготовить",
                        "3.2 Прибыло", "3.4 Осталось", "4.1 В пути",
                        "5.1 Получено", "5.4 Всего установлено"
                    ]].copy()
                    management_print.columns = [
                        "№", "Изделие", "Заказ-Всего", "Производство-Осталось изготовить",
                        "Склад-Прибыло", "Склад-Осталось", "Транспорт-В пути",
                        "Объект-Получено", "Объект-Всего установлено"
                    ]
                    render_print_html(
                        f"Состояние объекта — {str(object_row.get('object_name', '') or '').strip()}",
                        management_print,
                        f"print_object_management_{object_id}"
                    )

                    if management_execute:
                        errors = []
                        pending = []

                        for idx, r in edited_management.iterrows():
                            tid = safe_int(r["ID"])
                            name = str(r["Изделие"] or "").strip()
                            base = management_df.iloc[idx]

                            old_state = {
                                "order": safe_int(base["1.1 Всего"]),
                                "new": safe_int(base["_qty_new"]),
                                "production": safe_int(base["_qty_production"]),
                                "ready": safe_int(base["_qty_ready"]),
                                "shipped": safe_int(base["_qty_shipped"]),
                                "arrived": safe_int(base["_qty_arrived"]),
                                "installing": safe_int(base["_qty_installing"]),
                                "installed": safe_int(base["_qty_installed"]),
                            }

                            correction = safe_int(r["1.2 Коррекция"])
                            manufactured_action = safe_int(r["2.2 Изготовлено"])
                            shipped_action = safe_int(r["3.3 Отгружено"])
                            delivered_action = safe_int(r["4.2 Доставлен"])
                            installed_action = safe_int(r["5.2 Установлено"])

                            result = calculate_object_management_change(
                                old_state,
                                correction,
                                manufactured_action,
                                shipped_action,
                                delivered_action,
                                installed_action,
                            )

                            if result["error"]:
                                errors.append(
                                    f"{name}: {result['error']}"
                                )
                                continue

                            state = result["state"]
                            commands = result["commands"]
                            newly_produced_from_new = result["newly_produced_from_new"]

                            changed = (
                                state != old_state or
                                correction != 0 or
                                manufactured_action != 0 or
                                shipped_action != 0 or
                                delivered_action != 0 or
                                installed_action != 0
                            )
                            if changed:
                                pending.append({
                                    "tid": tid,
                                    "name": name,
                                    "old": old_state,
                                    "new": state,
                                    "commands": commands,
                                    "newly_produced_from_new": newly_produced_from_new,
                                    "actions": {
                                        "correction": correction,
                                        "manufactured": manufactured_action,
                                        "shipped": shipped_action,
                                        "delivered": delivered_action,
                                        "installed": installed_action,
                                    },
                                })

                        if errors:
                            st.error("Операция не подготовлена:\n" + "\n".join(errors))
                        elif not pending:
                            st.info("Изменений для выполнения нет.")
                        else:
                            st.session_state["object_management_pending"] = {
                                "object_id": object_id,
                                "object_name": str(object_row["object_name"]),
                                "changes": pending,
                            }

                    pending = st.session_state.get("object_management_pending")
                    if pending and pending.get("object_id") == object_id:
                        st.warning("Подтвердить изменения по объекту?")
                        for change in pending["changes"]:
                            old = change["old"]
                            new = change["new"]
                            actions = change.get("actions", {})
                            st.write(f"**{change['name']}**")
                            if actions.get("correction"):
                                st.write(f"• Коррекция заказа: {actions['correction']:+d}")
                            if old["new"] != new["new"]:
                                st.write(f"• Осталось не изготовлено: {old['new']} → {new['new']}")
                            if old["production"] != new["production"]:
                                st.write(f"• В производстве: {old['production']} → {new['production']}")
                            if old["ready"] != new["ready"]:
                                st.write(f"• На складе: {old['ready']} → {new['ready']}")
                            if old["shipped"] != new["shipped"]:
                                st.write(f"• В пути: {old['shipped']} → {new['shipped']}")
                            if old["arrived"] != new["arrived"]:
                                st.write(f"• Получено на объекте: {old['arrived']} → {new['arrived']}")
                            if old["installed"] != new["installed"]:
                                st.write(f"• Всего установлено: {old['installed']} → {new['installed']}")

                        c1, c2 = st.columns(2)
                        with c1:
                            confirm = st.button(
                                "Подтвердить",
                                key=f"management_confirm_{object_id}",
                                use_container_width=True,
                            )
                        with c2:
                            cancel = st.button(
                                "Отменить",
                                key=f"management_cancel_{object_id}",
                                use_container_width=True,
                            )

                        if cancel:
                            st.session_state.pop("object_management_pending", None)
                            st.session_state.pop(f"object_management_editor_{object_id}", None)
                            st.rerun()

                        if confirm:
                            statements = []

                            # Reconcile material postings against the FINAL production
                            # stage of every changed item. This is intentionally not based
                            # on "newly produced" quantity only: legacy items that were
                            # already in transport/installation before the warehouse
                            # workflow was added must also receive their missing postings.
                            production_items = []
                            for ch in pending["changes"]:
                                new_state = ch.get("new", {})
                                planned_produced_qty = (
                                    safe_float(new_state.get("production", 0))
                                    + safe_float(new_state.get("ready", 0))
                                    + safe_float(new_state.get("shipped", 0))
                                    + safe_float(new_state.get("arrived", 0))
                                    + safe_float(new_state.get("installing", 0))
                                    + safe_float(new_state.get("installed", 0))
                                )
                                if planned_produced_qty <= 0:
                                    continue

                                item_df = run_query(
                                    """
                                    SELECT id
                                    FROM reklet.object_items
                                    WHERE object_id=%s
                                      AND (product_template_id=%s OR template_id=%s)
                                    ORDER BY id
                                    LIMIT 1
                                    """,
                                    (object_id, safe_int(ch["tid"]), safe_int(ch["tid"])),
                                    fetch=True,
                                )
                                if item_df.empty:
                                    raise ValueError(
                                        f"Не найдена позиция изделия в объекте: {ch.get('name','')}"
                                    )
                                production_items.append(
                                    (safe_int(item_df.iloc[0]["id"]), planned_produced_qty)
                                )

                            # The management screen is intentionally a shortcut: when a
                            # command starts from a later stage, all missing warehouse
                            # postings are generated automatically. The reconciliation is
                            # idempotent, so the same item can be corrected again without
                            # duplicating material purchases, transfers, or consumption.
                            try:
                                statements.extend(
                                    build_auto_material_reconciliation_statements(
                                        object_id, production_items
                                    )
                                )
                            except Exception as e:
                                st.error(f"Не удалось подготовить автоматические проводки склада: {e}")
                                st.stop()

                            for change in pending["changes"]:
                                tid = change["tid"]
                                new = change["new"]

                                # Create the object-item row if necessary.
                                statements.append((
                                    """
                                    INSERT INTO reklet.object_items
                                        (object_id, product_template_id, template_id,
                                         quantity_needed, item_name, quantity, qty_new, status)
                                    SELECT %s,%s,%s,%s,%s,%s,%s,'New'
                                    WHERE NOT EXISTS (
                                        SELECT 1
                                        FROM reklet.object_items
                                        WHERE object_id=%s
                                          AND (product_template_id=%s OR template_id=%s)
                                    )
                                    """,
                                    (
                                        object_id, tid, tid,
                                        new["order"], change["name"], new["order"], new["new"],
                                        object_id, tid, tid
                                    )
                                ))
                                statements.append((
                                    """
                                    INSERT INTO reklet.object_item_material_costs
                                        (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                                    SELECT oi.id,
                                           ptm.material_id,
                                           COALESCE(ptm.quantity_per_unit,0),
                                           COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                                           COALESCE(m.cost_per_unit,0)
                                    FROM reklet.object_items oi
                                    JOIN reklet.product_template_materials ptm
                                      ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                                    JOIN reklet.materials m ON m.id=ptm.material_id
                                    WHERE oi.object_id=%s
                                      AND (oi.product_template_id=%s OR oi.template_id=%s)
                                    ON CONFLICT (object_item_id,material_id) DO NOTHING
                                    """,
                                    (object_id, tid, tid)
                                ))

                                production_completed = (
                                    new["ready"] + new["shipped"] + new["arrived"] +
                                    new["installing"] + new["installed"]
                                )
                                production_status = (
                                    "completed" if new["new"] == 0 and new["production"] == 0 and new["order"] > 0
                                    else "in_progress" if new["production"] > 0 or production_completed > 0
                                    else "not_started"
                                )
                                installation_status = (
                                    "completed" if new["installed"] >= new["order"] and new["order"] > 0
                                    else "in_progress" if new["installed"] > 0
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
                                    WHERE object_id=%s
                                      AND (product_template_id=%s OR template_id=%s)
                                    """,
                                    (
                                        new["order"], new["order"], new["new"], new["production"],
                                        new["ready"], new["shipped"], new["arrived"],
                                        new["installing"], new["installed"],
                                        production_status,
                                        new["order"], production_completed, new["order"],
                                        installation_status,
                                        new["order"], new["installed"], new["order"],
                                        object_id, tid, tid
                                    )
                                ))

                                # Write every transition generated by the command.
                                for command in change["commands"]:
                                    kind, qty = command

                                    if kind == "production":
                                        statements.extend([
                                            (
                                                """
                                                INSERT INTO reklet.production_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'completed',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods
                                                    (object_item_id,object_id,quantity,status)
                                                SELECT id,object_id,%s,'ready'
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ready',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "ship":
                                        statements.extend([
                                            (
                                                """
                                                WITH ready_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='ready'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM ready_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity,
                                                    status=CASE WHEN updates.new_quantity=0 THEN 'shipped' ELSE 'ready' END
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ship',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.transport_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ship',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "arrive":
                                        statements.extend([
                                            (
                                                """
                                                WITH shipped_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='shipped'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM shipped_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity,
                                                    status=CASE WHEN updates.new_quantity=0 THEN 'arrived' ELSE 'shipped' END
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'arrive',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.transport_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'arrive',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "install":
                                        statements.extend([
                                            (
                                                """
                                                WITH arrived_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='arrived'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM arrived_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.installation_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'complete',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                            try:
                                run_transaction(statements)
                                # Green fields are one-time commands. Reset the editor
                                # state after a successful transaction so the action
                                # values return to zero after rerun.
                                st.session_state.pop(f"object_management_editor_{object_id}", None)
                                st.session_state.pop("object_management_pending", None)
                                st.success("Изменения выполнены. Движения записаны по всем необходимым этапам.")
                                st.rerun()
                            except Exception as e:
                                st.error("Операция не выполнена. Транзакция отменена.")
                                st.code(str(e))

                # --------------------------------------------------------
                # СТАТУСЫ ОБЪЕКТОВ
                # --------------------------------------------------------
                st.markdown("---")
                st.subheader("Статус объектов")
                status_filter = st.selectbox(
                    "Отбор по статусу",
                    ["Все объекты", "Согласован", "Запущен", "Завершен"],
                    key="object_management_status_filter"
                )

                status_df = run_query(
                    """
                    WITH item_state AS (
                        SELECT
                            oi.object_id,
                            COUNT(*) AS item_count,
                            COALESCE(SUM(COALESCE(oi.quantity_needed, 0)), 0) AS ordered_qty,
                            COALESCE(SUM(COALESCE(oi.qty_production, 0)), 0) AS production_qty,
                            COALESCE(SUM(COALESCE(oi.qty_ready, 0)), 0) AS ready_qty,
                            COALESCE(SUM(COALESCE(oi.qty_shipped, 0)), 0) AS shipped_qty,
                            COALESCE(SUM(COALESCE(oi.qty_arrived, 0)), 0) AS arrived_qty,
                            COALESCE(SUM(COALESCE(oi.qty_installing, 0)), 0) AS installing_qty,
                            COALESCE(SUM(COALESCE(oi.qty_installed, 0)), 0) AS installed_qty
                        FROM reklet.object_items oi
                        GROUP BY oi.object_id
                    ),
                    production_history AS (
                        SELECT DISTINCT object_id
                        FROM reklet.production_transactions
                        WHERE object_id IS NOT NULL
                    )
                    SELECT
                        o.id,
                        COALESCE(c.name, '') AS client_name,
                        o.object_name,
                        CASE
                            WHEN s.item_count IS NULL OR s.item_count = 0 THEN NULL
                            WHEN s.ordered_qty > 0 AND s.installed_qty >= s.ordered_qty THEN 'Завершен'
                            WHEN p.object_id IS NOT NULL
                                 OR s.production_qty > 0
                                 OR s.ready_qty > 0
                                 OR s.shipped_qty > 0
                                 OR s.arrived_qty > 0
                                 OR s.installing_qty > 0
                                 OR s.installed_qty > 0
                                THEN 'Запущен'
                            ELSE 'Согласован'
                        END AS status
                    FROM reklet.objects o
                    LEFT JOIN reklet.clients c ON c.id = o.client_id
                    LEFT JOIN item_state s ON s.object_id = o.id
                    LEFT JOIN production_history p ON p.object_id = o.id
                    WHERE s.item_count IS NOT NULL AND s.item_count > 0
                    ORDER BY o.object_name
                    """,
                    fetch=True
                )

                if status_df.empty:
                    st.info("Нет объектов с добавленными изделиями.")
                else:
                    if status_filter != "Все объекты":
                        status_df = status_df[status_df["status"] == status_filter].copy()

                    status_view = status_df[["client_name", "object_name", "status"]].copy()
                    status_view.columns = ["Заказчик", "Объект", "Статус"]

                    if status_view.empty:
                        st.info("Объектов с выбранным статусом нет.")
                    else:
                        st.dataframe(
                            status_view,
                            width="stretch",
                            hide_index=True
                        )
                        render_print_html(
                            "Статус объектов",
                            status_view,
                            "print_object_statuses",
                            subtitle=f"Отбор: {status_filter}"
                        )

    # ------------------------------------------------------------


def _render_object_content(object_id, object_row):
        st.subheader(f"Состав объекта: {str(object_row.get('object_name', '') or '').strip()}")
        items = get_object_items(object_id)
        if items.empty:
            st.info("Для этого объекта ещё не созданы изделия.")
        else:
            # Позиция без заказа и без каких-либо операций больше не
            # является актуальной частью состава объекта. Из БД её не
            # удаляем — она должна сохраняться в истории управления.
            quantity_columns = [
                "quantity_needed",
                "qty_new",
                "qty_production",
                "qty_ready",
                "qty_shipped",
                "qty_arrived",
                "qty_installing",
                "qty_installed",
            ]
            numeric = items[quantity_columns].apply(
                pd.to_numeric, errors="coerce"
            ).fillna(0)
            active_mask = numeric.ne(0).any(axis=1)
            display_items = items.loc[active_mask].copy()

            if display_items.empty:
                st.info("В составе объекта нет актуальных изделий.")
            else:
                display = display_items[["item_name", "quantity"]].copy().reset_index(drop=True)
                display.insert(0, "Nп/п", range(1, len(display) + 1))
                display.columns = ["Nп/п", "Изделие", "Количество"]
                st.dataframe(display, width="stretch", hide_index=True)
                render_print_html(
                    f"Состав объекта — {str(object_row.get('object_name', '') or '').strip()}",
                    display,
                    f"print_object_composition_{object_id}"
                )


def _render_object_materials(object_id, object_row):
        items = get_object_items(object_id)
        if items.empty:
            st.info("К этому объекту не привязаны изделия.")
        else:
            requirements = run_query(
                """
                SELECT
                    oi.id AS object_item_id,
                    oi.item_name,
                    oi.quantity AS product_quantity,
                    ptm.material_id,
                    m.name AS material_name,
                    u.name AS unit_name,
                    COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit) AS quantity_per_unit,
                    COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1) AS waste_coefficient,
                    COALESCE(oimc.unit_cost, m.cost_per_unit, 0) AS cost_per_unit,
                    m.stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.product_templates pt
                  ON pt.id = COALESCE(oi.product_template_id, oi.template_id)
                JOIN reklet.product_template_materials ptm
                  ON ptm.product_template_id = pt.id
                JOIN reklet.materials m ON m.id = ptm.material_id
                LEFT JOIN reklet.object_item_material_costs oimc
                  ON oimc.object_item_id=oi.id
                 AND oimc.material_id=ptm.material_id
                LEFT JOIN reklet.units u ON u.id = m.unit_id
                WHERE oi.object_id = %s
                ORDER BY oi.item_name, m.name
                """,
                (object_id,), fetch=True
            )
            if requirements.empty:
                st.warning("Для изделий этого объекта ещё не создана спецификация материалов.")
            else:
                requirements["required_quantity"] = (
                    requirements["product_quantity"]
                    * requirements["quantity_per_unit"]
                    * requirements["waste_coefficient"]
                )
                requirements["material_cost"] = (
                    requirements["required_quantity"]
                    * requirements["cost_per_unit"]
                )
                requirement_view = requirements[[
                    "item_name", "product_quantity", "material_name", "unit_name",
                    "quantity_per_unit", "waste_coefficient", "required_quantity",
                    "cost_per_unit", "material_cost"
                ]].copy()
                requirement_view.columns = [
                    "Изделие", "Количество", "Материал", "Единица",
                    "Количество на изделие", "Коэффициент отходов", "Требуется",
                    "Цена", "Сумма"
                ]
                st.dataframe(requirement_view, width="stretch", hide_index=True)
                render_print_html(
                    f"Потребность в материалах — {str(object_row.get('object_name', '') or '').strip()}",
                    requirement_view,
                    f"print_object_material_requirement_{object_id}"
                )


def _render_create_object():
        clients = get_clients()
        client_map = {str(row["name"]): int(row["id"]) for _, row in clients.iterrows()} if not clients.empty else {}
        st.subheader("Создать объект")
        with st.form("create_object"):
            client_name = st.selectbox("Заказчик", list(client_map.keys()) if client_map else [])
            object_name = st.text_input("Название объекта")
            address = st.text_input("Адрес")
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
            submit = st.form_submit_button("Создать объект")
            if submit:
                if not client_name or not object_name.strip():
                    st.warning("Необходимо указать заказчика и название объекта.")
                else:
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


def render_objects():
    st.header("Объекты")
    section = render_button_nav(
        ["Информация по объектам", "Управление объектами"],
        "objects_navigation", "objects_nav", columns_per_row=2,
    )
    st.markdown("---")
    if section == "Управление объектами":
        _render_object_management()
        render_page_instruction("objects_management")
        return

    df = get_objects().sort_values("id", ascending=False).copy()
    if df.empty:
        st.info("Объектов нет.")
        with st.expander("Создать новый объект", expanded=False):
            _render_create_object()
        render_page_instruction("objects")
        return

    customer_names = sorted(
        df["client_name"].fillna("").astype(str).str.strip()
        .loc[lambda x: x != ""].unique().tolist()
    )
    customer_options = ["Все Заказчики"] + customer_names
    c1, c2 = st.columns(2)
    with c1:
        selected_customer = st.selectbox("Отбор по Заказчику", customer_options, key="object_info_customer_filter")
    filtered = df.copy()
    if selected_customer != "Все Заказчики":
        filtered = filtered[filtered["client_name"].fillna("").astype(str).str.strip().eq(selected_customer)].copy()

    object_rows = filtered[["id", "object_name"]].copy()
    object_rows["object_name"] = object_rows["object_name"].fillna("").astype(str).str.strip()
    object_options = ["Все Объекты"] + [f"{int(r['id'])} — {r['object_name']}" for _, r in object_rows.iterrows()]
    with c2:
        selected_object_label = st.selectbox("Отбор по Объекту", object_options, key="object_info_object_filter")

    selected_object_id = None
    if selected_object_label != "Все Объекты":
        selected_object_id = int(selected_object_label.split(" — ", 1)[0])
        filtered = filtered[filtered["id"].eq(selected_object_id)].copy()

    st.subheader("Перечень объектов")
    if filtered.empty:
        st.info("Объектов по выбранному отбору нет.")
    else:
        display = filtered[["object_name", "client_name", "address"]].copy().reset_index(drop=True)
        display.insert(0, "№ п.п", range(1, len(display) + 1))
        display.columns = ["№ п.п", "Объект", "Заказчик", "Адрес объекта"]
        st.dataframe(display, width="stretch", hide_index=True)
        render_print_html("Перечень объектов", display, "print_object_list")

    if selected_object_id is None:
        with st.expander("Создать новый объект", expanded=False):
            _render_create_object()
    else:
        selected_row_df = df[df["id"].eq(selected_object_id)]
        if selected_row_df.empty:
            st.warning("Выбранный объект не найден.")
        else:
            selected_object_row = selected_row_df.iloc[0].copy()
            with st.expander("Данные Объекта и их коррекция", expanded=False):
                _render_object_data(selected_object_id)
            with st.expander("Изделия объекта", expanded=False):
                _render_object_content(selected_object_id, selected_object_row)
            with st.expander("Добавить изделия в объект", expanded=False):
                _render_add_items(selected_object_id, selected_object_row)
            with st.expander("Материалы Объекта", expanded=False):
                _render_object_materials(selected_object_id, selected_object_row)
            with st.expander("Создать новый объект", expanded=False):
                _render_create_object()
    render_page_instruction("objects")

