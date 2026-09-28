import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_int, safe_float
from core.printing import render_print_html
from core.instructions import render_page_instruction
from repositories.clients import get_clients
from repositories.materials import (
    get_materials_with_categories,
    get_material_categories,
)
from repositories.products import (
    get_templates,
    get_product_categories,
)


def _render_add_product():

    st.subheader("Добавить изделие")
    clients = get_clients()
    client_map = {f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in clients.iterrows()} if not clients.empty else {}
    try:
        categories = get_product_categories()
    except Exception as e:
        categories = pd.DataFrame(columns=["id","name"])
        st.error("Не удалось открыть категории изделий.")
        st.code(str(e))
    category_options = categories["name"].astype(str).tolist() if not categories.empty else []
    with st.form("create_product_form"):
        name = st.text_input("Название изделия")
        type_value = st.selectbox("Тип",["recurrent","custom"])
        customer_label = st.selectbox("Заказчик",list(client_map.keys())) if client_map else None
        category = st.selectbox("Категория",category_options) if category_options else None
        submit = st.form_submit_button("Создать изделие")
        if submit:
            if not name.strip():
                st.warning("Необходимо указать название изделия.")
            elif not client_map:
                st.warning("Сначала создайте заказчика в разделе «Клиенты».")
            elif not category:
                st.warning("Сначала создайте категорию изделия.")
            else:
                customer_name = clients[clients["id"]==client_map[customer_label]].iloc[0]["name"]
                run_query(
                    """INSERT INTO reklet.product_templates (name,type,client_name,category)
                       VALUES (%s,%s,%s,%s)""",
                    (name.strip(),type_value,customer_name,category)
                )
                st.success("Изделие создано.")
                st.rerun()



def _render_product_categories():

    st.subheader("Категории изделий")
    try:
        categories = get_product_categories()
    except Exception as e:
        categories = pd.DataFrame(columns=["id","name"])
        st.error("Не удалось открыть категории изделий.")
        st.code(str(e))

    # ----------------------------------------------------
    # ПЕРЕЧЕНЬ КАТЕГОРИЙ
    # ----------------------------------------------------
    st.markdown("### Перечень категорий")
    if categories.empty:
        st.info("Категорий изделий нет.")
    else:
        category_list = categories[["id", "name"]].copy()
        category_list.insert(0, "Nп/п", range(1, len(category_list) + 1))
        category_list.columns = ["Nп/п", "ID", "Категория"]
        st.dataframe(category_list, width="stretch", hide_index=True)
        render_print_html("Перечень категорий изделий", category_list, "print_product_categories")

    # ----------------------------------------------------
    # КОРРЕКТИРОВКА КАТЕГОРИИ
    # ----------------------------------------------------
    st.markdown("### Корректировка категории")
    if categories.empty:
        st.info("Нет категорий для корректировки.")
    else:
        category_map = {
            f"{int(row['id'])} — {str(row['name']).strip()}": int(row['id'])
            for _, row in categories.iterrows()
        }
        selected_label = st.selectbox(
            "Категория",
            ["— Выберите категорию —"] + list(category_map.keys()),
            index=0,
            key="product_category_edit_filter"
        )

        if selected_label != "— Выберите категорию —":
            category_id = category_map[selected_label]
            old_name = str(
                categories[categories["id"] == category_id].iloc[0]["name"]
            ).strip()
            pending_key = f"product_category_edit_pending_{category_id}"

            with st.form(f"product_category_edit_form_{category_id}", clear_on_submit=False):
                new_name = st.text_input("Новое название", value=old_name)
                execute_category_changes = st.form_submit_button(
                    "Выполнить", use_container_width=True
                )

            if execute_category_changes:
                new_name_clean = new_name.strip()
                if not new_name_clean:
                    st.error("Название категории не может быть пустым.")
                elif new_name_clean == old_name:
                    st.info("Изменений нет.")
                else:
                    st.session_state[pending_key] = {
                        "category_id": category_id,
                        "old_name": old_name,
                        "new_name": new_name_clean,
                    }

            pending = st.session_state.get(pending_key)
            if pending:
                st.markdown("#### Подтверждение изменений")
                confirmation = pd.DataFrame([{
                    "Поле": "Категория",
                    "Было": pending["old_name"],
                    "Станет": pending["new_name"],
                }])
                st.dataframe(confirmation, width="stretch", hide_index=True)
                c1, c2 = st.columns(2)
                with c1:
                    confirm_category_changes = st.button(
                        "Подтвердить",
                        key=f"confirm_product_category_edit_{category_id}",
                        type="primary",
                        use_container_width=True,
                    )
                with c2:
                    cancel_category_changes = st.button(
                        "Отмена",
                        key=f"cancel_product_category_edit_{category_id}",
                        use_container_width=True,
                    )

                if cancel_category_changes:
                    st.session_state.pop(pending_key, None)
                    st.rerun()

                if confirm_category_changes:
                    try:
                        run_transaction([
                            (
                                "UPDATE reklet.product_categories SET name=%s WHERE id=%s",
                                (pending["new_name"], pending["category_id"])
                            ),
                            (
                                "UPDATE reklet.product_templates SET category=%s WHERE category=%s",
                                (pending["new_name"], pending["old_name"])
                            )
                        ])
                        st.session_state.pop(pending_key, None)
                        st.success("Категория изменена.")
                        st.rerun()
                    except Exception as e:
                        st.error("Не удалось изменить категорию.")
                        st.code(str(e))

            # ------------------------------------------------
            # БЕЗОПАСНОЕ УДАЛЕНИЕ
            # ------------------------------------------------
            st.markdown("### Безопасное удаление категории")
            with st.expander("Безопасное удаление категории", expanded=False):
                st.warning(
                    "Удаление категории необратимо. Категория, используемая изделиями, "
                    "не может быть удалена."
                )
                confirm_delete_category = st.checkbox(
                    "Я подтверждаю удаление выбранной категории.",
                    key=f"confirm_delete_product_category_{category_id}"
                )
                if st.button(
                    "Удалить категорию",
                    key=f"delete_product_category_{category_id}",
                    disabled=not confirm_delete_category,
                ):
                    used = run_query(
                        "SELECT COUNT(*) AS cnt FROM reklet.product_templates WHERE category=%s",
                        (old_name,), fetch=True
                    )
                    if int(used.iloc[0]["cnt"]) > 0:
                        st.error("Удаление невозможно: категория используется изделиями.")
                    else:
                        run_query(
                            "DELETE FROM reklet.product_categories WHERE id=%s",
                            (category_id,)
                        )
                        st.success("Категория удалена.")
                        st.rerun()



def _render_product_correction(templates):

    st.subheader("Корректировка изделия")
    if templates.empty:
        st.info("Нет изделий для корректировки по текущему отбору.")
        return

    pmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in templates.iterrows()}
    label=st.selectbox("Изделие",list(pmap.keys()),key="edit_product_select")
    pid=pmap[label]
    row=templates[templates["id"]==pid].iloc[0]

    try:
        categories=get_product_categories()
        category_options=categories["name"].astype(str).tolist()
    except Exception:
        category_options=[]

    current_category=str(row["category"] or "")
    if current_category and current_category not in category_options:
        category_options=[current_category]+category_options
    current_customer=str(row["client_name"] or "")

    with st.form("edit_product_form",clear_on_submit=False):
        name=st.text_input("Название изделия",value=str(row["name"] or ""))
        type_value=st.selectbox(
            "Тип",["recurrent","custom"],
            index=0 if row["type"]=="recurrent" else 1
        )
        # Заказчик определяется фильтром в «Перечень изделий» и здесь
        # повторно не выбирается. Показываем только текущего заказчика.
        st.text_input("Заказчик",value=current_customer,disabled=True)
        category=(
            st.selectbox(
                "Категория",category_options,
                index=category_options.index(current_category)
                if current_category in category_options else 0
            )
            if category_options else None
        )
        execute=st.form_submit_button("Выполнить",use_container_width=True)

    if execute:
        if not name.strip():
            st.warning("Название изделия не может быть пустым.")
        else:
            run_query(
                """UPDATE reklet.product_templates
                   SET name=%s,type=%s,category=%s
                 WHERE id=%s""",
                (name.strip(),type_value,category or None,pid)
            )
            st.success("Изделие изменено.")
            st.rerun()

    with st.expander("Удаление изделия",expanded=False):
        st.warning("Безопасное удаление: изделие, используемое в объекте, не будет удалено.")
        confirm=st.checkbox(
            "Я подтверждаю удаление выбранного изделия.",
            key=f"confirm_delete_product_{pid}"
        )
        if st.button(
            "Удалить изделие",key=f"delete_product_{pid}",disabled=not confirm
        ):
            used=run_query(
                "SELECT COUNT(*) AS cnt FROM reklet.object_items WHERE product_template_id=%s OR template_id=%s",
                (pid,pid),fetch=True
            )
            if int(used.iloc[0]["cnt"])>0:
                st.error("Удаление невозможно: изделие используется в объекте.")
            else:
                run_transaction([
                    ("DELETE FROM reklet.product_template_materials WHERE product_template_id=%s",(pid,)),
                    ("DELETE FROM reklet.product_templates WHERE id=%s",(pid,))
                ])
                st.success("Изделие удалено.")
                st.rerun()


def _render_product_specification(templates):

    st.subheader("Спецификация изделия")
    if templates.empty:
        st.info("Нет изделий.")
    else:
        pmap={f"{int(r['id'])} — {r['name']} — {r['client_name'] or 'Без заказчика'}":int(r['id']) for _,r in templates.iterrows()}
        selected=st.selectbox("Изделие",list(pmap.keys()),key="product_spec_select")
        pid=pmap[selected]
        specification=run_query(
            """SELECT ptm.id,ptm.material_id,m.name AS material_name,u.name AS unit_name,
                      mc.name AS category_name,ptm.quantity_per_unit,ptm.waste_coefficient
               FROM reklet.product_template_materials ptm
               JOIN reklet.materials m ON m.id=ptm.material_id
               LEFT JOIN reklet.material_categories mc ON mc.id=m.category_id
               LEFT JOIN reklet.units u ON u.id=m.unit_id
               WHERE ptm.product_template_id=%s ORDER BY m.name""",
            (pid,),fetch=True
        )
        if specification.empty:
            st.info("В спецификации этого изделия нет материалов.")
        else:
            view=specification[["id","material_name","category_name","unit_name","quantity_per_unit","waste_coefficient"]].copy()
            view.columns=["ID","Материал","Категория","Единица","Количество на изделие","Коэффициент отходов"]
            st.dataframe(view,width="stretch",hide_index=True)
            render_print_html(
                f"Спецификация изделия — {str(templates[templates['id']==pid].iloc[0]['name'])}",
                view,
                f"print_product_spec_{pid}"
            )

        st.markdown("---")
        st.subheader("Добавить материал в изделие")
        materials=get_materials_with_categories()
        material_categories=get_material_categories()
        category_options=["Все категории","Без категории"] + (
            material_categories["name"].astype(str).tolist() if not material_categories.empty else []
        )
        selected_category=st.selectbox("Отбор по категории материала",category_options,key=f"spec_material_category_{pid}")
        filtered=materials.copy()
        if selected_category=="Без категории":
            filtered=filtered[filtered["category_id"].isna()].copy()
        elif selected_category!="Все категории":
            filtered=filtered[filtered["category_name"].fillna("").astype(str).eq(selected_category)].copy()
        if filtered.empty:
            st.info("Материалов по выбранной категории нет.")
        else:
            spec_add=filtered[["id","name","category_name","unit_name"]].copy()
            spec_add.insert(0,"Выбрать",False)
            spec_add["Количество на изделие"]=0.0
            spec_add["Коэффициент отходов"]=1.20
            spec_add.columns=["Выбрать","ID","Материал","Категория","Единица","Количество на изделие","Коэффициент отходов"]
            with st.form(f"product_spec_material_form_{pid}",clear_on_submit=False):
                edited=st.data_editor(
                    spec_add,key=f"product_spec_add_editor_{pid}_{selected_category}",
                    width="stretch",hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "ID":st.column_config.NumberColumn("ID",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Категория":st.column_config.TextColumn("Категория",disabled=True),
                        "Единица":st.column_config.TextColumn("Единица",disabled=True),
                        "Количество на изделие":st.column_config.NumberColumn("Количество на изделие",min_value=0.0,step=0.001,format="%.4f"),
                        "Коэффициент отходов":st.column_config.NumberColumn("Коэффициент отходов",min_value=0.0,step=0.01,format="%.2f")
                    },
                    disabled=["ID","Материал","Категория","Единица"]
                )
                execute=st.form_submit_button("Добавить выбранные материалы",use_container_width=True)
            if execute:
                selected_rows=edited[
                    edited["Выбрать"].fillna(False) &
                    (edited["Количество на изделие"].fillna(0).astype(float)>0)
                ]
                if selected_rows.empty:
                    st.warning("Выберите материалы и укажите количество.")
                else:
                    statements=[]
                    for _,r in selected_rows.iterrows():
                        mid=safe_int(r["ID"]); qty=safe_float(r["Количество на изделие"]); waste=safe_float(r["Коэффициент отходов"],1.20)
                        statements.extend([
                            ("UPDATE reklet.product_template_materials SET quantity_per_unit=%s,waste_coefficient=%s WHERE product_template_id=%s AND material_id=%s",(qty,waste,pid,mid)),
                            ("""INSERT INTO reklet.product_template_materials(product_template_id,material_id,quantity_per_unit,waste_coefficient)
                               SELECT %s,%s,%s,%s WHERE NOT EXISTS
                               (SELECT 1 FROM reklet.product_template_materials WHERE product_template_id=%s AND material_id=%s)""",
                             (pid,mid,qty,waste,pid,mid))
                        ])
                    run_transaction(statements)
                    st.success(f"Сохранено материалов: {len(selected_rows)}.")
                    st.rerun()


def _select_product_section(value):
    st.session_state["products_navigation"] = value


def _render_product_navigation():
    options = ["Перечень изделий", "Спецификация изделия"]
    if st.session_state.get("products_navigation") not in options:
        st.session_state["products_navigation"] = options[0]

    cols = st.columns(2, gap="small")
    for col, option in zip(cols, options):
        with col:
            st.button(
                option,
                key=f"products_nav_direct_{option}",
                use_container_width=True,
                on_click=_select_product_section,
                args=(option,),
            )

    return st.session_state["products_navigation"]


def render_products():
    st.header("Изделия")
    product_sub = _render_product_navigation()

    templates_all=get_templates()
    client_options=["Все заказчики"]+(
        sorted(templates_all["client_name"].dropna().astype(str).str.strip()
               .loc[lambda x:x!=""].unique().tolist())
        if not templates_all.empty else []
    )

    if product_sub=="Перечень изделий":
        selected_client=st.selectbox(
            "Отбор по заказчику-изделию",client_options,key="product_filter_list"
        )
        templates=templates_all.copy()
        if selected_client!="Все заказчики":
            templates=templates[
                templates["client_name"].fillna("").astype(str).str.strip().eq(selected_client)
            ].copy()

        st.subheader("Перечень изделий")
        if templates.empty:
            st.info("Изделий нет.")
        else:
            display=templates[["id","name","type","client_name","category"]].copy()
            display.columns=["ID","Изделие","Тип","Заказчик","Категория"]
            st.dataframe(display,width="stretch",hide_index=True)
            render_print_html("Перечень изделий",display,"print_product_list")

        with st.expander("Добавить изделие",expanded=False):
            _render_add_product()

        with st.expander("Корректировка изделия",expanded=False):
            _render_product_correction(templates)

        with st.expander("Категории изделий",expanded=False):
            _render_product_categories()

    elif product_sub=="Спецификация изделия":
        selected_client=st.selectbox(
            "Отбор по заказчику-изделию",client_options,key="product_filter_specification"
        )
        templates=templates_all.copy()
        if selected_client!="Все заказчики":
            templates=templates[
                templates["client_name"].fillna("").astype(str).str.strip().eq(selected_client)
            ].copy()
        _render_product_specification(templates)
    render_page_instruction("products")
