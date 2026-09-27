import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.printing import render_print_html
from repositories.clients import get_clients


def render_clients():

    st.header("Клиенты")

    clients_all = get_clients().copy()

    # ========================================================
    # ОТБОР ПО КЛИЕНТУ
    # ========================================================
    client_names = []
    if not clients_all.empty and "name" in clients_all.columns:
        client_names = (
            clients_all["name"]
            .fillna("")
            .astype(str)
            .str.strip()
            .loc[lambda x: x != ""]
            .sort_values()
            .unique()
            .tolist()
        )

    client_options = ["Все клиенты"] + client_names
    selected_client = st.selectbox(
        "Отбор по клиенту",
        client_options,
        key="client_filter_list"
    )

    clients = clients_all.copy()
    selected_client_id = None

    if selected_client != "Все клиенты":
        clients = clients[
            clients["name"]
            .fillna("")
            .astype(str)
            .str.strip()
            .eq(selected_client)
        ].copy()

        if not clients.empty:
            selected_client_id = int(clients.iloc[0]["id"])

    # ========================================================
    # ПЕРЕЧЕНЬ КЛИЕНТОВ
    # ========================================================
    st.subheader("Перечень клиентов")

    if clients.empty:
        st.info("Клиентов нет.")
    else:
        display = clients[
            ["id", "name", "phone", "address", "email", "website", "notes"]
        ].copy()
        display.columns = [
            "ID",
            "Наименование",
            "Телефон",
            "Адрес",
            "Email",
            "Веб-сайт",
            "Примечание",
        ]
        st.dataframe(display, width="stretch", hide_index=True)
        render_print_html("Перечень клиентов", display, "print_clients_list")

    # ========================================================
    # КОРРЕКТИРОВКА КЛИЕНТА
    # Строка всегда видна. Без конкретного клиента она неактивна;
    # после выбора клиента раскрывается рабочее окно.
    # ========================================================
    if selected_client_id is None or clients.empty:
        st.button(
            "Корректировка клиента",
            key="client_correction_placeholder",
            disabled=True,
            use_container_width=True,
        )
    else:
        row = clients[clients["id"] == selected_client_id].iloc[0]
        with st.expander("Корректировка клиента", expanded=False):
            pending_key = f"client_edit_pending_{selected_client_id}"

            with st.form(
                f"edit_client_form_{selected_client_id}",
                clear_on_submit=False,
            ):
                name = st.text_input("Наименование", value=str(row["name"] or ""))
                phone = st.text_input("Телефон", value=str(row["phone"] or ""))
                address = st.text_input("Адрес", value=str(row["address"] or ""))
                email = st.text_input("Email", value=str(row["email"] or ""))
                website = st.text_input("Веб-сайт", value=str(row["website"] or ""))
                notes = st.text_area("Примечание", value=str(row["notes"] or ""))
                execute_client_changes = st.form_submit_button(
                    "Выполнить", use_container_width=True
                )

            if execute_client_changes:
                new_values = {
                    "name": name.strip(),
                    "phone": phone.strip() or None,
                    "address": address.strip() or None,
                    "email": email.strip() or None,
                    "website": website.strip() or None,
                    "notes": notes.strip() or None,
                }

                if not new_values["name"]:
                    st.error("Наименование клиента не может быть пустым.")
                else:
                    comparisons = [
                        ("Наименование", str(row["name"] or "").strip(), new_values["name"]),
                        ("Телефон", str(row["phone"] or "").strip(), new_values["phone"] or ""),
                        ("Адрес", str(row["address"] or "").strip(), new_values["address"] or ""),
                        ("Email", str(row["email"] or "").strip(), new_values["email"] or ""),
                        ("Веб-сайт", str(row["website"] or "").strip(), new_values["website"] or ""),
                        ("Примечание", str(row["notes"] or "").strip(), new_values["notes"] or ""),
                    ]
                    changes=[]
                    for label, old_val, new_val in comparisons:
                        if str(old_val or "") != str(new_val or ""):
                            changes.append({
                                "Поле": label,
                                "Было": old_val if old_val else "—",
                                "Станет": new_val if new_val else "—",
                            })
                    if changes:
                        st.session_state[pending_key] = {
                            "client_id": selected_client_id,
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
                c1,c2=st.columns(2)
                with c1:
                    confirm_client_changes=st.button(
                        "Подтвердить", key=f"confirm_client_edit_{selected_client_id}",
                        type="primary", use_container_width=True
                    )
                with c2:
                    cancel_client_changes=st.button(
                        "Отмена", key=f"cancel_client_edit_{selected_client_id}",
                        use_container_width=True
                    )
                if confirm_client_changes:
                    values=pending["values"]
                    try:
                        run_transaction([
                            (
                                """UPDATE reklet.clients
                                   SET name=%s, phone=%s, address=%s, email=%s,
                                       website=%s, notes=%s, contact_info=%s
                                 WHERE id=%s""",
                                (values["name"],values["phone"],values["address"],values["email"],
                                 values["website"],values["notes"],values["phone"],selected_client_id)
                            )
                        ])
                        st.session_state.pop(pending_key,None)
                        st.success("Данные клиента изменены.")
                        st.rerun()
                    except Exception as e:
                        st.error("Изменения не сохранены. Транзакция отменена.")
                        st.code(str(e))
                if cancel_client_changes:
                    st.session_state.pop(pending_key,None)
                    st.rerun()

            with st.expander("Безопасное удаление клиента"):
                st.warning(
                    "Удаление необратимо. Клиента нельзя удалить, "
                    "если он используется хотя бы одним объектом."
                )
                delete_confirm=st.checkbox(
                    "Я подтверждаю удаление выбранного клиента.",
                    key=f"confirm_delete_client_{selected_client_id}",
                )
                if st.button(
                    "Удалить клиента", key=f"delete_client_{selected_client_id}",
                    disabled=not delete_confirm, use_container_width=True
                ):
                    used=run_query(
                        "SELECT COUNT(*) AS cnt FROM reklet.objects WHERE client_id=%s",
                        (selected_client_id,),fetch=True
                    )
                    if int(used.iloc[0]["cnt"])>0:
                        st.error("Удаление невозможно: этот клиент используется объектами.")
                    else:
                        run_query("DELETE FROM reklet.clients WHERE id=%s",(selected_client_id,))
                        st.success("Клиент удалён.")
                        st.rerun()

    # ========================================================
    # ДОБАВИТЬ КЛИЕНТА
    # Независимо от текущего отбора сверху.
    # ========================================================
    st.markdown("---")
    with st.expander("Добавить клиента", expanded=False):
        with st.form("add_client_form", clear_on_submit=False):
            name = st.text_input("Наименование")
            phone = st.text_input("Телефон")
            address = st.text_input("Адрес")
            email = st.text_input("Email")
            website = st.text_input("Веб-сайт")
            notes = st.text_area("Примечание")
            submit = st.form_submit_button(
                "Добавить клиента",
                use_container_width=True,
            )

        if submit:
            if not name.strip():
                st.warning("Необходимо указать наименование клиента.")
            else:
                run_query(
                    """
                    INSERT INTO reklet.clients
                        (name, phone, address, email, website, notes, contact_info)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        name.strip(),
                        phone.strip() or None,
                        address.strip() or None,
                        email.strip() or None,
                        website.strip() or None,
                        notes.strip() or None,
                        phone.strip() or None,
                    ),
                )
                st.success("Клиент добавлен.")
                st.rerun()
