import pandas as pd
import streamlit as st

from core.db import run_query
from core.printing import render_print_html
from core.ui import render_button_nav
from core.instructions import render_page_instruction
from repositories.materials import (
    get_materials_with_categories,
    get_material_categories,
)
from repositories.suppliers import get_suppliers

def _render_supplier_correction(suppliers):

        st.subheader("Коррекция поставщиков")
        if suppliers.empty:
            st.info("Поставщиков нет.")
        else:
            supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers.iterrows()}
            selected_label=st.selectbox("Поставщик",list(supplier_map.keys()),key="supplier_edit_select")
            selected_id=supplier_map[selected_label]
            row=suppliers[suppliers["id"]==selected_id].iloc[0]
            with st.form("edit_supplier_form"):
                name=st.text_input("Название",value=str(row.get("name") or ""))
                types=["material_supplier","subcontractor","both"]
                current_type=str(row.get("type") or "material_supplier")
                supplier_type=st.selectbox("Тип поставщика",types,index=types.index(current_type) if current_type in types else 0)
                contact_person=st.text_input("Контактное лицо",value=str(row.get("contact_person") or ""))
                phone=st.text_input("Телефон",value=str(row.get("phone") or ""))
                email=st.text_input("Email",value=str(row.get("email") or ""))
                category=st.text_input("Категория",value=str(row.get("category") or ""))
                conditions=st.text_area("Условия",value=str(row.get("conditions") or ""))
                contact_info=st.text_area("Контактная информация",value=str(row.get("contact_info") or ""))
                if st.form_submit_button("Сохранить изменения"):
                    if not name.strip():
                        st.warning("Название поставщика не может быть пустым.")
                    else:
                        run_query(
                            """UPDATE reklet.suppliers SET name=%s,type=%s,contact_info=%s,
                                      contact_person=%s,phone=%s,email=%s,category=%s,conditions=%s
                               WHERE id=%s""",
                            (name.strip(),supplier_type,contact_info.strip() or None,
                             contact_person.strip() or None,phone.strip() or None,email.strip() or None,
                             category.strip() or None,conditions.strip() or None,selected_id)
                        )
                        st.success("Данные поставщика изменены.")
                        st.rerun()

            with st.expander("Удаление поставщика",expanded=False):
                st.warning(
                    "Безопасное удаление: поставщик не будет удалён, "
                    "если он используется материалами или движениями."
                )
                confirm=st.checkbox("Я подтверждаю удаление выбранного поставщика.",key="confirm_supplier_delete")
                if st.button("Удалить поставщика",key="delete_supplier_safe",disabled=not confirm):
                    used=run_query(
                        """SELECT
                             (SELECT COUNT(*) FROM reklet.material_suppliers WHERE supplier_id=%s) AS material_links,
                             (SELECT COUNT(*) FROM reklet.material_transactions WHERE supplier_id=%s) AS transactions,
                             (SELECT COUNT(*) FROM reklet.purchase_orders WHERE supplier_id=%s) AS purchase_orders""",
                        (selected_id,selected_id,selected_id),fetch=True
                    )
                    if int(used.iloc[0]["material_links"])>0 or int(used.iloc[0]["transactions"])>0 or int(used.iloc[0]["purchase_orders"])>0:
                        st.error("Удаление невозможно: поставщик используется в связанных данных.")
                    else:
                        run_query("DELETE FROM reklet.suppliers WHERE id=%s",(selected_id,))
                        st.success("Поставщик удалён.")
                        st.rerun()

    # ============================================================


def render_suppliers():
    st.header("Поставщики")

    supplier_sub = render_button_nav(
        [
            "Перечень поставщиков",
            "Создать поставщика",
            "Материалы поставщика",
            "Поиск поставщика"
        ],
        "suppliers_navigation",
        "suppliers_nav",
        columns_per_row=5
    )
    suppliers=get_suppliers()

    if supplier_sub=="Перечень поставщиков":
        st.subheader("Перечень поставщиков")
        if suppliers.empty:
            st.info("Поставщиков нет.")
        else:
            display_cols=[c for c in ["id","name","type","contact_person","phone","email","category","conditions"] if c in suppliers.columns]
            supplier_view = suppliers[display_cols].copy()
            st.dataframe(supplier_view,width="stretch",hide_index=True)
            render_print_html("Перечень поставщиков", supplier_view, "print_supplier_list")

            with st.expander("Коррекция поставщиков",expanded=False):
                _render_supplier_correction(suppliers)

    elif supplier_sub=="Создать поставщика":
        st.subheader("Создать поставщика")
        with st.form("create_supplier_new"):
            name=st.text_input("Название")
            supplier_type=st.selectbox("Тип поставщика",["material_supplier","subcontractor","both"])
            contact_person=st.text_input("Контактное лицо")
            phone=st.text_input("Телефон")
            email=st.text_input("Email")
            category=st.text_input("Категория")
            conditions=st.text_area("Условия")
            contact_info=st.text_area("Контактная информация")
            submit=st.form_submit_button("Создать поставщика")
            if submit:
                if not name.strip():
                    st.warning("Необходимо указать название.")
                else:
                    st.session_state["pending_supplier_create"]={
                        "name":name.strip(),"type":supplier_type,"contact_person":contact_person.strip(),
                        "phone":phone.strip(),"email":email.strip(),"category":category.strip(),
                        "conditions":conditions.strip(),"contact_info":contact_info.strip()
                    }
        pending_supplier=st.session_state.get("pending_supplier_create")
        if pending_supplier:
            st.warning("Подтвердите создание поставщика.")
            supplier_preview=pd.DataFrame([pending_supplier])
            supplier_preview.columns=["Название","Тип","Контактное лицо","Телефон","Email","Категория","Условия","Контактная информация"]
            st.dataframe(supplier_preview,width="stretch",hide_index=True)
            c1,c2=st.columns(2)
            with c1:
                ok=st.button("Подтвердить создание",key="confirm_supplier_create",use_container_width=True)
            with c2:
                no=st.button("Отменить",key="cancel_supplier_create",use_container_width=True)
            if no:
                st.session_state.pop("pending_supplier_create",None)
                st.rerun()
            if ok:
                run_query(
                    """INSERT INTO reklet.suppliers
                       (name,type,contact_info,contact_person,phone,email,category,conditions)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (pending_supplier["name"],pending_supplier["type"],pending_supplier["contact_info"] or None,
                     pending_supplier["contact_person"] or None,pending_supplier["phone"] or None,
                     pending_supplier["email"] or None,pending_supplier["category"] or None,pending_supplier["conditions"] or None)
                )
                st.session_state.pop("pending_supplier_create",None)
                st.success(f"Поставщик «{pending_supplier['name']}» создан.")
                st.rerun()

    elif supplier_sub=="Материалы поставщика":
        st.subheader("Материалы поставщика")

        st.markdown("---")

        if suppliers.empty:
            st.info("Сначала создайте поставщика.")
        else:
            supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers.iterrows()}
            selected_supplier_label=st.selectbox("Отбор по поставщику",list(supplier_map.keys()),key="supplier_material_filter")
            supplier_id=supplier_map[selected_supplier_label]

            linked=run_query(
                """SELECT ms.id,m.id AS material_id,m.name AS material,
                          mc.name AS category,ms.purchase_price,ms.supplier_code,
                          ms.conditions,ms.is_preferred
                   FROM reklet.material_suppliers ms
                   JOIN reklet.materials m ON m.id=ms.material_id
                   LEFT JOIN reklet.material_categories mc ON mc.id=m.category_id
                   WHERE ms.supplier_id=%s ORDER BY m.name""",
                (supplier_id,),fetch=True
            )
            if linked.empty:
                st.info("Для этого поставщика материалы пока не привязаны.")
            else:
                view=linked.copy()
                view.columns=["ID связи","ID материала","Материал","Категория","Цена","Код поставщика","Условия","Предпочтительный"]
                st.dataframe(view,width="stretch",hide_index=True)
                render_print_html(
                    f"Материалы поставщика — {selected_supplier_label}",
                    view,
                    f"print_supplier_materials_{supplier_id}"
                )

            all_materials=get_materials_with_categories()
            material_categories=get_material_categories()
            category_options=["Все категории","Без категории"] + (material_categories["name"].astype(str).tolist() if not material_categories.empty else [])
            add_category=st.selectbox("Категория материала для добавления",category_options,key="supplier_material_add_category")
            filtered_add_materials=all_materials.copy()
            if add_category=="Без категории":
                filtered_add_materials=filtered_add_materials[filtered_add_materials["category_id"].isna()].copy()
            elif add_category!="Все категории":
                filtered_add_materials=filtered_add_materials[filtered_add_materials["category_name"].fillna("").astype(str).eq(add_category)].copy()

            material_options={
                f"{int(r['id'])} — {r['name']}":int(r['id'])
                for _,r in filtered_add_materials.sort_values("name").iterrows()
            }
            if not material_options:
                st.info("В выбранной категории материалов нет.")
            else:
                with st.form("supplier_material_link_form_new"):
                    material_label=st.selectbox("Материал для добавления",list(material_options.keys()))
                    price=st.number_input("Закупочная цена",min_value=0.0,value=0.0,format="%.2f")
                    code=st.text_input("Код поставщика")
                    conditions=st.text_area("Условия")
                    preferred=st.checkbox("Предпочтительный поставщик")
                    if st.form_submit_button("Добавить материал поставщику"):
                        run_query(
                            """INSERT INTO reklet.material_suppliers
                               (material_id,supplier_id,purchase_price,supplier_code,conditions,is_preferred)
                               VALUES (%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(material_id,supplier_id)
                               DO UPDATE SET purchase_price=EXCLUDED.purchase_price,
                                             supplier_code=EXCLUDED.supplier_code,
                                             conditions=EXCLUDED.conditions,
                                             is_preferred=EXCLUDED.is_preferred""",
                            (material_options[material_label],supplier_id,price,code.strip() or None,
                             conditions.strip() or None,preferred)
                        )
                        st.success("Материал поставщику добавлен.")
                        st.rerun()

            if not linked.empty:
                with st.expander("Убрать материал у поставщика",expanded=False):
                    link_map={
                        f"{int(r['material_id'])} — {r['material']}":int(r['material_id'])
                        for _,r in linked.iterrows()
                    }
                    unlink_label=st.selectbox("Материал",list(link_map.keys()),key="unlink_supplier_material")
                    unlink_confirm=st.checkbox(
                        "Я подтверждаю удаление связи поставщик → материал.",
                        key="confirm_unlink_supplier_material"
                    )
                    if st.button("Убрать материал у поставщика",key="unlink_supplier_material_button",disabled=not unlink_confirm):
                        run_query(
                            "DELETE FROM reklet.material_suppliers WHERE supplier_id=%s AND material_id=%s",
                            (supplier_id,link_map[unlink_label])
                        )
                        st.success("Материал убран из списка поставщика.")
                        st.rerun()


    elif supplier_sub=="Поиск поставщика":
        st.subheader("Поиск поставщика")

        all_materials = get_materials_with_categories()
        material_categories = get_material_categories()

        if all_materials.empty:
            st.info("Материалов пока нет.")
        else:
            category_options = ["Все категории", "Без категории"] + (
                material_categories["name"].astype(str).tolist()
                if not material_categories.empty else []
            )

            filter_category_col, filter_material_col = st.columns(2, gap="small")
            with filter_category_col:
                search_category = st.selectbox(
                    "Категория материала",
                    category_options,
                    key="supplier_search_category"
                )

            filtered_materials = all_materials.copy()
            if search_category == "Без категории":
                filtered_materials = filtered_materials[
                    filtered_materials["category_id"].isna()
                ].copy()
            elif search_category != "Все категории":
                filtered_materials = filtered_materials[
                    filtered_materials["category_name"].fillna("").astype(str).eq(search_category)
                ].copy()

            if filtered_materials.empty:
                st.info("В выбранной категории материалов нет.")
            else:
                material_map = {
                    f"{int(row['id'])} — {row['name']}": int(row['id'])
                    for _, row in filtered_materials.sort_values("name").iterrows()
                }

                with filter_material_col:
                    selected_material = st.selectbox(
                        "Материал",
                        list(material_map.keys()),
                        key="supplier_search_material_new"
                    )
                material_id = material_map[selected_material]

                suppliers_for_material = run_query(
                    """
                    SELECT
                        s.id,
                        s.name AS supplier,
                        ms.purchase_price,
                        ms.supplier_code,
                        ms.conditions,
                        ms.is_preferred
                    FROM reklet.material_suppliers ms
                    JOIN reklet.suppliers s
                        ON s.id = ms.supplier_id
                    WHERE ms.material_id = %s
                    ORDER BY s.name
                    """,
                    (material_id,),
                    fetch=True
                )

                if suppliers_for_material.empty:
                    st.info("Для этого материала поставщики не назначены.")
                else:
                    supplier_view = suppliers_for_material.copy()
                    supplier_view.columns = [
                        "ID",
                        "Поставщик",
                        "Цена",
                        "Код поставщика",
                        "Условия",
                        "Предпочтительный"
                    ]
                    st.dataframe(
                        supplier_view,
                        width="stretch",
                        hide_index=True
                    )
                    render_print_html(
                        f"Поставщики материала — {str(selected_material).split(' — ', 1)[-1]}",
                        supplier_view,
                        f"print_supplier_search_{material_id}",
                        subtitle=f"Категория: {search_category}"
                    )
    render_page_instruction("suppliers")
