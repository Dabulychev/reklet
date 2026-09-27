import streamlit as st
import pandas as pd
from html import escape

from core.db import get_connection, run_query, run_transaction
from core.formatting import safe_int, safe_float, money
from core.printing import printable_html, render_print_html
from core.ui import data_editor_ru, render_button_nav
from repositories.clients import get_clients
from repositories.objects import (
    get_objects,
    get_stage_objects,
    get_object_items,
)
from repositories.materials import (
    get_materials,
    get_materials_with_categories,
    get_material_categories,
)
from repositories.suppliers import get_suppliers
from repositories.products import (
    get_templates,
    get_product_categories,
    get_product_category_names,
)
from database.migrations import (
    ensure_product_category_table,
    ensure_stage_movement_tables,
    initialize_database,
    ensure_material_planning_tables,
    ensure_object_item_material_costs,
)
from services.material_planning import get_object_material_planning
from modules.warehouse import warehouse_select_object
from modules.reports import movement_options
from modules.objects import render_objects
from modules.clients import render_clients
from modules.products import render_products
from modules.suppliers import render_suppliers


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Reklet — Управление производством",
    layout="wide",
    initial_sidebar_state="expanded"
)



# ============================================================
# DATABASE STARTUP
# ============================================================

# The production database schema is already present.
# Do not execute CREATE TABLE/INDEX statements on every Streamlit rerun:
# PostgreSQL DDL may wait on a lock and make the app appear to load forever.
# initialize_database() remains available above for controlled migrations.


# ============================================================
# AUTHENTICATION
# ============================================================

if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if "demo_mode" not in st.session_state:
    st.session_state["demo_mode"] = False


if not st.session_state["authentication_status"]:

    st.title("Reklet — Управление производством")
    st.subheader("Войти")

    with st.form("login_form"):

        username_input = st.text_input("Логин")

        password_input = st.text_input(
            "Пароль",
            type="password"
        )

        submit_login = st.form_submit_button("Войти")

        if submit_login:

            # ==================================================
            # ADMIN LOGIN
            # ==================================================

            if (
                username_input == "admin"
                and password_input == "qwert12345"
            ):

                st.session_state["authentication_status"] = True
                st.session_state["username"] = "admin"
                st.session_state["name"] = "Administrator"

                # Admin works with real database changes
                st.session_state["demo_mode"] = False

                st.rerun()


            # ==================================================
            # DEMO LOGIN
            # ==================================================

            elif (
                username_input == "demo"
                and password_input == "demo"
            ):

                st.session_state["authentication_status"] = True
                st.session_state["username"] = "demo"
                st.session_state["name"] = "Demo User"

                # Demo flag.
                # Transaction logic will be added in Step 4.
                st.session_state["demo_mode"] = True

                st.rerun()


            # ==================================================
            # INVALID LOGIN
            # ==================================================

            else:

                st.session_state["authentication_status"] = False

                st.error(
                    "Неверный логин или пароль"
                )

    st.stop()


try:
    ensure_material_planning_tables()
except Exception as e:
    st.error("Не удалось подготовить складскую модель данных.")
    st.code(str(e))
    st.stop()


# ============================================================
# HELPER FUNCTIONS
# ============================================================




# ============================================================
# DATA FUNCTIONS
# ============================================================








# ============================================================
# SIMPLE RECTANGULAR NAVIGATION
# ============================================================
# Navigation uses real Streamlit buttons, not radio widgets.
# Therefore there are no radio circles/dots and no radio selection
# animation.  All navigation controls are plain rectangular buttons.
st.markdown("""
<style>
.stButton > button {
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    transform: none !important;
    min-height: 38px !important;
    padding: 0.35rem 0.75rem !important;
    font-weight: 400 !important;
}
.stButton > button:hover,
.stButton > button:focus,
.stButton > button:active {
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    transform: none !important;
}

/* ===== Управление объектами: визуальное разделение этапов ===== */
.stage-guide {
    margin: 0.35rem 0 0.85rem 0;
    border: 1px solid rgba(120,140,165,.35);
    border-radius: 4px;
    overflow: hidden;
    background: rgba(20,25,35,.18);
}
.stage-title {
    padding: .55rem .8rem;
    font-size: .86rem;
    font-weight: 700;
    letter-spacing: .03em;
}
.stage-groups {
    display: grid;
    grid-template-columns: 16% 12% 14% 21% 14% 23%;
    min-height: 58px;
}
.stage-spacer, .stage-group {
    padding: .55rem .45rem;
    border-right: 1px solid rgba(100,120,145,.35);
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
}
.stage-spacer {
    text-align: left;
    font-weight: 600;
    background: rgba(100,120,145,.10);
}
.stage-group b { font-size: .84rem; }
.stage-group span { font-size: .70rem; opacity: .78; margin-top: .18rem; }
.stage-order { background: rgba(80,120,190,.10); }
.stage-production { background: rgba(80,160,220,.12); }
.stage-warehouse { background: rgba(70,175,175,.11); }
.stage-transport { background: rgba(210,170,70,.12); }
.stage-installation { background: rgba(80,165,100,.12); border-right: 0; }
.stage-legend {
    display: flex;
    flex-wrap: wrap;
    gap: .7rem 1.1rem;
    padding: .48rem .75rem;
    border-top: 1px solid rgba(100,120,145,.30);
    font-size: .74rem;
}
.legend-system { color: #2b75d6; }
.legend-action { color: #218c45; }
.legend-flow { opacity: .78; }

/* Make the data editor feel like one continuous process table. */
[data-testid="stDataEditor"] {
    border-top: 2px solid rgba(100,120,145,.30);
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# MAIN NAVIGATION
# ============================================================

menu_options = [
    "Клиенты",
    "Объекты",
    "Изделия",
    "Склад материалов",
    "Поставщики",
    "Производство",
    "Готовая продукция",
    "Транспорт и логистика",
    "Монтаж",
    "Зарплата",
    "Отчёты"
]

menu = render_button_nav(
    menu_options,
    "main_menu",
    "main_nav",
    columns_per_row=11
)

st.markdown("---")


# ============================================================
# CLIENTS
# ============================================================


if menu == "Клиенты":
    render_clients()

# OBJECTS
# ============================================================
elif menu == "Объекты":
    render_objects()

elif menu == "Изделия":
    render_products()

# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Склад материалов":

    st.header("Склад материалов")

    material_sections = [
        ("Перечень материалов", "list"),
        ("Потребность и резерв", "planning"),
        ("Закупка материалов", "purchase"),
        ("Приход материалов", "receipt"),
        ("Выдача материалов в производство", "issue"),
        ("Движение материалов", "movement"),
    ]

    valid_material_sections={value for _,value in material_sections}
    if st.session_state.get("material_section") not in valid_material_sections:
        st.session_state.material_section = "list"

    for start_idx in range(0,len(material_sections),3):
        row=material_sections[start_idx:start_idx+3]
        cols=st.columns(len(row),gap="small")
        for col,(label,value) in zip(cols,row):
            with col:
                if st.button(label,key=f"material_nav_{start_idx}_{value}",use_container_width=True):
                    st.session_state.material_section=value
                    st.rerun()

    active_material_section=st.session_state.material_section
    materials=get_materials_with_categories()
    categories=get_material_categories()

    if active_material_section=="list":
        st.subheader("Перечень материалов")
        cat_options=["Все материалы","Без категории"]+(categories["name"].astype(str).tolist() if not categories.empty else [])
        selected_cat=st.selectbox("Отбор по категории",cat_options,key="material_category_filter")
        filtered=materials.copy()
        if selected_cat=="Без категории": filtered=filtered[filtered["category_id"].isna()].copy()
        elif selected_cat!="Все материалы": filtered=filtered[filtered["category_name"].fillna("").astype(str).eq(selected_cat)].copy()
        if filtered.empty:
            st.info("Материалы по выбранному отбору отсутствуют.")
        else:
            ra=run_query("SELECT material_id,COALESCE(SUM(quantity_reserved),0) AS reserved_quantity FROM reklet.material_reservations GROUP BY material_id",fetch=True)
            rmap={safe_int(r["material_id"]):safe_float(r["reserved_quantity"]) for _,r in ra.iterrows()} if not ra.empty else {}

            # Основной перечень материалов — только просмотр. Изменение
            # данных выполняется в раскрывающемся блоке ниже, чтобы здесь
            # не было скрытых редактирований и случайных изменений.
            display=filtered[[
                "id","name","category_name","unit_name","cost_per_unit",
                "stock_quantity","default_waste_coefficient"
            ]].copy()
            display["reserved_quantity"]=display["id"].map(rmap).fillna(0.0)
            display["available_quantity"]=(
                pd.to_numeric(display["stock_quantity"],errors="coerce").fillna(0)
                - display["reserved_quantity"]
            ).clip(lower=0)
            display=display[[
                "id","name","category_name","unit_name","cost_per_unit",
                "stock_quantity","reserved_quantity","available_quantity",
                "default_waste_coefficient"
            ]].copy()
            display.columns=[
                "ID","Материал","Категория","Единица","Цена за единицу",
                "На складе","Зарезервировано","Доступно","Коэффициент отходов"
            ]

            st.dataframe(display,width="stretch",hide_index=True)
            render_print_html(
                "Перечень материалов",
                display,
                "print_material_list",
                subtitle=f"Категория: {selected_cat}"
            )

            # --------------------------------------------------------
            # ДОБАВИТЬ / КОРРЕКТИРОВАТЬ МАТЕРИАЛ — раскрывающийся блок
            # --------------------------------------------------------
            with st.expander("Добавить/корректировать материал", expanded=False):

                # ----------------------------------------------------
                # ДОБАВИТЬ МАТЕРИАЛ
                # ----------------------------------------------------
                with st.expander("Добавить материал", expanded=False):
                    st.subheader("Добавить материал")
                    units=run_query("SELECT id,name FROM reklet.units ORDER BY name",fetch=True)
                    unit_map={str(r["name"]):int(r["id"]) for _,r in units.iterrows()} if not units.empty else {}
                    cat_options_add=["— Без категории —"]+(categories["name"].astype(str).tolist() if not categories.empty else [])
                    suppliers_for_add = get_suppliers()
                    supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers_for_add.iterrows()} if not suppliers_for_add.empty else {}

                    with st.form("add_material_form_list_expander_v2"):
                        name=st.text_input("Название материала", key="add_material_name_expander_v2")
                        unit=st.selectbox("Единица измерения",list(unit_map.keys()), key="add_material_unit_expander_v2") if unit_map else None
                        cat=st.selectbox("Категория",cat_options_add, key="add_material_category_expander_v2")
                        price=st.number_input("Цена за единицу",min_value=0.0,value=0.0,format="%.2f", key="add_material_price_expander_v2")
                        stock=st.number_input("Начальный остаток",min_value=0.0,value=0.0,format="%.4f", key="add_material_stock_expander_v2")
                        waste=st.number_input("Коэффициент отходов",min_value=0.0,value=1.20,format="%.2f", key="add_material_waste_expander_v2")
                        chosen_suppliers=st.multiselect(
                            "Поставщики (можно выбрать одного или нескольких)",
                            list(supplier_map.keys()),
                            key="add_material_suppliers_expander_v2"
                        )
                        submit=st.form_submit_button("Добавить материал",use_container_width=True)
                        if submit:
                            if not name.strip() or not unit_map:
                                st.warning("Укажите название материала и единицу измерения.")
                            else:
                                st.session_state["pending_material_create_list_expander_v2"]={
                                    "name":name.strip(),
                                    "unit_id":unit_map[unit],
                                    "unit_name":unit,
                                    "category":cat,
                                    "price":price,
                                    "stock":stock,
                                    "waste":waste,
                                    "supplier_ids":[supplier_map[x] for x in chosen_suppliers],
                                    "supplier_labels":chosen_suppliers,
                                }

                    pending_create=st.session_state.get("pending_material_create_list_expander_v2")
                    if pending_create:
                        st.warning("Подтвердите добавление материала в перечень.")
                        cat_text=pending_create["category"] if pending_create["category"]!="— Без категории —" else "без категории"
                        suppliers_text=", ".join(pending_create["supplier_labels"]) if pending_create["supplier_labels"] else "поставщики пока не назначены"
                        st.write(f"**Материал:** {pending_create['name']}")
                        st.write(f"**Категория:** {cat_text}")
                        st.write(f"**Единица:** {pending_create['unit_name']}")
                        st.write(f"**Цена:** {pending_create['price']:.2f}  **Коэффициент отходов:** {pending_create['waste']:.2f}")
                        st.write(f"**Поставщики:** {suppliers_text}")
                        c1,c2=st.columns(2)
                        with c1:
                            confirm=st.button("Подтвердить добавление",key="confirm_material_create_list_expander_v2",use_container_width=True,type="primary")
                        with c2:
                            cancel=st.button("Отменить",key="cancel_material_create_list_expander_v2",use_container_width=True)
                        if cancel:
                            st.session_state.pop("pending_material_create_list_expander_v2",None)
                            st.rerun()
                        if confirm:
                            cmap={str(r["name"]):int(r["id"]) for _,r in categories.iterrows()}
                            cid=cmap.get(pending_create["category"]) if pending_create["category"]!="— Без категории —" else None
                            conn=get_connection(); cur=conn.cursor()
                            try:
                                cur.execute(
                                    """INSERT INTO reklet.materials(name,unit_id,category_id,cost_per_unit,stock_quantity,default_waste_coefficient)
                                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                                    (pending_create["name"],pending_create["unit_id"],cid,pending_create["price"],pending_create["stock"],pending_create["waste"])
                                )
                                material_id=int(cur.fetchone()[0])
                                for sid in pending_create["supplier_ids"]:
                                    cur.execute(
                                        """INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price)
                                           VALUES (%s,%s,%s)
                                           ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price""",
                                        (material_id,sid,pending_create["price"])
                                    )
                                conn.commit()
                            except Exception:
                                conn.rollback()
                                raise
                            finally:
                                cur.close()
                                conn.close()
                            st.session_state.pop("pending_material_create_list_expander_v2",None)
                            st.success(f"Материал «{pending_create['name']}» добавлен в перечень в категорию «{cat_text}».")
                            st.rerun()

                # ----------------------------------------------------
                # КОРРЕКТИРОВАТЬ МАТЕРИАЛ
                # ----------------------------------------------------
                pending_material_changes=st.session_state.get("pending_material_changes")
                with st.expander("Корректировать материал", expanded=bool(pending_material_changes)):
                    st.subheader("Корректировать материал")

                    correction_materials=filtered.copy()
                    correction_editor=correction_materials[
                        ["id","name","category_name","unit_name","cost_per_unit","stock_quantity","default_waste_coefficient"]
                    ].copy()
                    correction_editor.columns=[
                        "ID","Материал","Категория","Единица","Цена за единицу","На складе","Коэффициент отходов"
                    ]

                    correction_edited=st.data_editor(
                        correction_editor,
                        key="materials_correction_editor_v3",
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "ID":st.column_config.NumberColumn("ID",disabled=True),
                            "Материал":st.column_config.TextColumn("Материал"),
                            "Категория":st.column_config.SelectboxColumn(
                                "Категория",
                                options=[""]+categories["name"].astype(str).tolist(),
                                required=False
                            ),
                            "Единица":st.column_config.TextColumn("Единица",disabled=True),
                            "Цена за единицу":st.column_config.NumberColumn("Цена за единицу",min_value=0.0,format="%.2f"),
                            "На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),
                            "Коэффициент отходов":st.column_config.NumberColumn("Коэффициент отходов",min_value=0.0,format="%.2f")
                        },
                        disabled=["ID","Единица","На складе"]
                    )

                    if st.button("Выполнить",key="save_material_correction_v3",use_container_width=True):
                        original_by_id={safe_int(r["id"]):r for _,r in correction_materials.iterrows()}
                        changes=[]
                        for _,row in correction_edited.iterrows():
                            mid=safe_int(row["ID"])
                            old=original_by_id.get(mid)
                            if old is None:
                                continue
                            fields=[]
                            old_name=str(old["name"] or "").strip()
                            new_name=str(row["Материал"] or "").strip()
                            old_cat=str(old["category_name"] or "").strip() if pd.notna(old["category_name"]) else ""
                            new_cat=str(row["Категория"] or "").strip() if pd.notna(row["Категория"]) else ""
                            old_price=safe_float(old["cost_per_unit"])
                            new_price=safe_float(row["Цена за единицу"])
                            old_waste=safe_float(old["default_waste_coefficient"],1.20)
                            new_waste=safe_float(row["Коэффициент отходов"],1.20)
                            if old_name!=new_name:
                                fields.append(("Материал",old_name,new_name))
                            if old_cat!=new_cat:
                                fields.append(("Категория",old_cat or "—",new_cat or "—"))
                            if abs(old_price-new_price)>1e-9:
                                fields.append(("Цена за единицу",f"{old_price:.2f}",f"{new_price:.2f}"))
                            if abs(old_waste-new_waste)>1e-9:
                                fields.append(("Коэффициент отходов",f"{old_waste:.2f}",f"{new_waste:.2f}"))
                            if fields:
                                changes.append({
                                    "id":mid,
                                    "fields":fields,
                                    "name":new_name,
                                    "category":new_cat,
                                    "price":new_price,
                                    "waste":new_waste
                                })
                        if changes:
                            st.session_state["pending_material_changes"]=changes
                            st.rerun()
                        else:
                            st.info("Изменений нет.")

                    pending_material_changes=st.session_state.get("pending_material_changes")
                    if pending_material_changes:
                        st.warning("Подтверждение изменений материалов")
                        confirm_rows=[]
                        for ch in pending_material_changes:
                            for field,before,after in ch["fields"]:
                                confirm_rows.append({
                                    "Материал":ch["name"],
                                    "Поле":field,
                                    "Было":before,
                                    "Станет":after
                                })
                        st.dataframe(pd.DataFrame(confirm_rows),width="stretch",hide_index=True)
                        c1,c2=st.columns(2)
                        with c1:
                            confirm_materials=st.button("Подтвердить",key="confirm_material_changes_v3",use_container_width=True,type="primary")
                        with c2:
                            cancel_materials=st.button("Отменить",key="cancel_material_changes_v3",use_container_width=True)
                        if cancel_materials:
                            st.session_state.pop("pending_material_changes",None)
                            st.rerun()
                        if confirm_materials:
                            cmap={str(r["name"]):int(r["id"]) for _,r in categories.iterrows()}
                            statements=[]
                            for ch in pending_material_changes:
                                statements.append((
                                    "UPDATE reklet.materials SET name=%s,category_id=%s,cost_per_unit=%s,default_waste_coefficient=%s WHERE id=%s",
                                    (ch["name"],cmap.get(ch["category"]) if ch["category"] else None,ch["price"],ch["waste"],ch["id"])
                                ))
                            run_transaction(statements)
                            st.session_state.pop("pending_material_changes",None)
                            st.success("Изменения материалов подтверждены и сохранены.")
                            st.rerun()

                # ----------------------------------------------------
                # БЕЗОПАСНО УДАЛИТЬ МАТЕРИАЛ
                # ----------------------------------------------------
                with st.expander("Безопасно удалить материал", expanded=False):
                    st.warning(
                        "Удаление материала необратимо. Связи с поставщиками сами по себе "
                        "не считаются использованием и будут удалены вместе с материалом. "
                        "Материал с фактическими операциями или зависимостями удалить нельзя."
                    )

                    all_materials_delete=get_materials_with_categories()
                    if all_materials_delete.empty:
                        st.info("Материалов для удаления нет.")
                    else:
                        delete_material_map={
                            f"{int(r['id'])} — {r['name']}":int(r['id'])
                            for _,r in all_materials_delete.sort_values("name").iterrows()
                        }
                        delete_material_label=st.selectbox(
                            "Материал",
                            list(delete_material_map.keys()),
                            key="safe_delete_material_select_v3"
                        )
                        delete_material_id=delete_material_map[delete_material_label]
                        selected_delete_material=all_materials_delete[
                            all_materials_delete["id"]==delete_material_id
                        ].iloc[0]

                        # Supplier links are master-data associations, not evidence that
                        # the material was actually used. They are safe to remove together
                        # with the material when no operational dependency exists.
                        supplier_links=run_query(
                            "SELECT COUNT(*) AS cnt FROM reklet.material_suppliers WHERE material_id=%s",
                            (delete_material_id,),fetch=True
                        )
                        supplier_link_count=safe_int(supplier_links.iloc[0]["cnt"]) if not supplier_links.empty else 0

                        stock_qty=safe_float(selected_delete_material.get("stock_quantity",0))
                        st.write(f"**Остаток на складе:** {stock_qty:.4f}")
                        if supplier_link_count:
                            st.caption(f"Связей с поставщиками: {supplier_link_count}. При удалении они будут удалены автоматически вместе с материалом.")

                        delete_confirm=st.checkbox(
                            "Я подтверждаю, что хочу удалить выбранный материал.",
                            key=f"safe_delete_material_confirm_v3_{delete_material_id}"
                        )

                        if st.button(
                            "Удалить материал",
                            key=f"safe_delete_material_button_v3_{delete_material_id}",
                            disabled=not delete_confirm,
                            use_container_width=True
                        ):
                            try:
                                refs=run_query(
                                    """
                                    SELECT
                                        n.nspname AS schema_name,
                                        c.relname AS table_name,
                                        a.attname AS column_name
                                    FROM pg_constraint con
                                    JOIN pg_class c ON c.oid=con.conrelid
                                    JOIN pg_namespace n ON n.oid=c.relnamespace
                                    JOIN unnest(con.conkey) WITH ORDINALITY AS ck(attnum,ord) ON TRUE
                                    JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ck.attnum
                                    WHERE con.contype='f'
                                      AND con.confrelid='reklet.materials'::regclass
                                      AND n.nspname='reklet'
                                    ORDER BY c.relname,a.attname
                                    """,
                                    fetch=True
                                )

                                # material_suppliers is intentionally excluded: it is a
                                # removable master-data link, not a usage/dependency record.
                                dependencies=[]
                                if not refs.empty:
                                    for _,ref in refs.iterrows():
                                        table_name=str(ref["table_name"])
                                        column_name=str(ref["column_name"])
                                        if table_name=="material_suppliers":
                                            continue
                                        count_df=run_query(
                                            f"SELECT COUNT(*) AS cnt FROM reklet.{table_name} WHERE {column_name}=%s",
                                            (delete_material_id,),fetch=True
                                        )
                                        cnt=safe_int(count_df.iloc[0]["cnt"]) if not count_df.empty else 0
                                        if cnt>0:
                                            dependencies.append(f"{table_name} ({cnt})")

                                if stock_qty>0:
                                    st.error(
                                        "Удаление запрещено: у материала есть остаток на складе "
                                        f"({stock_qty:.4f}). Сначала удалите/спишите остаток."
                                    )
                                elif dependencies:
                                    st.error(
                                        "Удаление запрещено: материал уже используется в системе. "
                                        "Связанные записи: "+", ".join(dependencies)
                                    )
                                else:
                                    # Explicitly remove supplier associations first so the
                                    # operation is robust even if a live FK differs from the
                                    # expected ON DELETE CASCADE definition.
                                    run_transaction([
                                        ("DELETE FROM reklet.material_suppliers WHERE material_id=%s",(delete_material_id,)),
                                        ("DELETE FROM reklet.materials WHERE id=%s",(delete_material_id,))
                                    ])
                                    st.success(
                                        f"Материал «{selected_delete_material['name']}» безопасно удалён."
                                    )
                                    st.rerun()
                            except Exception as e:
                                st.error("Материал не удалён. Операция отменена.")
                                st.code(str(e))

            # --------------------------------------------------------
            # КАТЕГОРИИ МАТЕРИАЛОВ — раскрывающийся блок
            # --------------------------------------------------------
            with st.expander("Категории материалов", expanded=False):
                st.subheader("Категории материалов")
                categories_exp=get_material_categories()

                st.markdown("### Перечень категорий")
                if categories_exp.empty:
                    st.info("Категорий материалов нет.")
                else:
                    cat_view=categories_exp[["id","name"]].copy()
                    cat_view.columns=["ID","Категория"]
                    st.dataframe(cat_view,width="stretch",hide_index=True)

                with st.expander("Добавить категорию",expanded=False):
                    with st.form("add_material_category_form_list_expander"):
                        new=st.text_input("Название категории",key="new_material_category_name_list_expander")
                        if st.form_submit_button("Добавить",use_container_width=True):
                            if not new.strip():
                                st.warning("Укажите название категории.")
                            else:
                                try:
                                    run_query("INSERT INTO reklet.material_categories(name) VALUES (%s)",(new.strip(),))
                                    st.success(f"Категория «{new.strip()}» добавлена.")
                                    st.rerun()
                                except Exception:
                                    st.error("Не удалось добавить категорию. Возможно, такое название уже существует.")

                with st.expander("Корректировать категорию",expanded=False):
                    if categories_exp.empty:
                        st.info("Категорий нет.")
                    else:
                        cmap={f"{r['id']} — {r['name']}":int(r['id']) for _,r in categories_exp.iterrows()}
                        label=st.selectbox("Категория",list(cmap.keys()),key="edit_material_category_select_list_expander")
                        cid=cmap[label]
                        current=str(categories_exp[categories_exp["id"]==cid].iloc[0]["name"])
                        with st.form("edit_material_category_form_list_expander"):
                            new=st.text_input("Новое название",value=current,key="edit_material_category_name_list_expander")
                            if st.form_submit_button("Выполнить",use_container_width=True):
                                if not new.strip():
                                    st.warning("Название не может быть пустым.")
                                elif new.strip()==current:
                                    st.info("Изменений нет.")
                                else:
                                    st.session_state["pending_material_category_edit_list_expander"]={"id":cid,"old":current,"new":new.strip()}

                        pending_cat=st.session_state.get("pending_material_category_edit_list_expander")
                        if pending_cat and int(pending_cat["id"])==cid:
                            st.warning("Подтверждение изменения категории")
                            st.dataframe(pd.DataFrame([{"Категория":"Категория","Было":pending_cat["old"],"Станет":pending_cat["new"]}]),width="stretch",hide_index=True)
                            c1,c2=st.columns(2)
                            with c1:
                                ok=st.button("Подтвердить",key="confirm_material_category_edit_list_expander",use_container_width=True,type="primary")
                            with c2:
                                no=st.button("Отменить",key="cancel_material_category_edit_list_expander",use_container_width=True)
                            if no:
                                st.session_state.pop("pending_material_category_edit_list_expander",None)
                                st.rerun()
                            if ok:
                                run_query("UPDATE reklet.material_categories SET name=%s WHERE id=%s",(pending_cat["new"],pending_cat["id"]))
                                st.session_state.pop("pending_material_category_edit_list_expander",None)
                                st.success("Категория изменена.")
                                st.rerun()

                with st.expander("Безопасное удаление категории",expanded=False):
                    if categories_exp.empty:
                        st.info("Категорий нет.")
                    else:
                        cmap={f"{r['id']} — {r['name']}":int(r['id']) for _,r in categories_exp.iterrows()}
                        label=st.selectbox("Категория",list(cmap.keys()),key="delete_material_category_safe_list_expander")
                        cid=cmap[label]
                        st.warning("Удаление необратимо. Используемая материалами категория не может быть удалена.")
                        confirm=st.checkbox("Я подтверждаю удаление категории.",key="confirm_delete_material_category_safe_list_expander")
                        if st.button("Удалить категорию",key="delete_material_category_safe_button_list_expander",disabled=not confirm,use_container_width=True):
                            refs=run_query("SELECT COUNT(*) AS n FROM reklet.materials WHERE category_id=%s",(cid,),fetch=True)
                            if int(refs.iloc[0]["n"])>0:
                                st.error("Удаление запрещено: категория используется материалами.")
                            else:
                                run_query("DELETE FROM reklet.material_categories WHERE id=%s",(cid,))
                                st.success("Категория удалена.")
                                st.rerun()

    elif active_material_section=="add":
        st.subheader("Добавить материал")
        units=run_query("SELECT id,name FROM reklet.units ORDER BY name",fetch=True)
        unit_map={str(r["name"]):int(r["id"]) for _,r in units.iterrows()} if not units.empty else {}
        cat_options=["— Без категории —"]+(categories["name"].astype(str).tolist() if not categories.empty else [])
        suppliers_for_add = get_suppliers()
        supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers_for_add.iterrows()} if not suppliers_for_add.empty else {}

        with st.form("add_material_form"):
            name=st.text_input("Название материала")
            unit=st.selectbox("Единица измерения",list(unit_map.keys())) if unit_map else None
            cat=st.selectbox("Категория",cat_options)
            price=st.number_input("Цена за единицу",min_value=0.0,value=0.0,format="%.2f")
            stock=st.number_input("Начальный остаток",min_value=0.0,value=0.0,format="%.4f")
            waste=st.number_input("Коэффициент отходов",min_value=0.0,value=1.20,format="%.2f")
            chosen_suppliers=st.multiselect("Поставщики (можно выбрать одного или нескольких)",list(supplier_map.keys()),key="add_material_suppliers")
            submit=st.form_submit_button("Добавить материал")
            if submit:
                if not name.strip() or not unit_map:
                    st.warning("Укажите название материала и единицу измерения.")
                else:
                    st.session_state["pending_material_create"]={
                        "name":name.strip(),
                        "unit_id":unit_map[unit],
                        "unit_name":unit,
                        "category":cat,
                        "price":price,
                        "stock":stock,
                        "waste":waste,
                        "supplier_ids":[supplier_map[x] for x in chosen_suppliers],
                        "supplier_labels":chosen_suppliers,
                    }

        pending_create=st.session_state.get("pending_material_create")
        if pending_create:
            st.warning("Подтвердите добавление материала в перечень.")
            cat_text=pending_create["category"] if pending_create["category"]!="— Без категории —" else "без категории"
            suppliers_text=", ".join(pending_create["supplier_labels"]) if pending_create["supplier_labels"] else "поставщики пока не назначены"
            st.write(f"**Материал:** {pending_create['name']}")
            st.write(f"**Категория:** {cat_text}")
            st.write(f"**Единица:** {pending_create['unit_name']}  ")
            st.write(f"**Цена:** {pending_create['price']:.2f}  **Коэффициент отходов:** {pending_create['waste']:.2f}")
            st.write(f"**Поставщики:** {suppliers_text}")
            c1,c2=st.columns(2)
            with c1:
                confirm=st.button("Подтвердить добавление",key="confirm_material_create",use_container_width=True)
            with c2:
                cancel=st.button("Отменить",key="cancel_material_create",use_container_width=True)
            if cancel:
                st.session_state.pop("pending_material_create",None)
                st.rerun()
            if confirm:
                cmap={str(r["name"]):int(r["id"]) for _,r in categories.iterrows()}
                cid=cmap.get(pending_create["category"]) if pending_create["category"]!="— Без категории —" else None
                conn=get_connection()
                cur=conn.cursor()
                try:
                    cur.execute("""INSERT INTO reklet.materials(name,unit_id,category_id,cost_per_unit,stock_quantity,default_waste_coefficient) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",(pending_create["name"],pending_create["unit_id"],cid,pending_create["price"],pending_create["stock"],pending_create["waste"]))
                    material_id=int(cur.fetchone()[0])
                    for sid in pending_create["supplier_ids"]:
                        cur.execute("""INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price""",(material_id,sid,pending_create["price"]))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    cur.close()
                st.session_state.pop("pending_material_create",None)
                st.success(f"Материал «{pending_create['name']}» добавлен в перечень в категорию «{cat_text}».")
                st.rerun()

    elif active_material_section=="categories":
        st.subheader("Категории материалов")
        categories=get_material_categories()

        st.markdown("### Перечень категорий")
        if categories.empty:
            st.info("Категорий материалов нет.")
        else:
            cat_view=categories[["id","name"]].copy()
            cat_view.columns=["ID","Категория"]
            st.dataframe(cat_view,width="stretch",hide_index=True)

        with st.expander("Добавить категорию",expanded=False):
            with st.form("add_material_category_form_new"):
                new=st.text_input("Название категории",key="new_material_category_name")
                if st.form_submit_button("Добавить"):
                    if not new.strip():
                        st.warning("Укажите название категории.")
                    else:
                        try:
                            run_query("INSERT INTO reklet.material_categories(name) VALUES (%s)",(new.strip(),))
                            st.success(f"Категория «{new.strip()}» добавлена.")
                            st.rerun()
                        except Exception:
                            st.error("Не удалось добавить категорию. Возможно, такое название уже существует.")

        with st.expander("Корректировать категорию",expanded=False):
            if categories.empty:
                st.info("Категорий нет.")
            else:
                cmap={f"{r['id']} — {r['name']}":int(r['id']) for _,r in categories.iterrows()}
                label=st.selectbox("Категория",list(cmap.keys()),key="edit_material_category_select")
                cid=cmap[label]
                current=str(categories[categories["id"]==cid].iloc[0]["name"])
                with st.form("edit_material_category_form"):
                    new=st.text_input("Новое название",value=current)
                    if st.form_submit_button("Выполнить"):
                        if not new.strip():
                            st.warning("Название не может быть пустым.")
                        elif new.strip()==current:
                            st.info("Изменений нет.")
                        else:
                            st.session_state["pending_material_category_edit"]={"id":cid,"old":current,"new":new.strip()}

                pending_cat=st.session_state.get("pending_material_category_edit")
                if pending_cat and int(pending_cat["id"])==cid:
                    st.warning("Подтверждение изменения категории")
                    st.dataframe(pd.DataFrame([{"Категория":"Категория","Было":pending_cat["old"],"Станет":pending_cat["new"]}]),width="stretch",hide_index=True)
                    c1,c2=st.columns(2)
                    with c1:
                        ok=st.button("Подтвердить",key="confirm_material_category_edit",use_container_width=True)
                    with c2:
                        no=st.button("Отменить",key="cancel_material_category_edit",use_container_width=True)
                    if no:
                        st.session_state.pop("pending_material_category_edit",None)
                        st.rerun()
                    if ok:
                        run_query("UPDATE reklet.material_categories SET name=%s WHERE id=%s",(pending_cat["new"],pending_cat["id"]))
                        st.session_state.pop("pending_material_category_edit",None)
                        st.success("Категория изменена.")
                        st.rerun()

        with st.expander("Безопасное удаление категории",expanded=False):
            if categories.empty:
                st.info("Категорий нет.")
            else:
                cmap={f"{r['id']} — {r['name']}":int(r['id']) for _,r in categories.iterrows()}
                label=st.selectbox("Категория",list(cmap.keys()),key="delete_material_category_safe")
                cid=cmap[label]
                st.warning("Удаление необратимо. Используемая материалами категория не может быть удалена.")
                confirm=st.checkbox("Я подтверждаю удаление категории.",key="confirm_delete_material_category_safe")
                if st.button("Удалить категорию",key="delete_material_category_safe_button",disabled=not confirm):
                    refs=run_query("SELECT COUNT(*) AS n FROM reklet.materials WHERE category_id=%s",(cid,),fetch=True)
                    if int(refs.iloc[0]["n"])>0:
                        st.error("Удаление запрещено: категория используется материалами.")
                    else:
                        run_query("DELETE FROM reklet.material_categories WHERE id=%s",(cid,))
                        st.success("Категория удалена.")
                        st.rerun()

    elif active_material_section=="planning":
        st.subheader("Потребность и резерв материалов")
        object_id,object_row=warehouse_select_object("material_planning")
        if object_id is not None:
            planning=get_object_material_planning(object_id)
            if planning.empty: st.info("Для выбранного объекта нет потребности в материалах по спецификациям.")
            else:
                view=planning[["material_name","unit_name","required_quantity","issued_quantity","work_in_process_quantity","remaining_need","stock_quantity","reserved_quantity","available_quantity","ordered_outstanding","need_to_buy"]].copy(); view.columns=["Материал","Единица","Потребность","Выдано в производство","В производстве","Осталось потребно","На складе","Зарезервировано","Доступно","Ожидается","Нужно купить"]
                st.dataframe(view,width="stretch",hide_index=True); render_print_html(f"Потребность и резерв — {object_row['object_name']}",view,f"print_material_planning_{object_id}",subtitle=f"Заказчик: {object_row['client_name']}")
                action_df=planning[["material_id","material_name","unit_name","remaining_need","stock_quantity","reserved_quantity","available_quantity"]].copy(); action_df.insert(0,"Выбрать",False); action_df["Зарезервировать"]=0.0; action_df["Снять резерв"]=0.0; action_df.columns=["Выбрать","ID","Материал","Единица","Осталось потребно","На складе","Зарезервировано","Доступно","Зарезервировать","Снять резерв"]
                with st.form(f"material_reservation_form_{object_id}",clear_on_submit=False):
                    edited=st.data_editor(action_df,key=f"material_reservation_editor_{object_id}",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Осталось потребно":st.column_config.NumberColumn("Осталось потребно",disabled=True,format="%.4f"),"На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),"Зарезервировано":st.column_config.NumberColumn("Зарезервировано",disabled=True,format="%.4f"),"Доступно":st.column_config.NumberColumn("Доступно",disabled=True,format="%.4f"),"Зарезервировать":st.column_config.NumberColumn("Зарезервировать",min_value=0.0,step=0.001,format="%.4f"),"Снять резерв":st.column_config.NumberColumn("Снять резерв",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID","Материал","Единица","Осталось потребно","На складе","Зарезервировано","Доступно"])
                    execute=st.form_submit_button("Выполнить",use_container_width=True)
                if execute:
                    selected=edited[edited["Выбрать"].fillna(False)&((edited["Зарезервировать"].fillna(0)>0)|(edited["Снять резерв"].fillna(0)>0))].copy(); errors=[]; statements=[]
                    for _,row in selected.iterrows():
                        mid=safe_int(row["ID"]); add=safe_float(row["Зарезервировать"]); release=safe_float(row["Снять резерв"]); rem=safe_float(row["Осталось потребно"]); res=safe_float(row["Зарезервировано"]); avail=safe_float(row["Доступно"])
                        if add>0 and release>0: errors.append(f"{row['Материал']}: задайте только резерв или снятие резерва."); continue
                        if add>max(rem-res,0)+1e-9: errors.append(f"{row['Материал']}: можно зарезервировать максимум {max(rem-res,0):.4f}.")
                        if add>avail+1e-9: errors.append(f"{row['Материал']}: доступно только {avail:.4f}.")
                        if release>res+1e-9: errors.append(f"{row['Материал']}: текущий резерв только {res:.4f}.")
                        if add>0:
                            statements.append(("INSERT INTO reklet.material_reservations(object_id,material_id,quantity_reserved) SELECT %s,%s,%s WHERE %s>1e-9 ON CONFLICT(object_id,material_id) DO UPDATE SET quantity_reserved=reklet.material_reservations.quantity_reserved+EXCLUDED.quantity_reserved,updated_at=timezone('utc'::text,now())",(object_id,mid,add,add)))
                            statements.append(("INSERT INTO reklet.material_reservation_transactions(object_id,material_id,operation_type,quantity) VALUES (%s,%s,'reserve',%s)",(object_id,mid,add)))
                        elif release>0:
                            if release >= res-1e-9:
                                statements.append(("DELETE FROM reklet.material_reservations WHERE object_id=%s AND material_id=%s",(object_id,mid)))
                            else:
                                statements.append(("UPDATE reklet.material_reservations SET quantity_reserved=quantity_reserved-%s,updated_at=timezone('utc'::text,now()) WHERE object_id=%s AND material_id=%s",(release,object_id,mid)))
                            statements.append(("INSERT INTO reklet.material_reservation_transactions(object_id,material_id,operation_type,quantity) VALUES (%s,%s,'release',%s)",(object_id,mid,release)))
                    statements.append(("DELETE FROM reklet.material_reservations WHERE object_id=%s AND quantity_reserved<=0",(object_id,)))
                    if selected.empty: st.info("Выберите материал и укажите количество.")
                    elif errors: st.error("Резерв не изменён:\n"+"\n".join(errors))
                    else: run_transaction(statements); st.success("Резерв материалов обновлён."); st.session_state.pop(f"material_reservation_editor_{object_id}",None); st.rerun()

    elif active_material_section=="purchase":
        st.subheader("Закупка материалов")
        object_id,object_row=warehouse_select_object("material_purchase")
        if object_id is not None:
            planning=get_object_material_planning(object_id); need=planning[planning["need_to_buy"]>0.0000001].copy()
            if need.empty: st.success("Для выбранного объекта сейчас закупать нечего.")
            else:
                links=run_query("SELECT ms.material_id,s.id AS supplier_id,s.name AS supplier_name,ms.purchase_price,ms.is_preferred FROM reklet.material_suppliers ms JOIN reklet.suppliers s ON s.id=ms.supplier_id ORDER BY ms.material_id,ms.is_preferred DESC,s.name",fetch=True)
                default_supplier_name="ООО «Поставщик»"
                default_supplier_df=run_query("SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1",(default_supplier_name,),fetch=True)
                default_supplier_id=safe_int(default_supplier_df.iloc[0]["id"]) if not default_supplier_df.empty else None
                rows=[]
                for _,n in need.iterrows():
                    mid=safe_int(n["material_id"]); matches=links[links["material_id"].eq(mid)].copy() if not links.empty else pd.DataFrame()
                    if matches.empty:
                        price_df=run_query("SELECT COALESCE(cost_per_unit,0) AS cost_per_unit FROM reklet.materials WHERE id=%s",(mid,),fetch=True)
                        default_price=safe_float(price_df.iloc[0]["cost_per_unit"]) if not price_df.empty else 0.0
                        rows.append({"Выбрать":False,"ID":mid,"Материал":n["material_name"],"Нужно купить":safe_float(n["need_to_buy"]),"Поставщик":default_supplier_name,"Цена":default_price,"Купить":0.0,"supplier_id":default_supplier_id})
                    else:
                        for _,sr in matches.sort_values(["is_preferred","supplier_name"],ascending=[False,True]).iterrows(): rows.append({"Выбрать":False,"ID":mid,"Материал":n["material_name"],"Нужно купить":safe_float(n["need_to_buy"]),"Поставщик":sr["supplier_name"],"Цена":safe_float(sr["purchase_price"]),"Купить":0.0,"supplier_id":safe_int(sr["supplier_id"])})
                pdf=pd.DataFrame(rows)
                editor=pdf[["Выбрать","ID","Материал","Нужно купить","Поставщик","Цена","Купить"]].copy()
                with st.form(f"purchase_form_{object_id}",clear_on_submit=False):
                    edited=st.data_editor(editor,key=f"purchase_editor_{object_id}",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Нужно купить":st.column_config.NumberColumn("Нужно купить",disabled=True,format="%.4f"),"Поставщик":st.column_config.TextColumn("Поставщик",disabled=True),"Цена":st.column_config.NumberColumn("Цена",disabled=True,format="%.2f"),"Купить":st.column_config.NumberColumn("Купить",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID","Материал","Нужно купить","Поставщик","Цена"])
                    create=st.form_submit_button("Сформировать закупку",use_container_width=True)
                pending_key=f"material_purchase_pending_{object_id}"
                if create:
                    selected=edited[edited["Выбрать"].fillna(False)&(edited["Купить"].fillna(0)>0)].copy(); lines=[]; errors=[]
                    for idx,row in selected.iterrows():
                        sid=pdf.iloc[int(idx)].get("supplier_id")
                        lines.append({"material_id":safe_int(row["ID"]),"material_name":str(row["Материал"]),"supplier_id":(safe_int(sid) if sid is not None else None),"supplier_name":str(row["Поставщик"]),"quantity":safe_float(row["Купить"]),"unit_price":safe_float(row["Цена"]),"need_to_buy":safe_float(row["Нужно купить"])})
                    totals={}
                    for line in lines: totals[line["material_id"]]=totals.get(line["material_id"],0)+line["quantity"]
                    for mid,total in totals.items():
                        req=safe_float(need.loc[need["material_id"].eq(mid),"need_to_buy"].iloc[0])
                        if total+1e-9<req: errors.append(f"{need.loc[need['material_id'].eq(mid),'material_name'].iloc[0]}: закупка {total:.4f}, необходимо {req:.4f}. Потребность останется незакрытой.")
                    if not lines: st.warning("Выберите поставщика и укажите количество.")
                    else: st.session_state[pending_key]={"object_id":object_id,"object_name":str(object_row["object_name"]),"warnings":errors,"lines":lines}
                pending=st.session_state.get(pending_key)
                if pending:
                    st.markdown("---"); st.subheader("Подтверждение закупки")
                    if pending["warnings"]: st.warning("\n".join(pending["warnings"]))
                    cdf=pd.DataFrame(pending["lines"])[["material_name","supplier_name","quantity","unit_price"]].copy(); cdf.columns=["Материал","Поставщик","Количество","Цена"]; st.dataframe(cdf,width="stretch",hide_index=True)
                    c1,c2=st.columns(2)
                    with c1: confirm=st.button("Подтвердить закупку",key=f"confirm_purchase_{object_id}",use_container_width=True)
                    with c2: cancel=st.button("Отмена",key=f"cancel_purchase_{object_id}",use_container_width=True)
                    if confirm:
                        grouped={}
                        for line in pending["lines"]: grouped.setdefault(line["supplier_id"],[]).append(line)
                        statements=[]
                        for sid,ls in grouped.items():
                            values=[]
                            params=[]
                            if sid is not None:
                                params.extend([sid,f"Закупка для объекта: {pending['object_name']}"])
                                for line in ls:
                                    values.append("(%s,%s,%s,0,%s)")
                                    params.extend([pending["object_id"],line["material_id"],line["quantity"],line["unit_price"]])
                                sql=f"""WITH new_po AS (INSERT INTO reklet.purchase_orders(supplier_id,status,notes) VALUES (%s,'ordered',%s) RETURNING id) INSERT INTO reklet.purchase_order_items(purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price) SELECT new_po.id,x.object_id,x.material_id,x.quantity_ordered,x.quantity_received,x.unit_price FROM new_po CROSS JOIN (VALUES {', '.join(values)}) AS x(object_id,material_id,quantity_ordered,quantity_received,unit_price)"""
                                statements.append((sql,tuple(params)))
                            else:
                                # If the default supplier has not been created yet,
                                # create it atomically with the purchase order.
                                for line in ls:
                                    statements.append((
                                        """
                                        WITH existing_supplier AS (
                                            SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1
                                        ), created_supplier AS (
                                            INSERT INTO reklet.suppliers(name,type,category,conditions)
                                            SELECT %s,'material_supplier','Служебный','Условный поставщик по умолчанию'
                                            WHERE NOT EXISTS (SELECT 1 FROM existing_supplier)
                                            RETURNING id
                                        ), supplier AS (
                                            SELECT id FROM existing_supplier
                                            UNION ALL SELECT id FROM created_supplier
                                            LIMIT 1
                                        ), new_po AS (
                                            INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                                            SELECT id,'ordered',%s FROM supplier
                                            RETURNING id
                                        )
                                        INSERT INTO reklet.purchase_order_items(purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price)
                                        SELECT id,%s,%s,%s,0,%s FROM new_po
                                        """,
                                        (default_supplier_name,default_supplier_name,f"Закупка для объекта: {pending['object_name']}",pending["object_id"],line["material_id"],line["quantity"],line["unit_price"])
                                    ))
                        run_transaction(statements); st.session_state.pop(pending_key,None); st.session_state.pop(f"purchase_editor_{object_id}",None); st.success("Закупка создана. Материалы ожидаются до прихода."); st.rerun()
                    if cancel: st.session_state.pop(pending_key,None); st.rerun()
                st.markdown("---"); st.subheader("История закупок")
                history=run_query("""SELECT po.id AS \"№ закупки\",po.order_date AS \"Дата\",CASE po.status WHEN 'ordered' THEN 'Заказан' WHEN 'partial' THEN 'Частично получен' WHEN 'received' THEN 'Получен' WHEN 'cancelled' THEN 'Отменён' ELSE po.status END AS \"Статус\",s.name AS \"Поставщик\",c.name AS \"Заказчик\",o.object_name AS \"Объект\",m.name AS \"Материал\",poi.quantity_ordered AS \"Заказано\",poi.quantity_received AS \"Получено\",GREATEST(poi.quantity_ordered-poi.quantity_received,0) AS \"Осталось\",poi.unit_price AS \"Цена\" FROM reklet.purchase_order_items poi JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id JOIN reklet.suppliers s ON s.id=po.supplier_id JOIN reklet.objects o ON o.id=poi.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id JOIN reklet.materials m ON m.id=poi.material_id WHERE poi.object_id=%s ORDER BY po.id DESC,m.name LIMIT 500""",(object_id,),fetch=True)
                if not history.empty: st.dataframe(history,width="stretch",hide_index=True); render_print_html(f"История закупок — {object_row['object_name']}",history,f"print_purchase_history_{object_id}")

    elif active_material_section=="receipt":
        st.subheader("Приход материалов")
        openp=run_query("""SELECT poi.id AS purchase_item_id,po.id AS purchase_order_id,s.id AS supplier_id,s.name AS supplier_name,o.id AS object_id,o.object_name,c.name AS client_name,m.id AS material_id,m.name AS material_name,u.name AS unit_name,poi.quantity_ordered,poi.quantity_received,GREATEST(poi.quantity_ordered-poi.quantity_received,0) AS remaining_quantity,poi.unit_price FROM reklet.purchase_order_items poi JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id JOIN reklet.suppliers s ON s.id=po.supplier_id JOIN reklet.objects o ON o.id=poi.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id JOIN reklet.materials m ON m.id=poi.material_id LEFT JOIN reklet.units u ON u.id=m.unit_id WHERE po.status<>'cancelled' AND poi.quantity_received<poi.quantity_ordered ORDER BY po.id DESC,o.object_name,m.name LIMIT 500""",fetch=True)
        if openp.empty: st.info("Ожидающих закупок для прихода нет.")
        else:
            edf=openp[["purchase_item_id","purchase_order_id","supplier_name","client_name","object_name","material_name","unit_name","quantity_ordered","quantity_received","remaining_quantity","unit_price"]].copy(); edf.insert(0,"Выбрать",False); edf["Принять"]=0.0; edf.columns=["Выбрать","ID позиции","№ закупки","Поставщик","Заказчик","Объект","Материал","Единица","Заказано","Получено","Осталось","Цена","Принять"]
            with st.form("purchase_receipt_form",clear_on_submit=False):
                edited=st.data_editor(edf,key="purchase_receipt_editor",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID позиции":st.column_config.NumberColumn("ID позиции",disabled=True),"№ закупки":st.column_config.NumberColumn("№ закупки",disabled=True),"Поставщик":st.column_config.TextColumn("Поставщик",disabled=True),"Заказчик":st.column_config.TextColumn("Заказчик",disabled=True),"Объект":st.column_config.TextColumn("Объект",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True,format="%.4f"),"Получено":st.column_config.NumberColumn("Получено",disabled=True,format="%.4f"),"Осталось":st.column_config.NumberColumn("Осталось",disabled=True,format="%.4f"),"Цена":st.column_config.NumberColumn("Цена",disabled=True,format="%.2f"),"Принять":st.column_config.NumberColumn("Принять",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID позиции","№ закупки","Поставщик","Заказчик","Объект","Материал","Единица","Заказано","Получено","Осталось","Цена"])
                execute=st.form_submit_button("Оформить приход",use_container_width=True)
            if execute:
                selected=edited[edited["Выбрать"].fillna(False)&(edited["Принять"].fillna(0)>0)].copy(); errors=[]; statements=[]; groups={}
                for idx,row in selected.iterrows():
                    qty=safe_float(row["Принять"]); rem=safe_float(row["Осталось"]); raw=openp.loc[int(idx)];
                    if qty>rem+1e-9: errors.append(f"{row['Материал']} / закупка №{safe_int(row['№ закупки'])}: можно принять максимум {rem:.4f}.")
                    key=(safe_int(raw["object_id"]),safe_int(raw["material_id"])); groups[key]=groups.get(key,0)+qty
                caches={}; auto={}
                for (oid,mid),total in groups.items():
                    if oid not in caches: caches[oid]=get_object_material_planning(oid)
                    m=caches[oid]; match=m[m["material_id"].eq(mid)]
                    auto[(oid,mid)]=min(total,max(safe_float(match.iloc[0]["remaining_need"])-safe_float(match.iloc[0]["reserved_quantity"]),0.0)) if not match.empty else 0.0
                for idx,row in selected.iterrows():
                    raw=openp.loc[int(idx)]; qty=safe_float(row["Принять"])
                    statements.extend([("INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",(safe_int(raw["material_id"]),safe_int(raw["supplier_id"]),safe_int(raw["object_id"]),qty,safe_float(raw["unit_price"]))),("UPDATE reklet.purchase_order_items SET quantity_received=quantity_received+%s WHERE id=%s",(qty,safe_int(raw["purchase_item_id"]))),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,safe_int(raw["material_id"])))])
                for (oid,mid),qty in auto.items():
                    if qty>0: statements.append(("INSERT INTO reklet.material_reservations(object_id,material_id,quantity_reserved) SELECT %s,%s,%s WHERE %s>1e-9 ON CONFLICT(object_id,material_id) DO UPDATE SET quantity_reserved=reklet.material_reservations.quantity_reserved+EXCLUDED.quantity_reserved,updated_at=timezone('utc'::text,now())",(oid,mid,qty,qty)))
                for po_id in sorted({safe_int(openp.loc[int(i),"purchase_order_id"]) for i in selected.index}): statements.append(("""UPDATE reklet.purchase_orders po SET status=CASE WHEN NOT EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received<poi.quantity_ordered) THEN 'received' WHEN EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received>0) THEN 'partial' ELSE 'ordered' END WHERE po.id=%s""",(po_id,)))
                if selected.empty: st.warning("Выберите позиции и укажите количество принятого материала.")
                elif errors: st.error("Приход не выполнен:\n"+"\n".join(errors))
                else: run_transaction(statements); st.success("Приход оформлен. При необходимости материал автоматически зарезервирован за объектом."); st.session_state.pop("purchase_receipt_editor",None); st.rerun()

        st.markdown("---")
        with st.expander("Приход без предварительной закупки"):
            suppliers=get_suppliers(); smap={str(r["name"]):int(r["id"]) for _,r in suppliers.iterrows()} if not suppliers.empty else {}
            cat_options=["Все категории","Без категории"]+(categories["name"].astype(str).tolist() if not categories.empty else []); cat=st.selectbox("Категория материала",cat_options,key="manual_receipt_category"); manual=materials.copy()
            if cat=="Без категории": manual=manual[manual["category_id"].isna()].copy()
            elif cat!="Все категории": manual=manual[manual["category_name"].fillna("").astype(str).eq(cat)].copy()
            mdf=manual[["id","name","unit_name"]].copy(); mdf.insert(0,"Выбрать",False); mdf["Количество"]=0.0; mdf["Цена"]=0.0; mdf.columns=["Выбрать","ID","Материал","Единица","Количество","Цена"]
            default_supplier_name="ООО «Поставщик»"
            if default_supplier_name not in smap:
                supplier_options=[default_supplier_name]+list(smap.keys())
            else:
                supplier_options=list(smap.keys())
            supplier=st.selectbox("Поставщик",supplier_options,key="manual_receipt_supplier")
            with st.form("manual_receipt_form",clear_on_submit=False):
                edited=st.data_editor(mdf,key="manual_receipt_editor",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Количество":st.column_config.NumberColumn("Количество",min_value=0.0,step=0.001,format="%.4f"),"Цена":st.column_config.NumberColumn("Цена",min_value=0.0,step=0.01,format="%.2f")},disabled=["ID","Материал","Единица"])
                execute=st.form_submit_button("Выполнить приход",use_container_width=True)
            if execute:
                sel=edited[edited["Выбрать"].fillna(False)&(edited["Количество"].fillna(0)>0)].copy()
                if sel.empty: st.warning("Выберите материалы и укажите количество.")
                else:
                    sid=smap.get(supplier)
                    if sid is None and supplier==default_supplier_name:
                        existing_default=run_query("SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1",(default_supplier_name,),fetch=True)
                        if existing_default.empty:
                            created_default=run_query(
                                """INSERT INTO reklet.suppliers(name,type,category,conditions) VALUES (%s,'material_supplier','Служебный','Условный поставщик по умолчанию') RETURNING id""",
                                (default_supplier_name,),fetch=True
                            )
                            sid=safe_int(created_default.iloc[0]["id"])
                        else:
                            sid=safe_int(existing_default.iloc[0]["id"])
                    statements=[]
                    for _,row in sel.iterrows():
                        mid=safe_int(row["ID"]); qty=safe_float(row["Количество"]); price=safe_float(row["Цена"]); statements.extend([("INSERT INTO reklet.material_transactions(material_id,supplier_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,'purchase',%s,%s,'IN')",(mid,sid,qty,price)),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,mid))]);
                        if sid: statements.append(("INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",(mid,sid,price)))
                    run_transaction(statements); st.success(f"Приход выполнен: {len(sel)} поз."); st.session_state.pop("manual_receipt_editor",None); st.rerun()
        history=run_query("""SELECT mt.created_at AS \"Дата\",s.name AS \"Поставщик\",o.object_name AS \"Объект\",m.name AS \"Материал\",u.name AS \"Единица\",mt.quantity AS \"Количество\",mt.unit_price AS \"Цена\",mt.quantity*COALESCE(mt.unit_price,0) AS \"Сумма\" FROM reklet.material_transactions mt LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id LEFT JOIN reklet.objects o ON o.id=mt.object_id JOIN reklet.materials m ON m.id=mt.material_id LEFT JOIN reklet.units u ON u.id=m.unit_id WHERE mt.operation_type='purchase' AND mt.transaction_type='IN' ORDER BY mt.created_at DESC LIMIT 500""",fetch=True); st.markdown("---"); st.subheader("История прихода материалов")
        if not history.empty: st.dataframe(history,width="stretch",hide_index=True); render_print_html("Ведомость прихода материалов",history,"print_material_receipt_history")

    elif active_material_section=="issue":
        st.subheader("Выдача материалов в производство")
        object_id,object_row=warehouse_select_object("material_issue")
        if object_id is not None:
            planning=get_object_material_planning(object_id)
            if planning.empty: st.info("Для выбранного объекта нет потребности в материалах.")
            else:
                scope=st.selectbox("Материалы",["Все материалы","Только необходимые для объекта"],key="issue_material_scope"); issue=planning.copy();
                if scope=="Только необходимые для объекта": issue=issue[issue["remaining_need"]>0].copy()
                if issue.empty: st.info("Материалов для выбранного отбора нет.")
                else:
                    idf=issue[["material_id","material_name","unit_name","stock_quantity","required_quantity","issued_quantity","reserved_quantity"]].copy(); idf.insert(0,"Выбрать",False); idf["Доступно к выдаче"]=idf[["reserved_quantity","stock_quantity"]].min(axis=1); idf["Выдать"]=0.0; idf.columns=["Выбрать","ID","Материал","Единица","На складе","Потребность объекта","Выдано","Зарезервировано","Доступно к выдаче","Выдать"]
                    with st.form(f"issue_materials_form_{object_id}",clear_on_submit=False):
                        edited=st.data_editor(idf,key=f"issue_materials_editor_{object_id}_{scope}",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),"Потребность объекта":st.column_config.NumberColumn("Потребность объекта",disabled=True,format="%.4f"),"Выдано":st.column_config.NumberColumn("Выдано",disabled=True,format="%.4f"),"Зарезервировано":st.column_config.NumberColumn("Зарезервировано",disabled=True,format="%.4f"),"Доступно к выдаче":st.column_config.NumberColumn("Доступно к выдаче",disabled=True,format="%.4f"),"Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID","Материал","Единица","На складе","Потребность объекта","Выдано","Зарезервировано","Доступно к выдаче"]); execute=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
                    if execute:
                        selected=edited[edited["Выбрать"].fillna(False)&(edited["Выдать"].fillna(0)>0)].copy(); errors=[]; statements=[]
                        for _,row in selected.iterrows():
                            mid=safe_int(row["ID"]); qty=safe_float(row["Выдать"]); stock=safe_float(row["На складе"]); reserved=safe_float(row["Зарезервировано"])
                            if qty>stock+1e-9: errors.append(f"{row['Материал']}: на складе только {stock:.4f}.")
                            if qty>reserved+1e-9: errors.append(f"{row['Материал']}: зарезервировано только {reserved:.4f} для этого объекта.")
                            statements.extend([("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,object_id,qty)),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(qty,mid))])
                            if abs(qty-reserved) <= 1e-9:
                                statements.append(("DELETE FROM reklet.material_reservations WHERE object_id=%s AND material_id=%s",(object_id,mid)))
                            else:
                                statements.append(("UPDATE reklet.material_reservations SET quantity_reserved=quantity_reserved-%s,updated_at=timezone('utc'::text,now()) WHERE object_id=%s AND material_id=%s",(qty,object_id,mid)))
                        if selected.empty: st.warning("Выберите материалы и укажите количество.")
                        elif errors: st.error("Выдача не выполнена:\n"+"\n".join(errors))
                        else: run_transaction(statements); st.success("Материалы выданы в производство."); st.session_state.pop(f"issue_materials_editor_{object_id}_{scope}",None); st.rerun()

    elif active_material_section=="movement":
        ensure_material_planning_tables()
        st.subheader("Движение материалов")
        movements=run_query("""SELECT * FROM (
            SELECT mt.created_at AS tx_date,
                   CASE mt.operation_type
                       WHEN 'purchase' THEN 'Приход материала'
                       WHEN 'production_transfer' THEN 'Выдано в производство'
                       ELSE mt.operation_type
                   END AS operation_name,
                   c.name AS client_name,
                   o.object_name,
                   NULL::text AS product_name,
                   m.name AS material_name,
                   s.name AS supplier_name,
                   mt.quantity::numeric AS quantity,
                   mt.unit_price::numeric AS unit_price
            FROM reklet.material_transactions mt
            LEFT JOIN reklet.materials m ON m.id=mt.material_id
            LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id
            LEFT JOIN reklet.objects o ON o.id=mt.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id

            UNION ALL

            SELECT mc.created_at AS tx_date,
                   'Списано при производстве'::text AS operation_name,
                   c.name AS client_name,
                   o.object_name,
                   oi.item_name AS product_name,
                   m.name AS material_name,
                   NULL::text AS supplier_name,
                   mc.quantity::numeric AS quantity,
                   COALESCE(mc.unit_cost_snapshot,0)::numeric AS unit_price
            FROM reklet.material_consumption mc
            LEFT JOIN reklet.objects o ON o.id=mc.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            LEFT JOIN reklet.object_items oi ON oi.id=mc.object_item_id
            LEFT JOIN reklet.materials m ON m.id=mc.material_id

            UNION ALL

            SELECT mrt.created_at AS tx_date,
                   CASE mrt.operation_type
                       WHEN 'reserve' THEN 'Резерв материала'
                       WHEN 'release' THEN 'Снятие резерва'
                       ELSE mrt.operation_type
                   END AS operation_name,
                   c.name AS client_name,
                   o.object_name,
                   NULL::text AS product_name,
                   m.name AS material_name,
                   NULL::text AS supplier_name,
                   mrt.quantity::numeric AS quantity,
                   NULL::numeric AS unit_price
            FROM reklet.material_reservation_transactions mrt
            LEFT JOIN reklet.objects o ON o.id=mrt.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            LEFT JOIN reklet.materials m ON m.id=mrt.material_id
        ) x ORDER BY tx_date DESC LIMIT 500""",fetch=True)
        if movements.empty: st.info("Движений материалов пока нет.")
        else:
            view=movements.rename(columns={"tx_date":"Дата","operation_name":"Операция","client_name":"Заказчик","object_name":"Объект","product_name":"Изделие","material_name":"Материал","supplier_name":"Поставщик","quantity":"Количество","unit_price":"Цена"})[["Дата","Операция","Заказчик","Объект","Изделие","Материал","Поставщик","Количество","Цена"]]; st.dataframe(view,width="stretch",hide_index=True); render_print_html("Движение материалов",view,"print_material_movements")




# ============================================================
# SUPPLIERS
# ============================================================
elif menu == "Поставщики":
    render_suppliers()

# PRODUCTION
# ============================================================

elif menu == "Производство":

    ensure_material_planning_tables()
    st.header("Производство")
    ensure_stage_movement_tables()

    objects = get_stage_objects("production")
    if objects.empty:
        st.success("На производстве нет незавершённых заданий.")
    else:
        object_options = [f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _, r in objects.iterrows()]
        object_map = {x: int(x.split(" — ")[0]) for x in object_options}
        selected_object = st.selectbox("Объект", object_options, key="production_object_table")
        object_id = object_map[selected_object]

        production_df = run_query(
            """SELECT oi.id, oi.item_name, oi.quantity_needed,
                      COALESCE(oi.qty_new,0) AS qty_new,
                      COALESCE(oi.qty_production,0) AS qty_production,
                      COALESCE(oi.qty_ready,0) AS qty_ready,
                      (COALESCE(oi.quantity_needed,0) - COALESCE(oi.qty_new,0)) AS manufactured_total
               FROM reklet.object_items oi
               WHERE oi.object_id=%s
                 AND (COALESCE(oi.qty_new,0) > 0 OR COALESCE(oi.qty_production,0) > 0)
               ORDER BY oi.id""",
            (object_id,), fetch=True
        )

        if production_df.empty:
            st.success("Для выбранного объекта производство завершено.")
        else:
            ensure_object_item_material_costs(object_id)
            production_material_requirements = run_query(
                """
                SELECT oi.id AS object_item_id, ptm.material_id,
                       SUM(COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)
                           * COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS material_per_product
                FROM reklet.object_items oi
                JOIN reklet.product_template_materials ptm
                  ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                JOIN reklet.materials m
                  ON m.id=ptm.material_id
                LEFT JOIN reklet.object_item_material_costs oimc
                  ON oimc.object_item_id=oi.id
                 AND oimc.material_id=ptm.material_id
                WHERE oi.object_id=%s
                GROUP BY oi.id,ptm.material_id
                """,
                (object_id,), fetch=True
            )
            issued_materials = run_query(
                """SELECT material_id,COALESCE(SUM(quantity),0) AS issued_quantity
                   FROM reklet.material_transactions
                   WHERE object_id=%s AND operation_type='production_transfer' AND transaction_type='OUT'
                   GROUP BY material_id""",
                (object_id,), fetch=True
            )
            consumed_materials = run_query(
                """SELECT material_id,COALESCE(SUM(quantity),0) AS consumed_quantity
                   FROM reklet.material_consumption
                   WHERE object_id=%s GROUP BY material_id""",
                (object_id,), fetch=True
            )
            issued_map={safe_int(r["material_id"]):safe_float(r["issued_quantity"]) for _,r in issued_materials.iterrows()} if not issued_materials.empty else {}
            consumed_map={safe_int(r["material_id"]):safe_float(r["consumed_quantity"]) for _,r in consumed_materials.iterrows()} if not consumed_materials.empty else {}
            wip_map={mid:issued_map.get(mid,0.0)-consumed_map.get(mid,0.0) for mid in set(issued_map)|set(consumed_map)}
            req_map={}
            if not production_material_requirements.empty:
                for _,rr in production_material_requirements.iterrows():
                    req_map.setdefault(safe_int(rr["object_item_id"]),[]).append((safe_int(rr["material_id"]),safe_float(rr["material_per_product"])))

            editor = production_df[["id","item_name","quantity_needed","manufactured_total","qty_production","qty_ready"]].copy()
            editor.columns = ["ID","Изделие","Заказано","Изготовлено","В производстве","Уже на готовой продукции"]
            editor["Передать на склад"] = 0
            editor["Сразу смонтировать"] = 0

            production_print = editor[[
                "ID", "Изделие", "Заказано", "Изготовлено",
                "В производстве", "Уже на готовой продукции"
            ]].copy()
            render_print_html(
                f"Производственное задание — {selected_object}",
                production_print,
                f"print_production_{object_id}"
            )

            with st.form(f"production_form_{object_id}", clear_on_submit=False):
                edited = st.data_editor(
                    editor, key=f"production_excel_editor_{object_id}", width="stretch", hide_index=True,
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", disabled=True),
                        "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                        "Заказано": st.column_config.NumberColumn("Заказано", disabled=True),
                        "Изготовлено": st.column_config.NumberColumn("Изготовлено", min_value=0, step=1, format="%d"),
                        "В производстве": st.column_config.NumberColumn("В производстве", disabled=True),
                        "Уже на готовой продукции": st.column_config.NumberColumn("Уже на готовой продукции", disabled=True),
                        "Передать на склад": st.column_config.NumberColumn("Передать на склад", min_value=0, step=1, format="%d"),
                        "Сразу смонтировать": st.column_config.NumberColumn("Сразу смонтировать", min_value=0, step=1, format="%d"),
                    },
                    disabled=["ID","Изделие","Заказано","В производстве","Уже на готовой продукции"],
                )
                execute = st.form_submit_button("Выполнить", use_container_width=True)

            if execute:
                selected = edited[(pd.to_numeric(edited["Передать на склад"], errors="coerce").fillna(0) > 0) | (pd.to_numeric(edited["Сразу смонтировать"], errors="coerce").fillna(0) > 0) | (pd.to_numeric(edited["Изготовлено"], errors="coerce").fillna(0) != production_df["manufactured_total"].values)] .copy()
                errors=[]
                statements=[]
                consumption_plan=[]
                consumption_by_material={}
                for idx, r in edited.iterrows():
                    src = production_df.iloc[idx]
                    item_id=safe_int(r["ID"])
                    ordered=safe_int(src["quantity_needed"])
                    old_manufactured=safe_int(src["manufactured_total"])
                    new_manufactured=safe_int(r["Изготовлено"])
                    in_prod=safe_int(src["qty_production"])
                    to_stock=safe_int(r["Передать на склад"])
                    direct_install=safe_int(r["Сразу смонтировать"])
                    if new_manufactured < old_manufactured:
                        errors.append(f"{r['Изделие']}: количество изготовленного нельзя уменьшить ниже {old_manufactured}.")
                    if new_manufactured > ordered:
                        errors.append(f"{r['Изделие']}: изготовлено {new_manufactured}, заказано только {ordered}.")
                    added = new_manufactured - old_manufactured
                    if added > 0:
                        for material_id,per_product in req_map.get(item_id,[]):
                            qty_material=added*per_product
                            consumption_plan.append((item_id,material_id,qty_material))
                            consumption_by_material[material_id]=consumption_by_material.get(material_id,0.0)+qty_material
                    available_for_transfer = in_prod + max(added,0)
                    if to_stock + direct_install > available_for_transfer:
                        errors.append(f"{r['Изделие']}: передача {to_stock + direct_install} шт., доступно максимум {available_for_transfer} шт.")
                    if to_stock < 0 or direct_install < 0:
                        errors.append(f"{r['Изделие']}: количество не может быть отрицательным.")
                    if to_stock and direct_install:
                        pass
                    if errors and len(errors)>50: break

                    if new_manufactured != old_manufactured:
                        statements.append((
                            "UPDATE reklet.object_items SET qty_new=GREATEST(quantity_needed-%s-COALESCE(qty_ready,0)-COALESCE(qty_shipped,0)-COALESCE(qty_arrived,0)-COALESCE(qty_installing,0)-COALESCE(qty_installed,0),0), qty_production=COALESCE(qty_production,0)+%s, production_status='in_progress' WHERE id=%s",
                            (new_manufactured, added, item_id)
                        ))

                    total_transfer = to_stock + direct_install
                    if total_transfer:
                        statements.append((
                            "UPDATE reklet.object_items SET qty_production=GREATEST(COALESCE(qty_production,0)-%s,0), qty_ready=COALESCE(qty_ready,0)+%s WHERE id=%s",
                            (total_transfer, to_stock, item_id)
                        ))
                        statements.append((
                            "INSERT INTO reklet.production_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'completed',%s FROM reklet.object_items WHERE id=%s",
                            (total_transfer,item_id)
                        ))
                        if to_stock:
                            statements.append((
                                "INSERT INTO reklet.finished_goods (object_item_id,object_id,quantity,status) SELECT id,object_id,%s,'ready' FROM reklet.object_items WHERE id=%s",
                                (to_stock,item_id)
                            ))
                            statements.append((
                                "INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s",
                                (to_stock,item_id)
                            ))
                        if direct_install:
                            # Прямая передача: история проходит все четыре этапа,
                            # но промежуточные остатки не задерживаются на складе/транспорте.
                            statements.extend([
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("UPDATE reklet.object_items SET qty_installed=COALESCE(qty_installed,0)+%s, installation_status='completed', installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND((COALESCE(qty_installed,0)+%s)::numeric/quantity_needed*100)) ELSE 0 END WHERE id=%s", (direct_install,direct_install,item_id)),
                                ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.installation_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'complete',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                            ])

                for material_id,required_qty in consumption_by_material.items():
                    available_wip=wip_map.get(material_id,0.0)
                    if required_qty>available_wip+1e-9:
                        nm=run_query("SELECT name FROM reklet.materials WHERE id=%s",(material_id,),fetch=True)
                        name=str(nm.iloc[0]["name"]) if not nm.empty else str(material_id)
                        errors.append(f"{name}: для нового производства нужно {required_qty:.4f}, а в производстве доступно только {max(available_wip,0):.4f}. Сначала выдайте материал в производство.")
                if not errors:
                    for item_id,material_id,qty_material in consumption_plan:
                        statements.append((
                        """
                        INSERT INTO reklet.material_consumption
                            (object_item_id,object_id,material_id,quantity,unit_cost_snapshot)
                        SELECT %s,%s,%s,%s,
                               COALESCE(oimc.unit_cost,m.cost_per_unit,0)
                        FROM reklet.materials m
                        LEFT JOIN reklet.object_item_material_costs oimc
                          ON oimc.object_item_id=%s
                         AND oimc.material_id=%s
                        WHERE m.id=%s
                        """,
                        (item_id,object_id,material_id,qty_material,item_id,material_id,material_id)
                    ))

                if errors:
                    st.error("Операция не выполнена:\n" + "\n".join(errors))
                elif not statements:
                    st.info("Изменений нет.")
                else:
                    run_transaction(statements)
                    st.success("Производственные данные обновлены. Выполненные позиции исчезнут из рабочего списка.")
                    st.rerun()

elif menu == "Готовая продукция":

    st.header("Готовая продукция")
    ensure_stage_movement_tables()

    objects = get_stage_objects("finished_goods")
    if objects.empty:
        st.success("На складе готовой продукции нет незавершённых заданий.")
    else:
        object_options = [f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _, r in objects.iterrows()]
        object_map = {x: int(x.split(" — ")[0]) for x in object_options}
        selected_object = st.selectbox("Объект", object_options, key="finished_goods_object_filter")
        object_id = object_map[selected_object]

        df = run_query(
            """SELECT oi.id, oi.item_name, oi.quantity_needed AS ordered,
                      COALESCE(oi.qty_ready,0) AS ready,
                      COALESCE(oi.qty_shipped,0) AS shipped,
                      COALESCE(oi.qty_arrived,0) AS arrived
               FROM reklet.object_items oi
               WHERE oi.object_id=%s AND COALESCE(oi.qty_ready,0)>0
               ORDER BY oi.id""",
            (object_id,), fetch=True
        )

        if df.empty:
            st.success("Для выбранного объекта на складе готовой продукции нет изделий для передачи в транспорт.")
        else:
            editor=df[["id","item_name","ordered","ready","shipped","arrived"]].copy()
            editor.columns=["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
            editor["Передать в транспорт"]=0
            finished_goods_print = editor[["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]].copy()
            render_print_html(
                f"Готовая продукция — {selected_object}",
                finished_goods_print,
                f"print_finished_goods_{object_id}"
            )
            with st.form(f"finished_goods_form_{object_id}", clear_on_submit=False):
                edited=st.data_editor(
                    editor, key=f"finished_goods_editor_{object_id}", width="stretch", hide_index=True,
                    column_config={
                        "ID":st.column_config.NumberColumn("ID",disabled=True),
                        "Изделие":st.column_config.TextColumn("Изделие",disabled=True),
                        "Заказано":st.column_config.NumberColumn("Заказано",disabled=True),
                        "На складе":st.column_config.NumberColumn("На складе",disabled=True),
                        "Уже отправлено":st.column_config.NumberColumn("Уже отправлено",disabled=True),
                        "Доставлено":st.column_config.NumberColumn("Доставлено",disabled=True),
                        "Передать в транспорт":st.column_config.NumberColumn("Передать в транспорт",min_value=0,step=1,format="%d"),
                    },
                    disabled=["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
                )
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Передать в транспорт"]); available=safe_int(r["На складе"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, на складе только {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_ready=GREATEST(COALESCE(qty_ready,0)-%s,0), qty_shipped=COALESCE(qty_shipped,0)+%s WHERE id=%s",(qty,qty,item_id)),
                            ("UPDATE reklet.finished_goods SET quantity=GREATEST(quantity-%s,0), status=CASE WHEN quantity-%s<=0 THEN 'shipped' ELSE 'ready' END WHERE id=(SELECT id FROM reklet.finished_goods WHERE object_item_id=%s AND status='ready' AND quantity>0 ORDER BY created_at, id LIMIT 1)",(qty,qty,item_id)),
                            ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                            ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else:
                    run_transaction(statements); st.success("Изделия переданы в транспорт."); st.rerun()

    st.markdown("---")
    st.subheader("Движения по складу готовой продукции")
    movements=run_query("""SELECT fgt.id,o.object_name,c.name AS client_name,oi.item_name,fgt.operation_type,fgt.quantity,fgt.created_at FROM reklet.finished_goods_transactions fgt LEFT JOIN reklet.objects o ON o.id=fgt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=fgt.object_item_id ORDER BY fgt.created_at DESC LIMIT 500""",fetch=True)
    if movements.empty: st.info("Движений пока нет.")
    else:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"})
        finished_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy()
        st.dataframe(finished_movement_view,width="stretch",hide_index=True)
        render_print_html("Движения по складу готовой продукции", finished_movement_view, "print_finished_goods_movements")

# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Транспорт и логистика":

    st.header("Транспорт и логистика")
    ensure_stage_movement_tables()
    objects=get_stage_objects("transport")
    if objects.empty:
        st.success("В транспорте нет незавершённых заданий.")
    else:
        object_options=[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _,r in objects.iterrows()]
        object_map={x:int(x.split(" — ")[0]) for x in object_options}
        selected_object=st.selectbox("Объект",object_options,key="transport_object_filter")
        object_id=object_map[selected_object]
        df=run_query("""SELECT oi.id,oi.item_name,oi.quantity_needed AS ordered,COALESCE(oi.qty_shipped,0) AS shipped,COALESCE(oi.qty_arrived,0) AS arrived,GREATEST(COALESCE(oi.qty_shipped,0)-COALESCE(oi.qty_arrived,0),0) AS in_transit FROM reklet.object_items oi WHERE oi.object_id=%s AND COALESCE(oi.qty_shipped,0)>COALESCE(oi.qty_arrived,0) ORDER BY oi.id""",(object_id,),fetch=True)
        if df.empty:
            st.success("Для выбранного объекта нет изделий, ожидающих доставки.")
        else:
            editor=df[["id","item_name","ordered","shipped","arrived","in_transit"]].copy(); editor.columns=["ID","Изделие","Заказано","Отправлено","Доставлено","В пути"]; editor["Доставить на объект"]=0
            transport_print = editor[[
                "ID", "Изделие", "Заказано", "Отправлено", "Доставлено", "В пути"
            ]].copy()
            render_print_html(
                f"Доставка — {selected_object}",
                transport_print,
                f"print_transport_{object_id}"
            )
            with st.form(f"transport_form_{object_id}",clear_on_submit=False):
                edited=st.data_editor(editor,key=f"transport_editor_{object_id}",width="stretch",hide_index=True,column_config={
                    "ID":st.column_config.NumberColumn("ID",disabled=True),"Изделие":st.column_config.TextColumn("Изделие",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True),"Отправлено":st.column_config.NumberColumn("Отправлено",disabled=True),"Доставлено":st.column_config.NumberColumn("Доставлено",disabled=True),"В пути":st.column_config.NumberColumn("В пути",disabled=True),"Доставить на объект":st.column_config.NumberColumn("Доставить на объект",min_value=0,step=1,format="%d")},disabled=["ID","Изделие","Заказано","Отправлено","Доставлено","В пути"])
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Доставить на объект"]); available=safe_int(r["В пути"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, в пути только {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_shipped=GREATEST(COALESCE(qty_shipped,0)-%s,0), qty_arrived=COALESCE(qty_arrived,0)+%s WHERE id=%s",(qty,qty,item_id)),
                            ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                            ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else: run_transaction(statements); st.success("Изделия доставлены на объект."); st.rerun()

    st.markdown("---"); st.subheader("Движения транспорта")
    movements=run_query("""SELECT tt.id,o.object_name,c.name AS client_name,oi.item_name,tt.operation_type,tt.quantity,tt.created_at FROM reklet.transport_transactions tt LEFT JOIN reklet.objects o ON o.id=tt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=tt.object_item_id ORDER BY tt.created_at DESC LIMIT 500""",fetch=True)
    if not movements.empty:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); transport_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy(); st.dataframe(transport_movement_view,width="stretch",hide_index=True); render_print_html("Движения транспорта", transport_movement_view, "print_transport_movements")
    else: st.info("Движений транспорта пока нет.")

# ============================================================
# INSTALLATION
# ============================================================

elif menu == "Монтаж":

    st.header("Монтаж")
    ensure_stage_movement_tables()
    objects=get_stage_objects("installation")
    if objects.empty:
        st.success("На монтаже нет незавершённых заданий.")
    else:
        object_options=[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _,r in objects.iterrows()]
        object_map={x:int(x.split(" — ")[0]) for x in object_options}
        selected_object=st.selectbox("Объект",object_options,key="installation_object_filter")
        object_id=object_map[selected_object]
        df=run_query("""SELECT oi.id,oi.item_name,oi.quantity_needed AS ordered,COALESCE(oi.qty_arrived,0) AS arrived,COALESCE(oi.qty_installing,0) AS installing,COALESCE(oi.qty_installed,0) AS installed FROM reklet.object_items oi WHERE oi.object_id=%s AND COALESCE(oi.qty_arrived,0)>0 ORDER BY oi.id""",(object_id,),fetch=True)
        if df.empty:
            st.success("Для выбранного объекта нет изделий, доступных для монтажа.")
        else:
            editor=df[["id","item_name","ordered","arrived","installing","installed"]].copy(); editor.columns=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"]; editor["Смонтировать"]=0
            installation_print = editor[[
                "ID", "Изделие", "Заказано", "Прибыло", "В монтаже", "Смонтировано"
            ]].copy()
            render_print_html(
                f"Задание на монтаж — {selected_object}",
                installation_print,
                f"print_installation_{object_id}"
            )
            with st.form(f"installation_form_{object_id}",clear_on_submit=False):
                edited=st.data_editor(editor,key=f"installation_editor_{object_id}",width="stretch",hide_index=True,column_config={
                    "ID":st.column_config.NumberColumn("ID",disabled=True),"Изделие":st.column_config.TextColumn("Изделие",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True),"Прибыло":st.column_config.NumberColumn("Прибыло",disabled=True),"В монтаже":st.column_config.NumberColumn("В монтаже",disabled=True),"Смонтировано":st.column_config.NumberColumn("Смонтировано",disabled=True),"Смонтировать":st.column_config.NumberColumn("Смонтировать",min_value=0,step=1,format="%d")},disabled=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"])
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Смонтировать"]); available=safe_int(r["Прибыло"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, доступно для монтажа {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_arrived=GREATEST(COALESCE(qty_arrived,0)-%s,0), qty_installed=COALESCE(qty_installed,0)+%s, installation_status=CASE WHEN COALESCE(qty_installed,0)+%s>=quantity_needed THEN 'completed' ELSE 'in_progress' END, installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND((COALESCE(qty_installed,0)+%s)::numeric/quantity_needed*100)) ELSE 0 END WHERE id=%s",(qty,qty,qty,qty,item_id)),
                            ("INSERT INTO reklet.installation_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'complete',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else: run_transaction(statements); st.success("Монтаж выполнен."); st.rerun()

    st.markdown("---"); st.subheader("Движения по монтажу")
    movements=run_query("""SELECT it.id,o.object_name,c.name AS client_name,oi.item_name,it.operation_type,it.quantity,it.created_at FROM reklet.installation_transactions it LEFT JOIN reklet.objects o ON o.id=it.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=it.object_item_id ORDER BY it.created_at DESC LIMIT 500""",fetch=True)
    if not movements.empty:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); installation_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy(); st.dataframe(installation_movement_view,width="stretch",hide_index=True); render_print_html("Движения по монтажу", installation_movement_view, "print_installation_movements")
    else: st.info("Движений монтажа пока нет.")

# ============================================================
# PAYROLL
# ============================================================

elif menu == "Зарплата":

    ensure_material_planning_tables()
    st.header("Зарплата")

    if "payroll_section" not in st.session_state:
        st.session_state.payroll_section = "Производство"

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Зарплата производства", key="payroll_production_btn", width="stretch"):
            st.session_state.payroll_section = "Производство"
            st.rerun()
    with b2:
        if st.button("Зарплата транспортировки", key="payroll_transport_btn", width="stretch"):
            st.session_state.payroll_section = "Транспортировка"
            st.rerun()
    with b3:
        if st.button("Зарплата монтажа", key="payroll_install_btn", width="stretch"):
            st.session_state.payroll_section = "Монтаж"
            st.rerun()
    with b4:
        if st.button("Сводка по зарплате", key="payroll_summary_btn", width="stretch"):
            st.session_state.payroll_section = "Сводка"
            st.rerun()

    st.markdown("---")

    # --------------------------------------------------------
    # Двойной отбор: сначала заказчик, затем его объект.
    # Никакой общей таблицы по всем объектам здесь нет.
    # --------------------------------------------------------
    customers = run_query(
        """
        SELECT DISTINCT c.id, c.name
        FROM reklet.clients c
        JOIN reklet.objects o ON o.client_id = c.id
        JOIN reklet.object_items oi ON oi.object_id = o.id
        ORDER BY c.name
        """,
        fetch=True
    )

    section_key = st.session_state.payroll_section

    if customers.empty:
        st.info("Нет объектов с изделиями для расчёта зарплаты.")
        st.stop()

    customer_options = [f"{int(row['id'])} — {row['name']}" for _, row in customers.iterrows()]
    selected_customer = st.selectbox(
        "Заказчик",
        customer_options,
        key=f"payroll_customer_filter_{section_key}"
    )
    selected_customer_id = int(selected_customer.split(" — ")[0])

    objects_for_customer = run_query(
        """
        SELECT DISTINCT o.id, o.object_name
        FROM reklet.objects o
        JOIN reklet.object_items oi ON oi.object_id = o.id
        WHERE o.client_id = %s
        ORDER BY o.object_name
        """,
        (selected_customer_id,),
        fetch=True
    )

    if objects_for_customer.empty:
        st.info("У выбранного заказчика нет объектов с изделиями.")
        st.stop()

    object_options = [
        f"{int(row['id'])} — {row['object_name']}"
        for _, row in objects_for_customer.iterrows()
    ]
    selected_object = st.selectbox(
        "Объект",
        object_options,
        key=f"payroll_object_filter_{section_key}_{selected_customer_id}"
    )
    selected_object_id = int(selected_object.split(" — ")[0])

    st.markdown("---")

    # Данные только выбранного объекта.
    ensure_object_item_material_costs(selected_object_id)
    payroll_items = run_query(
        """
        SELECT
            oi.id AS object_item_id,
            oi.object_id,
            o.object_name,
            COALESCE(c.name, '') AS client_name,
            oi.item_name,
            COALESCE(oi.quantity_needed, 0) AS quantity_needed,
            COALESCE(o.transport_distance_km, 0) AS distance_km,
            COALESCE(SUM(
                COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit) *
                COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1) *
                COALESCE(oimc.unit_cost, m.cost_per_unit, 0)
            ), 0) AS material_cost_per_unit
        FROM reklet.object_items oi
        JOIN reklet.objects o ON o.id = oi.object_id
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        LEFT JOIN reklet.product_templates pt
            ON pt.id = COALESCE(oi.product_template_id, oi.template_id)
        LEFT JOIN reklet.product_template_materials ptm
            ON ptm.product_template_id = pt.id
        LEFT JOIN reklet.materials m
            ON m.id = ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc
            ON oimc.object_item_id = oi.id
           AND oimc.material_id = ptm.material_id
        WHERE oi.object_id = %s
        GROUP BY
            oi.id, oi.object_id, o.object_name, c.name, oi.item_name,
            oi.quantity_needed, o.transport_distance_km
        ORDER BY oi.id
        """,
        (selected_object_id,),
        fetch=True
    )

    if payroll_items.empty:
        st.info("В выбранном объекте нет изделий для расчёта зарплаты.")
        st.stop()

    numeric_cols = ["material_cost_per_unit", "distance_km", "quantity_needed"]
    for col in numeric_cols:
        payroll_items[col] = pd.to_numeric(
            payroll_items[col], errors="coerce"
        ).fillna(0.0)

    if st.session_state.payroll_section == "Производство":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = view["material_cost_per_unit"]
        view["Количество"] = view["quantity_needed"]
        view["Зарплата производства"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
        )
        view = view.rename(columns={
            "object_name": "Объект",
            "client_name": "Заказчик",
            "item_name": "Изделие"
        })
        st.caption(
            "Зарплата производства рассчитывается сразу на всё количество изделий, "
            "указанное в объекте: себестоимость материалов × количество изделий × 1,50 (+50%)."
        )
        payroll_production_view = view[[
            "Изделие", "Себестоимость материалов", "Количество",
            "Зарплата производства"
        ]].copy()
        st.dataframe(payroll_production_view, width="stretch", hide_index=True)
        render_print_html(
            f"Зарплата производства — {selected_object}",
            payroll_production_view,
            f"print_payroll_production_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]}"
        )

    elif st.session_state.payroll_section == "Монтаж":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = view["material_cost_per_unit"]
        view["Количество"] = view["quantity_needed"]
        view["Зарплата монтажа"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
        )
        view = view.rename(columns={
            "object_name": "Объект",
            "client_name": "Заказчик",
            "item_name": "Изделие"
        })
        st.caption(
            "Зарплата монтажа рассчитывается сразу на всё количество изделий, "
            "указанное в объекте: себестоимость материалов × количество изделий × 1,40 (+40%)."
        )
        payroll_installation_view = view[[
            "Изделие", "Себестоимость материалов", "Количество",
            "Зарплата монтажа"
        ]].copy()
        st.dataframe(payroll_installation_view, width="stretch", hide_index=True)
        render_print_html(
            f"Зарплата монтажа — {selected_object}",
            payroll_installation_view,
            f"print_payroll_installation_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]}"
        )

    elif st.session_state.payroll_section == "Транспортировка":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = (
            view["material_cost_per_unit"] * view["quantity_needed"]
        )
        view["Количество"] = view["quantity_needed"]
        view["Зарплата 10%"] = view["Себестоимость материалов"] * 0.10

        st.caption(
            "Транспортировка = 10% от себестоимости материалов всех изделий объекта "
            "+ расстояние до объекта × 2. Расстояние оплачивается только один раз на объект."
        )
        payroll_transport_view = view[[
            "item_name", "Себестоимость материалов", "Количество", "Зарплата 10%"
        ]].rename(columns={"item_name": "Изделие"})
        st.dataframe(payroll_transport_view, width="stretch", hide_index=True)

        total_material_cost = float(view["Себестоимость материалов"].sum())
        salary_10 = total_material_cost * 0.10
        distance_km = float(payroll_items["distance_km"].iloc[0]) if not payroll_items.empty else 0.0
        distance_salary = distance_km * 2
        transport_total = salary_10 + distance_salary

        summary = pd.DataFrame([{
            "Себестоимость материалов всего": total_material_cost,
            "Зарплата 10%": salary_10,
            "Расстояние, км": distance_km,
            "Расстояние × 2": distance_salary,
            "Итого зарплата транспортировки": transport_total
        }])
        st.subheader("Итого по выбранному объекту")
        st.dataframe(summary, width="stretch", hide_index=True)
        render_print_html(
            f"Зарплата транспортировки — {selected_object}",
            payroll_transport_view,
            f"print_payroll_transport_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]} | Расстояние × 2 считается один раз на объект"
        )
        render_print_html(
            f"Итого зарплата транспортировки — {selected_object}",
            summary,
            f"print_payroll_transport_total_{selected_object_id}"
        )

    else:
        view = payroll_items.copy()
        view["Производство"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
        )
        view["Монтаж"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
        )
        view["Доставка 10%"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 0.10
        )

        payroll_summary_items = view[["item_name", "Производство", "Монтаж", "Доставка 10%"]].rename(
            columns={"item_name": "Изделие"}
        )
        st.dataframe(payroll_summary_items, width="stretch", hide_index=True)

        total_production = float(view["Производство"].sum())
        total_installation = float(view["Монтаж"].sum())
        total_delivery_10 = float(view["Доставка 10%"].sum())
        distance_km = float(payroll_items["distance_km"].iloc[0]) if not payroll_items.empty else 0.0
        distance_salary = distance_km * 2
        total_delivery = total_delivery_10 + distance_salary
        total_salary = total_production + total_installation + total_delivery

        summary = pd.DataFrame([{
            "Производство": total_production,
            "Монтаж": total_installation,
            "Доставка 10%": total_delivery_10,
            "Расстояние, км": distance_km,
            "Расстояние × 2": distance_salary,
            "Доставка": total_delivery,
            "Итого": total_salary
        }])
        st.subheader("Итого по выбранному объекту")
        st.dataframe(summary, width="stretch", hide_index=True)
        render_print_html(
            f"Сводка по зарплате — {selected_object}",
            payroll_summary_items,
            f"print_payroll_summary_items_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]}"
        )
        render_print_html(
            f"Итого зарплата — {selected_object}",
            summary,
            f"print_payroll_summary_total_{selected_object_id}"
        )

    st.caption(
        "Количество берётся из object_items.quantity_needed — это плановая зарплата "
        "за всё количество изделий объекта, независимо от фактически выполненных работ."
    )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    ensure_material_planning_tables()
    st.header("Отчёты")

    # ========================================================
    # REPORT BUTTONS
    # ========================================================
    if "reports_section" not in st.session_state:
        st.session_state["reports_section"] = "Сводные таблицы"

    rb1, rb2, rb3, rb4, rb5 = st.columns(5)

    with rb1:
        if st.button("Сводные таблицы", key="reports_summary_btn", use_container_width=True):
            st.session_state["reports_section"] = "Сводные таблицы"
            st.rerun()
    with rb2:
        if st.button("Печать документов", key="reports_print_btn", use_container_width=True):
            st.session_state["reports_section"] = "Печать документов"
            st.rerun()
    with rb3:
        if st.button("Операционные отчёты", key="reports_operational_btn", use_container_width=True):
            st.session_state["reports_section"] = "Операционные отчёты"
            st.rerun()
    with rb4:
        if st.button("Складские отчёты", key="reports_stock_btn", use_container_width=True):
            st.session_state["reports_section"] = "Складские отчёты"
            st.rerun()
    with rb5:
        if st.button("Все движения", key="reports_movements_btn", use_container_width=True):
            st.session_state["reports_section"] = "Все движения"
            st.rerun()

    st.markdown("---")

    # ========================================================
    # COMMON COST DATA
    # ========================================================
    report_q = """
    SELECT
        o.id AS object_id,
        o.object_name,
        c.name AS client_name,
        o.address,
        COALESCE(o.transport_distance_km, 0) AS distance_km,
        oi.id AS object_item_id,
        oi.item_name,
        COALESCE(oi.quantity_needed, 0) AS quantity_needed,
        COALESCE(oi.qty_installed, 0) AS qty_installed,
        (
            COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_arrived,
        (
            COALESCE(oi.qty_shipped, 0)
            + COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_shipped,
        COALESCE(oi.qty_ready, 0) AS qty_ready,
        COALESCE(SUM(
            COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)
            * COALESCE(oimc.unit_cost, m.cost_per_unit, 0)
            * COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1)
        ), 0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id = oi.object_id
    LEFT JOIN reklet.clients c ON c.id = o.client_id
    LEFT JOIN reklet.product_template_materials ptm
        ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
    LEFT JOIN reklet.materials m ON m.id = ptm.material_id
    LEFT JOIN reklet.object_item_material_costs oimc
        ON oimc.object_item_id = oi.id
       AND oimc.material_id = ptm.material_id
    GROUP BY
        o.id, o.object_name, c.name, o.address,
        o.transport_distance_km,
        oi.id, oi.item_name, oi.quantity_needed,
        oi.qty_installed, oi.qty_arrived, oi.qty_installing, oi.qty_shipped, oi.qty_ready
    ORDER BY o.object_name, oi.item_name
    """

    report_df = run_query(report_q, fetch=True)

    if not report_df.empty:
        numeric_cols = [
            "quantity_needed", "qty_installed", "qty_arrived",
            "qty_shipped", "qty_ready", "material_unit_cost", "distance_km"
        ]
        for col in numeric_cols:
            report_df[col] = pd.to_numeric(report_df[col], errors="coerce").fillna(0.0)

        report_df["Материалы"] = report_df["material_unit_cost"] * report_df["quantity_needed"]
        report_df["Производство"] = report_df["Материалы"] * 0.50
        report_df["Монтаж"] = report_df["Материалы"] * 0.40
        report_df["Доставка"] = report_df["Материалы"] * 0.10 + report_df["distance_km"] * 2
        report_df["Себестоимость"] = report_df["Материалы"] + report_df["Производство"] + report_df["Монтаж"] + report_df["Доставка"]
        report_df["Цена объекта"] = report_df["Себестоимость"] * 2
        report_df["Остаток"] = (report_df["quantity_needed"] - report_df["qty_installed"]).clip(lower=0)

    # ========================================================
    # 1. SUMMARY TABLES
    # ========================================================
    if st.session_state["reports_section"] == "Сводные таблицы":

        st.subheader("По заказчикам")

        if report_df.empty:
            st.info("Нет данных для сводной таблицы.")
        else:
            client_summary = report_df.groupby(
                ["client_name"], dropna=False
            ).agg(
                Объектов=("object_id", "nunique"),
                Изделий=("quantity_needed", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
                Выполнено=("qty_installed", "sum"),
            ).reset_index()
            client_summary = client_summary.rename(columns={"client_name": "Заказчик"})
            st.dataframe(client_summary, width="stretch", hide_index=True)
            render_print_html("Сводка по заказчикам", client_summary, "print_report_clients")

        st.subheader("По объектам")

        if not report_df.empty:
            object_summary = report_df.groupby(
                ["object_id", "object_name", "client_name", "address"], dropna=False
            ).agg(
                Изделий=("quantity_needed", "sum"),
                Выполнено=("qty_installed", "sum"),
                Остаток=("Остаток", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
            ).reset_index()
            object_summary.columns = [
                "№", "Объект", "Заказчик", "Адрес", "Изделий", "Выполнено",
                "Остаток", "Материалы", "Производство", "Монтаж", "Доставка",
                "Себестоимость", "Стоимость объекта"
            ]
            st.dataframe(object_summary, width="stretch", hide_index=True)
            render_print_html("Сводка по объектам", object_summary, "print_report_objects")

        st.subheader("Общие показатели")
        if not report_df.empty:
            totals = pd.DataFrame([{
                "Показатель": "Все объекты",
                "Объектов": report_df["object_id"].nunique(),
                "Изделий заказано": report_df["quantity_needed"].sum(),
                "Изделий установлено": report_df["qty_installed"].sum(),
                "Материалы": report_df["Материалы"].sum(),
                "Зарплата производства": report_df["Производство"].sum(),
                "Зарплата монтажа": report_df["Монтаж"].sum(),
                "Доставка": report_df["Доставка"].sum(),
                "Себестоимость": report_df["Себестоимость"].sum(),
                "Цена с наценкой 100%": report_df["Цена объекта"].sum(),
            }])
            st.dataframe(totals, width="stretch", hide_index=True)
            render_print_html("Общие показатели", totals, "print_report_totals")

    # ========================================================
    # 2. ALL MOVEMENTS
    # ========================================================
    elif st.session_state["reports_section"] == "Все движения":

        st.subheader("Все движения")
        st.caption("Одна строка = одна транзакция в базе данных. Фильтры можно комбинировать.")

        movements_q = """
            SELECT * FROM (
                SELECT
                    pt.created_at AS tx_date,
                    'Производство'::text AS section_name,
                    CASE pt.operation_type
                        WHEN 'completed' THEN 'Изготовлено'
                        ELSE pt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    pt.quantity::numeric AS quantity
                FROM reklet.production_transactions pt
                LEFT JOIN reklet.objects o ON o.id = pt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = pt.object_item_id

                UNION ALL

                SELECT
                    fgt.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    CASE fgt.operation_type
                        WHEN 'ready' THEN 'Поступило на склад'
                        WHEN 'ship' THEN 'Отгружено'
                        WHEN 'arrive' THEN 'Доставлено на объект'
                        ELSE fgt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    fgt.quantity::numeric AS quantity
                FROM reklet.finished_goods_transactions fgt
                LEFT JOIN reklet.objects o ON o.id = fgt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = fgt.object_item_id

                UNION ALL

                SELECT
                    mt.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    CASE mt.operation_type
                        WHEN 'purchase' THEN 'Приход материала'
                        WHEN 'production_transfer' THEN 'Выдано в производство'
                        ELSE mt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    NULL::text AS product_name,
                    m.name AS material_name,
                    s.name AS supplier_name,
                    mt.quantity::numeric AS quantity
                FROM reklet.material_transactions mt
                LEFT JOIN reklet.materials m ON m.id = mt.material_id
                LEFT JOIN reklet.suppliers s ON s.id = mt.supplier_id
                LEFT JOIN reklet.objects o ON o.id = mt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id

                UNION ALL

                SELECT
                    mc.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    'Списано при производстве'::text AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    m.name AS material_name,
                    NULL::text AS supplier_name,
                    mc.quantity::numeric AS quantity
                FROM reklet.material_consumption mc
                LEFT JOIN reklet.objects o ON o.id=mc.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id=mc.object_item_id
                LEFT JOIN reklet.materials m ON m.id=mc.material_id

                UNION ALL

                SELECT
                    tt.created_at AS tx_date,
                    'Транспортировка'::text AS section_name,
                    CASE tt.operation_type
                        WHEN 'ship' THEN 'Отправлено'
                        WHEN 'arrive' THEN 'Доставлено'
                        ELSE tt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    tt.quantity::numeric AS quantity
                FROM reklet.transport_transactions tt
                LEFT JOIN reklet.objects o ON o.id = tt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = tt.object_item_id

                UNION ALL

                SELECT
                    it.created_at AS tx_date,
                    'Монтаж'::text AS section_name,
                    CASE it.operation_type
                        WHEN 'complete' THEN 'Установлено'
                        ELSE it.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    it.quantity::numeric AS quantity
                FROM reklet.installation_transactions it
                LEFT JOIN reklet.objects o ON o.id = it.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = it.object_item_id
            ) movements
            ORDER BY tx_date DESC
        """

        movements = run_query(movements_q, fetch=True)

        if movements.empty:
            st.info("Транзакций в базе данных пока нет.")
        else:
            f1, f2, f3 = st.columns(3)
            f4, f5, f6 = st.columns(3)

            with f1:
                movement_client = st.selectbox(
                    "Заказчик", movement_options(movements, "client_name"), key="movement_filter_client"
                )
            with f2:
                movement_object = st.selectbox(
                    "Объект", movement_options(movements, "object_name"), key="movement_filter_object"
                )
            with f3:
                movement_section = st.selectbox(
                    "Раздел",
                    ["Все", "Производство", "Склад", "Транспортировка", "Монтаж"],
                    key="movement_filter_section"
                )
            with f4:
                movement_supplier = st.selectbox(
                    "Поставщик", movement_options(movements, "supplier_name"), key="movement_filter_supplier"
                )
            with f5:
                movement_material = st.selectbox(
                    "Материал", movement_options(movements, "material_name"), key="movement_filter_material"
                )
            with f6:
                movement_product = st.selectbox(
                    "Изделие", movement_options(movements, "product_name"), key="movement_filter_product"
                )

            filtered = movements.copy()

            if movement_client != "Все":
                filtered = filtered[filtered["client_name"].fillna("").astype(str) == movement_client]
            if movement_object != "Все":
                filtered = filtered[filtered["object_name"].fillna("").astype(str) == movement_object]
            if movement_section != "Все":
                filtered = filtered[filtered["section_name"] == movement_section]
            if movement_supplier != "Все":
                filtered = filtered[filtered["supplier_name"].fillna("").astype(str) == movement_supplier]
            if movement_material != "Все":
                filtered = filtered[filtered["material_name"].fillna("").astype(str) == movement_material]
            if movement_product != "Все":
                filtered = filtered[filtered["product_name"].fillna("").astype(str) == movement_product]

            view = filtered.rename(columns={
                "tx_date": "Дата",
                "section_name": "Раздел",
                "operation_name": "Действие",
                "client_name": "Заказчик",
                "object_name": "Объект",
                "product_name": "Изделие",
                "material_name": "Материал",
                "supplier_name": "Поставщик",
                "quantity": "Количество",
            })[[
                "Дата", "Раздел", "Действие", "Заказчик", "Объект",
                "Изделие", "Материал", "Поставщик", "Количество"
            ]]

            st.dataframe(view, width="stretch", hide_index=True)
            st.caption(f"Показано транзакций: {len(view)} из {len(movements)}")
            render_print_html("Все движения", view, "print_all_movements")

    # ========================================================
    # 3. PRINT DOCUMENTS
    # ========================================================
    elif st.session_state["reports_section"] == "Печать документов":

        st.subheader("Готовые документы")

        document_type = st.selectbox(
            "Документ",
            [
                "Выверка по объекту",
                "Выверка по заказчику",
                "Смета объекта",
                "Акт сдачи-приёмки работ",
                "Приходная накладная",
                "Расходная накладная",
            ],
            key="print_document_type"
        )

        # ---------- Reusable printable HTML ----------
        def printable_html(title, body_html):
            return f"""
            <!doctype html>
            <html><head><meta charset='utf-8'>
            <title>{escape(title)}</title>
            <style>
            body {{ font-family: Arial, sans-serif; margin: 35px; color: #111; }}
            h1 {{ font-size: 22px; margin-bottom: 8px; }}
            h2 {{ font-size: 17px; margin-top: 22px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #777; padding: 6px 8px; text-align: left; }}
            th {{ background: #eee; }}
            .right {{ text-align: right; }}
            .sign {{ margin-top: 45px; display: flex; justify-content: space-between; }}
            </style></head><body>
            <h1>{escape(title)}</h1>
            {body_html}
            </body></html>
            """

        if document_type in ["Выверка по объекту", "Смета объекта", "Акт сдачи-приёмки работ"]:
            if report_df.empty:
                st.info("Нет объектов для формирования документа.")
            else:
                object_options = [
                    f"{int(r['object_id'])} — {r['object_name']}"
                    for _, r in report_df[["object_id", "object_name"]].drop_duplicates().iterrows()
                ]
                selected_object = st.selectbox("Объект", object_options, key="print_object")
                selected_object_id = int(selected_object.split(" — ")[0])
                doc = report_df[report_df["object_id"] == selected_object_id].copy()

                object_name = str(doc.iloc[0]["object_name"])
                client_name = str(doc.iloc[0]["client_name"] or "")
                address = str(doc.iloc[0]["address"] or "")

                if document_type == "Выверка по объекту":
                    view = doc[["item_name", "quantity_needed", "qty_ready", "qty_shipped", "qty_arrived", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Готово", "Отправлено", "Доставлено", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                    title = f"Выверка по объекту — {object_name}"

                elif document_type == "Смета объекта":
                    estimate = doc.groupby("item_name", as_index=False).agg(
                        Количество=("quantity_needed", "sum"),
                        Материалы=("Материалы", "sum"),
                        Производство=("Производство", "sum"),
                        Монтаж=("Монтаж", "sum"),
                        Доставка=("Доставка", "sum"),
                        Себестоимость=("Себестоимость", "sum"),
                        Стоимость=("Цена объекта", "sum"),
                    )
                    st.dataframe(estimate, width="stretch", hide_index=True)
                    totals = estimate[["Материалы", "Производство", "Монтаж", "Доставка", "Себестоимость", "Стоимость"]].sum()
                    st.write(f"**Итого материалов:** {money(totals['Материалы'])}")
                    st.write(f"**Итого себестоимость:** {money(totals['Себестоимость'])}")
                    st.write(f"**Итоговая стоимость с наценкой 100%:** {money(totals['Стоимость'])}")
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += estimate.to_html(index=False)
                    body += f"<h2>Итого</h2><p>Материалы: {money(totals['Материалы'])}<br>Производство: {money(totals['Производство'])}<br>Монтаж: {money(totals['Монтаж'])}<br>Доставка: {money(totals['Доставка'])}<br>Себестоимость: {money(totals['Себестоимость'])}<br><b>Итоговая стоимость: {money(totals['Стоимость'])}</b></p>"
                    body += "<div class='sign'><span>Согласовано: __________________</span><span>Дата: __________________</span></div>"
                    title = f"Смета объекта — {object_name}"

                else:
                    planned = float(doc["quantity_needed"].sum())
                    completed = float(doc["qty_installed"].sum())
                    remaining = max(planned - completed, 0)
                    intermediate = remaining > 0
                    act_title = "Промежуточный акт сдачи-приёмки работ" if intermediate else "Акт сдачи-приёмки работ"
                    st.subheader(act_title)
                    st.write(f"Запланировано: **{planned:g} шт.**")
                    st.write(f"Выполнено: **{completed:g} шт.**")
                    st.write(f"Остаток: **{remaining:g} шт.**")
                    view = doc[["item_name", "quantity_needed", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<h2>{escape(act_title)}</h2><p><b>Объект:</b> {escape(object_name)}<br><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += f"<p><b>Запланировано:</b> {planned:g} шт.<br><b>Выполнено:</b> {completed:g} шт.<br><b>Остаток:</b> {remaining:g} шт.</p>"
                    body += "<div class='sign'><span>Заказчик: __________________</span><span>Исполнитель: __________________</span></div>"
                    title = f"{act_title} — {object_name}"

                st.download_button(
                    "Печать HTML",
                    data=printable_html(title, body),
                    file_name=title.replace(" ", "_") + ".html",
                    mime="text/html",
                    key="download_object_document"
                )
                st.caption("HTML-документ можно открыть в браузере и распечатать или сохранить в PDF через печать браузера.")

        elif document_type == "Выверка по заказчику":
            clients = report_df["client_name"].fillna("").astype(str).drop_duplicates().sort_values().tolist()
            if not clients:
                st.info("Нет заказчиков.")
            else:
                selected_client = st.selectbox("Заказчик", clients, key="print_client")
                doc = report_df[report_df["client_name"].fillna("").astype(str) == selected_client].copy()
                summary = doc.groupby(["object_id", "object_name"], as_index=False).agg(
                    Изделий=("quantity_needed", "sum"),
                    Выполнено=("qty_installed", "sum"),
                    Материалы=("Материалы", "sum"),
                    Производство=("Производство", "sum"),
                    Монтаж=("Монтаж", "sum"),
                    Доставка=("Доставка", "sum"),
                    Себестоимость=("Себестоимость", "sum"),
                    Стоимость=("Цена объекта", "sum"),
                )
                st.dataframe(summary, width="stretch", hide_index=True)
                body = f"<p><b>Заказчик:</b> {escape(selected_client)}</p>" + summary.to_html(index=False)
                body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                title = f"Выверка по заказчику — {selected_client}"
                st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_client_document")

        elif document_type in ["Приходная накладная", "Расходная накладная"]:
            if document_type == "Приходная накладная":
                suppliers_for_print = run_query(
                    "SELECT id, name FROM reklet.suppliers ORDER BY name",
                    fetch=True
                )
                supplier_options = ["Все поставщики"] + (
                    suppliers_for_print["name"].fillna("").astype(str).tolist()
                    if not suppliers_for_print.empty else []
                )
                selected_supplier = st.selectbox("Поставщик", supplier_options, key="print_receipt_supplier")
                invoice_q = """
                    SELECT mt.created_at AS "Дата", s.name AS "Поставщик", m.name AS "Материал",
                           u.name AS "Единица", mt.quantity AS "Количество",
                           mt.unit_price AS "Цена",
                           (mt.quantity * COALESCE(mt.unit_price,0)) AS "Сумма"
                    FROM reklet.material_transactions mt
                    LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id
                    JOIN reklet.materials m ON m.id=mt.material_id
                    LEFT JOIN reklet.units u ON u.id=m.unit_id
                    WHERE mt.operation_type='purchase' AND mt.transaction_type='IN'
                """
                params=[]
                if selected_supplier != "Все поставщики":
                    invoice_q += " AND s.name=%s"
                    params.append(selected_supplier)
                invoice_q += " ORDER BY mt.created_at DESC LIMIT 500"
                invoice_df = run_query(invoice_q, tuple(params), fetch=True)
                if invoice_df.empty:
                    st.info("Приходных движений нет.")
                else:
                    st.dataframe(invoice_df, width="stretch", hide_index=True)
                    body = invoice_df.to_html(index=False)
                    title = "Приходная накладная" if selected_supplier == "Все поставщики" else f"Приходная накладная — {selected_supplier}"
                    st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_purchase_invoice")

            else:
                objects_for_print = run_query(
                    "SELECT id, object_name FROM reklet.objects ORDER BY object_name",
                    fetch=True
                )
                object_options = ["Все объекты"] + (
                    [f"{int(r['id'])} — {r['object_name']}" for _, r in objects_for_print.iterrows()]
                    if not objects_for_print.empty else []
                )
                selected_issue_object = st.selectbox("Объект", object_options, key="print_issue_object")
                issue_q = """
                    SELECT mt.created_at AS "Дата", o.object_name AS "Объект", c.name AS "Заказчик",
                           m.name AS "Материал", u.name AS "Единица", mt.quantity AS "Количество",
                           mt.unit_price AS "Цена",
                           (mt.quantity * COALESCE(mt.unit_price,0)) AS "Сумма"
                    FROM reklet.material_transactions mt
                    JOIN reklet.materials m ON m.id=mt.material_id
                    LEFT JOIN reklet.units u ON u.id=m.unit_id
                    LEFT JOIN reklet.objects o ON o.id=mt.object_id
                    LEFT JOIN reklet.clients c ON c.id=o.client_id
                    WHERE mt.operation_type='production_transfer' AND mt.transaction_type='OUT'
                """
                params=[]
                if selected_issue_object != "Все объекты":
                    issue_q += " AND o.id=%s"
                    params.append(int(selected_issue_object.split(" — ")[0]))
                issue_q += " ORDER BY mt.created_at DESC LIMIT 500"
                invoice_df = run_query(issue_q, tuple(params), fetch=True)
                if invoice_df.empty:
                    st.info("Расходных движений нет.")
                else:
                    st.dataframe(invoice_df, width="stretch", hide_index=True)
                    body = invoice_df.to_html(index=False)
                    title = "Расходная накладная" if selected_issue_object == "Все объекты" else f"Расходная накладная — {selected_issue_object}"
                    st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_issue_invoice")

    # ========================================================
    # 3. OPERATIONAL REPORTS
    # ========================================================
    elif st.session_state["reports_section"] == "Операционные отчёты":
        st.subheader("Операционные отчёты")
        operational = st.selectbox(
            "Отчёт",
            [
                "Карточка объекта",
                "Отчёт по производству",
                "Готово, но не отправлено",
                "Отчёт по доставкам",
                "Отчёт по монтажу",
                "Незавершённые объекты",
            ],
            key="operational_report"
        )

        if report_df.empty:
            st.info("Нет данных.")
        elif operational == "Карточка объекта":
            options = [f"{int(r['object_id'])} — {r['object_name']}" for _, r in report_df[["object_id","object_name"]].drop_duplicates().iterrows()]
            selected = st.selectbox("Объект", options, key="operational_object")
            oid = int(selected.split(" — ")[0])
            card = report_df[report_df["object_id"] == oid]
            operational_view = card[["item_name","quantity_needed","qty_installed","qty_ready","qty_shipped","qty_arrived"]].rename(columns={"item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено","qty_ready":"Готово","qty_shipped":"Отправлено","qty_arrived":"Доставлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html(f"Карточка объекта — {selected}", operational_view, "print_operational_card")
        elif operational == "Отчёт по производству":
            operational_view = report_df.groupby(["object_name","client_name"], as_index=False).agg(Заказано=("quantity_needed", "sum"), Готово=("qty_ready", "sum"), Доставлено=("qty_arrived", "sum"), Установлено=("qty_installed", "sum"))
            operational_view = operational_view.rename(columns={"object_name":"Объект","client_name":"Заказчик"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по производству", operational_view, "print_operational_production")
        elif operational == "Готово, но не отправлено":
            operational_view = report_df[report_df["qty_ready"] > report_df["qty_shipped"]][["object_name","client_name","item_name","qty_ready","qty_shipped"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_ready":"Готово","qty_shipped":"Отправлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Готово, но не отправлено", operational_view, "print_operational_ready")
        elif operational == "Отчёт по доставкам":
            operational_view = report_df[["object_name","client_name","item_name","qty_shipped","qty_arrived"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_shipped":"Отправлено","qty_arrived":"Доставлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по доставкам", operational_view, "print_operational_deliveries")
        elif operational == "Отчёт по монтажу":
            operational_view = report_df[["object_name","client_name","item_name","quantity_needed","qty_installed"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по монтажу", operational_view, "print_operational_installation")
        else:
            incomplete = report_df[report_df["qty_installed"] < report_df["quantity_needed"]]
            operational_view = incomplete.groupby(["object_id","object_name","client_name"], as_index=False).agg(Запланировано=("quantity_needed","sum"), Выполнено=("qty_installed","sum"), Остаток=("Остаток","sum"))
            operational_view = operational_view.rename(columns={"object_id":"№","object_name":"Объект","client_name":"Заказчик"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Незавершённые объекты", operational_view, "print_operational_incomplete")

    # ========================================================
    # 4. STOCK REPORTS
    # ========================================================
    else:
        st.subheader("Складские отчёты")
        stock_report = st.selectbox(
            "Отчёт",
            ["Остатки материалов", "Материалы с низким остатком", "Потребность материалов по незавершённым объектам"],
            key="stock_report"
        )
        stock = run_query("""
            SELECT m.id, m.name AS material, u.name AS unit,
                   COALESCE(m.stock_quantity,0) AS stock_quantity,
                   COALESCE(m.cost_per_unit,0) AS cost_per_unit,
                   COALESCE(m.stock_quantity,0)*COALESCE(m.cost_per_unit,0) AS stock_value
            FROM reklet.materials m
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            ORDER BY m.name
        """, fetch=True)
        if stock_report == "Остатки материалов":
            stock_view = stock.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"})
            st.dataframe(stock_view, width="stretch", hide_index=True)
            render_print_html("Остатки материалов", stock_view, "print_stock_balances")
        elif stock_report == "Материалы с низким остатком":
            low = stock[stock["stock_quantity"] <= 10].copy()
            st.dataframe(low.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        else:
            need = run_query("""
                SELECT o.object_name, c.name AS client_name, oi.item_name,
                       m.name AS material,
                       (oi.quantity_needed
                         * COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)
                         * COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS required_quantity,
                       COALESCE(m.stock_quantity,0) AS stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
                JOIN reklet.materials m ON m.id=ptm.material_id
                LEFT JOIN reklet.object_item_material_costs oimc
                  ON oimc.object_item_id=oi.id
                 AND oimc.material_id=ptm.material_id
                WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                ORDER BY o.object_name, oi.item_name, m.name
            """, fetch=True)
            stock_need_view = need.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","material":"Материал","required_quantity":"Требуется","stock_quantity":"На складе"})
            st.dataframe(stock_need_view, width="stretch", hide_index=True)
            render_print_html("Потребность материалов по незавершённым объектам", stock_need_view, "print_stock_object_need")




# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    ensure_material_planning_tables()
    st.header("Отчёты")

    # ========================================================
    # REPORT BUTTONS
    # ========================================================
    if "reports_section" not in st.session_state:
        st.session_state["reports_section"] = "Сводные таблицы"

    rb1, rb2 = st.columns(2)
    rb3, rb4 = st.columns(2)

    with rb1:
        if st.button("Сводные таблицы", key="reports_summary_btn", use_container_width=True):
            st.session_state["reports_section"] = "Сводные таблицы"
            st.rerun()
    with rb2:
        if st.button("Печать документов", key="reports_print_btn", use_container_width=True):
            st.session_state["reports_section"] = "Печать документов"
            st.rerun()
    with rb3:
        if st.button("Операционные отчёты", key="reports_operational_btn", use_container_width=True):
            st.session_state["reports_section"] = "Операционные отчёты"
            st.rerun()
    with rb4:
        if st.button("Складские отчёты", key="reports_stock_btn", use_container_width=True):
            st.session_state["reports_section"] = "Складские отчёты"
            st.rerun()

    st.markdown("---")

    # ========================================================
    # COMMON COST DATA
    # ========================================================
    report_q = """
    SELECT
        o.id AS object_id,
        o.object_name,
        c.name AS client_name,
        o.address,
        COALESCE(o.transport_distance_km, 0) AS distance_km,
        oi.id AS object_item_id,
        oi.item_name,
        COALESCE(oi.quantity_needed, 0) AS quantity_needed,
        COALESCE(oi.qty_installed, 0) AS qty_installed,
        (
            COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_arrived,
        (
            COALESCE(oi.qty_shipped, 0)
            + COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_shipped,
        COALESCE(oi.qty_ready, 0) AS qty_ready,
        COALESCE(SUM(
            COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)
            * COALESCE(oimc.unit_cost, m.cost_per_unit, 0)
            * COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1)
        ), 0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id = oi.object_id
    LEFT JOIN reklet.clients c ON c.id = o.client_id
    LEFT JOIN reklet.product_template_materials ptm
        ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
    LEFT JOIN reklet.materials m ON m.id = ptm.material_id
    LEFT JOIN reklet.object_item_material_costs oimc
        ON oimc.object_item_id = oi.id
       AND oimc.material_id = ptm.material_id
    GROUP BY
        o.id, o.object_name, c.name, o.address,
        o.transport_distance_km,
        oi.id, oi.item_name, oi.quantity_needed,
        oi.qty_installed, oi.qty_arrived, oi.qty_installing, oi.qty_shipped, oi.qty_ready
    ORDER BY o.object_name, oi.item_name
    """

    report_df = run_query(report_q, fetch=True)

    if not report_df.empty:
        numeric_cols = [
            "quantity_needed", "qty_installed", "qty_arrived",
            "qty_shipped", "qty_ready", "material_unit_cost", "distance_km"
        ]
        for col in numeric_cols:
            report_df[col] = pd.to_numeric(report_df[col], errors="coerce").fillna(0.0)

        report_df["Материалы"] = report_df["material_unit_cost"] * report_df["quantity_needed"]
        report_df["Производство"] = report_df["Материалы"] * 0.50
        report_df["Монтаж"] = report_df["Материалы"] * 0.40
        report_df["Доставка"] = report_df["Материалы"] * 0.10 + report_df["distance_km"] * 2
        report_df["Себестоимость"] = report_df["Материалы"] + report_df["Производство"] + report_df["Монтаж"] + report_df["Доставка"]
        report_df["Цена объекта"] = report_df["Себестоимость"] * 2
        report_df["Остаток"] = (report_df["quantity_needed"] - report_df["qty_installed"]).clip(lower=0)

    # ========================================================
    # 1. SUMMARY TABLES
    # ========================================================
    if st.session_state["reports_section"] == "Сводные таблицы":

        st.subheader("По заказчикам")

        if report_df.empty:
            st.info("Нет данных для сводной таблицы.")
        else:
            client_summary = report_df.groupby(
                ["client_name"], dropna=False
            ).agg(
                Объектов=("object_id", "nunique"),
                Изделий=("quantity_needed", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
                Выполнено=("qty_installed", "sum"),
            ).reset_index()
            client_summary = client_summary.rename(columns={"client_name": "Заказчик"})
            st.dataframe(client_summary, width="stretch", hide_index=True)

        st.subheader("По объектам")

        if not report_df.empty:
            object_summary = report_df.groupby(
                ["object_id", "object_name", "client_name", "address"], dropna=False
            ).agg(
                Изделий=("quantity_needed", "sum"),
                Выполнено=("qty_installed", "sum"),
                Остаток=("Остаток", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
            ).reset_index()
            object_summary.columns = [
                "№", "Объект", "Заказчик", "Адрес", "Изделий", "Выполнено",
                "Остаток", "Материалы", "Производство", "Монтаж", "Доставка",
                "Себестоимость", "Стоимость объекта"
            ]
            st.dataframe(object_summary, width="stretch", hide_index=True)

        st.subheader("Общие показатели")
        if not report_df.empty:
            totals = pd.DataFrame([{
                "Показатель": "Все объекты",
                "Объектов": report_df["object_id"].nunique(),
                "Изделий заказано": report_df["quantity_needed"].sum(),
                "Изделий установлено": report_df["qty_installed"].sum(),
                "Материалы": report_df["Материалы"].sum(),
                "Зарплата производства": report_df["Производство"].sum(),
                "Зарплата монтажа": report_df["Монтаж"].sum(),
                "Доставка": report_df["Доставка"].sum(),
                "Себестоимость": report_df["Себестоимость"].sum(),
                "Цена с наценкой 100%": report_df["Цена объекта"].sum(),
            }])
            st.dataframe(totals, width="stretch", hide_index=True)

    # ========================================================
    # 2. PRINT DOCUMENTS
    # ========================================================
    elif st.session_state["reports_section"] == "Печать документов":

        st.subheader("Готовые документы")

        document_type = st.selectbox(
            "Документ",
            [
                "Выверка по объекту",
                "Выверка по заказчику",
                "Смета объекта",
                "Акт сдачи-приёмки работ",
                "Приходная накладная",
                "Расходная накладная",
            ],
            key="print_document_type"
        )

        # ---------- Reusable printable HTML ----------
        def printable_html(title, body_html):
            return f"""
            <!doctype html>
            <html><head><meta charset='utf-8'>
            <title>{escape(title)}</title>
            <style>
            body {{ font-family: Arial, sans-serif; margin: 35px; color: #111; }}
            h1 {{ font-size: 22px; margin-bottom: 8px; }}
            h2 {{ font-size: 17px; margin-top: 22px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #777; padding: 6px 8px; text-align: left; }}
            th {{ background: #eee; }}
            .right {{ text-align: right; }}
            .sign {{ margin-top: 45px; display: flex; justify-content: space-between; }}
            </style></head><body>
            <h1>{escape(title)}</h1>
            {body_html}
            </body></html>
            """

        if document_type in ["Выверка по объекту", "Смета объекта", "Акт сдачи-приёмки работ"]:
            if report_df.empty:
                st.info("Нет объектов для формирования документа.")
            else:
                object_options = [
                    f"{int(r['object_id'])} — {r['object_name']}"
                    for _, r in report_df[["object_id", "object_name"]].drop_duplicates().iterrows()
                ]
                selected_object = st.selectbox("Объект", object_options, key="print_object")
                selected_object_id = int(selected_object.split(" — ")[0])
                doc = report_df[report_df["object_id"] == selected_object_id].copy()

                object_name = str(doc.iloc[0]["object_name"])
                client_name = str(doc.iloc[0]["client_name"] or "")
                address = str(doc.iloc[0]["address"] or "")

                if document_type == "Выверка по объекту":
                    view = doc[["item_name", "quantity_needed", "qty_ready", "qty_shipped", "qty_arrived", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Готово", "Отправлено", "Доставлено", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                    title = f"Выверка по объекту — {object_name}"

                elif document_type == "Смета объекта":
                    estimate = doc.groupby("item_name", as_index=False).agg(
                        Количество=("quantity_needed", "sum"),
                        Материалы=("Материалы", "sum"),
                        Производство=("Производство", "sum"),
                        Монтаж=("Монтаж", "sum"),
                        Доставка=("Доставка", "sum"),
                        Себестоимость=("Себестоимость", "sum"),
                        Стоимость=("Цена объекта", "sum"),
                    )
                    st.dataframe(estimate, width="stretch", hide_index=True)
                    totals = estimate[["Материалы", "Производство", "Монтаж", "Доставка", "Себестоимость", "Стоимость"]].sum()
                    st.write(f"**Итого материалов:** {money(totals['Материалы'])}")
                    st.write(f"**Итого себестоимость:** {money(totals['Себестоимость'])}")
                    st.write(f"**Итоговая стоимость с наценкой 100%:** {money(totals['Стоимость'])}")
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += estimate.to_html(index=False)
                    body += f"<h2>Итого</h2><p>Материалы: {money(totals['Материалы'])}<br>Производство: {money(totals['Производство'])}<br>Монтаж: {money(totals['Монтаж'])}<br>Доставка: {money(totals['Доставка'])}<br>Себестоимость: {money(totals['Себестоимость'])}<br><b>Итоговая стоимость: {money(totals['Стоимость'])}</b></p>"
                    body += "<div class='sign'><span>Согласовано: __________________</span><span>Дата: __________________</span></div>"
                    title = f"Смета объекта — {object_name}"

                else:
                    planned = float(doc["quantity_needed"].sum())
                    completed = float(doc["qty_installed"].sum())
                    remaining = max(planned - completed, 0)
                    intermediate = remaining > 0
                    act_title = "Промежуточный акт сдачи-приёмки работ" if intermediate else "Акт сдачи-приёмки работ"
                    st.subheader(act_title)
                    st.write(f"Запланировано: **{planned:g} шт.**")
                    st.write(f"Выполнено: **{completed:g} шт.**")
                    st.write(f"Остаток: **{remaining:g} шт.**")
                    view = doc[["item_name", "quantity_needed", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<h2>{escape(act_title)}</h2><p><b>Объект:</b> {escape(object_name)}<br><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += f"<p><b>Запланировано:</b> {planned:g} шт.<br><b>Выполнено:</b> {completed:g} шт.<br><b>Остаток:</b> {remaining:g} шт.</p>"
                    body += "<div class='sign'><span>Заказчик: __________________</span><span>Исполнитель: __________________</span></div>"
                    title = f"{act_title} — {object_name}"

                st.download_button(
                    "Печать HTML",
                    data=printable_html(title, body),
                    file_name=title.replace(" ", "_") + ".html",
                    mime="text/html",
                    key="download_object_document"
                )
                st.caption("HTML-документ можно открыть в браузере и распечатать или сохранить в PDF через печать браузера.")

        elif document_type == "Выверка по заказчику":
            clients = report_df["client_name"].fillna("").astype(str).drop_duplicates().sort_values().tolist()
            if not clients:
                st.info("Нет заказчиков.")
            else:
                selected_client = st.selectbox("Заказчик", clients, key="print_client")
                doc = report_df[report_df["client_name"].fillna("").astype(str) == selected_client].copy()
                summary = doc.groupby(["object_id", "object_name"], as_index=False).agg(
                    Изделий=("quantity_needed", "sum"),
                    Выполнено=("qty_installed", "sum"),
                    Материалы=("Материалы", "sum"),
                    Производство=("Производство", "sum"),
                    Монтаж=("Монтаж", "sum"),
                    Доставка=("Доставка", "sum"),
                    Себестоимость=("Себестоимость", "sum"),
                    Стоимость=("Цена объекта", "sum"),
                )
                st.dataframe(summary, width="stretch", hide_index=True)
                body = f"<p><b>Заказчик:</b> {escape(selected_client)}</p>" + summary.to_html(index=False)
                body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                title = f"Выверка по заказчику — {selected_client}"
                st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_client_document")

        else:
            st.info("Накладные будут связаны непосредственно с движениями склада материалов. Выберите тип накладной — система покажет соответствующее движение для печати.")

    # ========================================================
    # 3. OPERATIONAL REPORTS
    # ========================================================
    elif st.session_state["reports_section"] == "Операционные отчёты":
        st.subheader("Операционные отчёты")
        operational = st.selectbox(
            "Отчёт",
            [
                "Карточка объекта",
                "Отчёт по производству",
                "Готово, но не отправлено",
                "Отчёт по доставкам",
                "Отчёт по монтажу",
                "Незавершённые объекты",
            ],
            key="operational_report"
        )

        if report_df.empty:
            st.info("Нет данных.")
        elif operational == "Карточка объекта":
            options = [f"{int(r['object_id'])} — {r['object_name']}" for _, r in report_df[["object_id","object_name"]].drop_duplicates().iterrows()]
            selected = st.selectbox("Объект", options, key="operational_object")
            oid = int(selected.split(" — ")[0])
            card = report_df[report_df["object_id"] == oid]
            st.dataframe(card[["item_name","quantity_needed","qty_installed","qty_ready","qty_shipped","qty_arrived"]].rename(columns={"item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено","qty_ready":"Готово","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по производству":
            st.dataframe(report_df.groupby(["object_name","client_name"], as_index=False).agg(Заказано=("quantity_needed","sum"), Готово=("qty_ready","sum"), Доставлено=("qty_arrived","sum"), Установлено=("qty_installed","sum")), width="stretch", hide_index=True)
        elif operational == "Готово, но не отправлено":
            st.dataframe(report_df[report_df["qty_ready"] > report_df["qty_shipped"]][["object_name","client_name","item_name","qty_ready","qty_shipped"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_ready":"Готово","qty_shipped":"Отправлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по доставкам":
            st.dataframe(report_df[["object_name","client_name","item_name","qty_shipped","qty_arrived"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по монтажу":
            st.dataframe(report_df[["object_name","client_name","item_name","quantity_needed","qty_installed"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено"}), width="stretch", hide_index=True)
        else:
            incomplete = report_df[report_df["qty_installed"] < report_df["quantity_needed"]]
            st.dataframe(incomplete.groupby(["object_id","object_name","client_name"], as_index=False).agg(Запланировано=("quantity_needed","sum"), Выполнено=("qty_installed","sum"), Остаток=("Остаток","sum")), width="stretch", hide_index=True)

    # ========================================================
    # 4. STOCK REPORTS
    # ========================================================
    else:
        st.subheader("Складские отчёты")
        stock_report = st.selectbox(
            "Отчёт",
            ["Остатки материалов", "Материалы с низким остатком", "Потребность материалов по незавершённым объектам"],
            key="stock_report"
        )
        stock = run_query("""
            SELECT m.id, m.name AS material, u.name AS unit,
                   COALESCE(m.stock_quantity,0) AS stock_quantity,
                   COALESCE(m.cost_per_unit,0) AS cost_per_unit,
                   COALESCE(m.stock_quantity,0)*COALESCE(m.cost_per_unit,0) AS stock_value
            FROM reklet.materials m
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            ORDER BY m.name
        """, fetch=True)
        if stock_report == "Остатки материалов":
            st.dataframe(stock.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        elif stock_report == "Материалы с низким остатком":
            low = stock[stock["stock_quantity"] <= 10].copy()
            st.dataframe(low.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        else:
            need = run_query("""
                SELECT o.object_name, c.name AS client_name, oi.item_name,
                       m.name AS material,
                       (oi.quantity_needed
                         * COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)
                         * COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS required_quantity,
                       COALESCE(m.stock_quantity,0) AS stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
                JOIN reklet.materials m ON m.id=ptm.material_id
                LEFT JOIN reklet.object_item_material_costs oimc
                  ON oimc.object_item_id=oi.id
                 AND oimc.material_id=ptm.material_id
                WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                ORDER BY o.object_name, oi.item_name, m.name
            """, fetch=True)
            st.dataframe(need.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","material":"Материал","required_quantity":"Требуется","stock_quantity":"На складе"}), width="stretch", hide_index=True)

