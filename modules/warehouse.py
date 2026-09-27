import pandas as pd
import streamlit as st

from core.db import get_connection, run_query, run_transaction
from core.formatting import safe_float, safe_int
from core.printing import render_print_html
from database.migrations import ensure_material_planning_tables
from repositories.clients import get_clients
from repositories.objects import get_objects
from repositories.materials import (
    get_material_categories,
    get_materials_with_categories,
)
from repositories.suppliers import get_suppliers
from services.material_planning import get_object_material_planning

def warehouse_select_object(prefix):
    clients=get_clients(); objects=get_objects().sort_values("id",ascending=False).copy()
    if clients.empty:
        st.info("Заказчики отсутствуют."); return None,None
    if objects.empty:
        st.info("Объектов нет."); return None,None
    client_rows=clients[["id","name"]].copy(); client_rows["name"]=client_rows["name"].fillna("").astype(str).str.strip(); client_rows=client_rows[client_rows["name"]!=""]
    client_options=[f"{int(r['id'])} — {r['name']}" for _,r in client_rows.iterrows()]
    selected_client=st.selectbox("Заказчик",["— Выберите заказчика —"]+client_options,key=f"{prefix}_customer")
    if selected_client=="— Выберите заказчика —":
        st.info("Сначала выберите заказчика."); return None,None
    client_id=int(selected_client.split(" — ")[0])
    client_objects=objects[pd.to_numeric(objects["client_id"],errors="coerce").eq(client_id)].copy()
    if client_objects.empty:
        st.info("У выбранного заказчика нет объектов."); return None,None
    object_options=[f"{int(r['id'])} — {str(r['object_name'] or '').strip()}" for _,r in client_objects.iterrows()]
    selected_object=st.selectbox("Объект",["— Выберите объект —"]+object_options,key=f"{prefix}_object_{client_id}")
    if selected_object=="— Выберите объект —":
        st.info("Теперь выберите объект."); return None,None
    object_id=int(selected_object.split(" — ")[0])
    row=client_objects[client_objects["id"]==object_id].iloc[0]
    return object_id,row


def _select_warehouse_section(value):
    st.session_state["warehouse_section"] = value


def _format_qty(value):
    """Display warehouse quantities with at most two decimal places."""
    if value is None or pd.isna(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) < 0.005:
        number = 0.0
    return f"{number:.2f}".rstrip("0").rstrip(".") or "0"


def render_warehouse():

    st.header("Склад материалов")

    # Только шесть актуальных разделов. Смена раздела выполняется через
    # callback, поэтому нет промежуточного рендера старого набора кнопок.
    material_sections = [
        ("Перечень материалов", "list"),
        ("Потребность материалов", "planning"),
        ("Закупка материалов", "purchase"),
        ("Приход материалов", "receipt"),
        ("Выдача материалов в производство", "issue"),
        ("Движение материалов", "movement"),
    ]

    valid_material_sections = {value for _, value in material_sections}
    if st.session_state.get("warehouse_section") not in valid_material_sections:
        st.session_state["warehouse_section"] = "list"

    for start_idx in range(0, len(material_sections), 3):
        row = material_sections[start_idx:start_idx + 3]
        cols = st.columns(len(row), gap="small")
        for col, (label, value) in zip(cols, row):
            with col:
                st.button(
                    label,
                    key=f"warehouse_nav_{start_idx}_{value}",
                    use_container_width=True,
                    on_click=_select_warehouse_section,
                    args=(value,),
                )

    active_material_section = st.session_state["warehouse_section"]
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
            # Основной перечень материалов — просмотр. Резервирование не используется.
            display=filtered[[
                "id","name","category_name","unit_name","cost_per_unit",
                "stock_quantity","default_waste_coefficient"
            ]].copy()
            display.columns=[
                "ID","Материал","Категория","Единица","Цена за единицу",
                "На складе","Коэффициент отходов"
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

                    add_form_version = st.session_state.get("add_material_form_version", 0)
                    add_form_suffix = f"_v{add_form_version}"
                    add_form_key = f"add_material_form_list_expander{add_form_suffix}"

                    with st.form(add_form_key):
                        name=st.text_input("Название материала", key=f"add_material_name_expander{add_form_suffix}")
                        unit=st.selectbox("Единица измерения",list(unit_map.keys()), key=f"add_material_unit_expander{add_form_suffix}") if unit_map else None
                        cat=st.selectbox("Категория",cat_options_add, key=f"add_material_category_expander{add_form_suffix}")
                        price=st.number_input("Цена за единицу",min_value=0.0,value=0.0,format="%.2f", key=f"add_material_price_expander{add_form_suffix}")
                        stock=st.number_input("Начальный остаток",min_value=0.0,value=0.0,format="%.4f", key=f"add_material_stock_expander{add_form_suffix}")
                        waste=st.number_input("Коэффициент отходов",min_value=0.0,value=1.20,format="%.2f", key=f"add_material_waste_expander{add_form_suffix}")
                        chosen_suppliers=st.multiselect(
                            "Поставщики (можно выбрать одного или нескольких)",
                            list(supplier_map.keys()),
                            key=f"add_material_suppliers_expander{add_form_suffix}"
                        )
                        # Предпочтительный поставщик выбирается только один раз
                        # и из полного списка поставщиков, а не только из выбранных
                        # выше. Если выбран только здесь, он автоматически
                        # добавляется также в список поставщиков материала.
                        preferred_options = ["— Не выбран —"] + list(supplier_map.keys())
                        preferred_supplier = st.selectbox(
                            "Привилегированный / предпочтительный поставщик",
                            preferred_options,
                            key=f"add_material_preferred_supplier_expander{add_form_suffix}"
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
                                    "supplier_ids": list(dict.fromkeys(
                                        [supplier_map[x] for x in chosen_suppliers] +
                                        ([supplier_map[preferred_supplier]] if preferred_supplier != "— Не выбран —" else [])
                                    )),
                                    "supplier_labels": list(dict.fromkeys(
                                        chosen_suppliers +
                                        ([preferred_supplier] if preferred_supplier != "— Не выбран —" else [])
                                    )),
                                    "preferred_supplier_id": (
                                        supplier_map[preferred_supplier]
                                        if preferred_supplier != "— Не выбран —"
                                        else None
                                    ),
                                    "preferred_supplier_label": preferred_supplier,
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
                        preferred_text = pending_create.get("preferred_supplier_label") or "не выбран"
                        st.write(f"**Привилегированный / предпочтительный поставщик:** {preferred_text}")
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
                                preferred_id = pending_create.get("preferred_supplier_id")
                                for sid in pending_create["supplier_ids"]:
                                    is_preferred = bool(preferred_id) and int(sid) == int(preferred_id)
                                    cur.execute(
                                        """INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price,is_preferred)
                                           VALUES (%s,%s,%s,%s)
                                           ON CONFLICT(material_id,supplier_id) DO UPDATE SET
                                               purchase_price=EXCLUDED.purchase_price,
                                               is_preferred=EXCLUDED.is_preferred""",
                                        (material_id,sid,pending_create["price"],is_preferred)
                                    )
                                if preferred_id:
                                    cur.execute(
                                        "UPDATE reklet.materials SET supplier_id=%s WHERE id=%s",
                                        (preferred_id, material_id)
                                    )
                                elif pending_create["supplier_ids"]:
                                    cur.execute(
                                        "UPDATE reklet.materials SET supplier_id=%s WHERE id=%s",
                                        (pending_create["supplier_ids"][0], material_id)
                                    )
                                conn.commit()
                            except Exception:
                                conn.rollback()
                                raise
                            finally:
                                cur.close()
                                conn.close()
                            st.session_state.pop("pending_material_create_list_expander_v2",None)
                            # Увеличиваем версию формы: после успешного добавления
                            # Streamlit создаёт новый экземпляр формы с пустыми полями.
                            st.session_state["add_material_form_version"] = add_form_version + 1
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
        st.subheader("Потребность материалов")
        object_id,object_row=warehouse_select_object("material_planning")
        if object_id is not None:
            planning=get_object_material_planning(object_id)
            if planning.empty:
                st.info("Для выбранного объекта нет потребности в материалах по спецификациям.")
            else:
                view=planning[[
                    "material_name","unit_name","base_required_quantity",
                    "waste_quantity","required_quantity","issued_quantity",
                    "work_in_process_quantity","remaining_need","stock_quantity",
                    "ordered_outstanding","need_to_buy"
                ]].copy()
                view.columns=[
                    "Материал","Единица","По спецификации","Обрез",
                    "Требуется","Выдано в производство","На производстве",
                    "Осталось потребно","На складе","Ожидается","Нужно купить"
                ]
                quantity_columns=[
                    "По спецификации","Обрез","Требуется",
                    "Выдано в производство","На производстве",
                    "Осталось потребно","На складе","Ожидается","Нужно купить"
                ]
                for column in quantity_columns:
                    view[column]=view[column].map(_format_qty)
                st.dataframe(view,width="stretch",hide_index=True)
                render_print_html(
                    f"Необходимые материалы — {object_row['object_name']}",
                    view,
                    f"print_material_planning_{object_id}",
                    subtitle=f"Заказчик: {object_row['client_name']}"
                )

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
                for idx,row in selected.iterrows():
                    raw=openp.loc[int(idx)]; qty=safe_float(row["Принять"])
                    statements.extend([("INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",(safe_int(raw["material_id"]),safe_int(raw["supplier_id"]),safe_int(raw["object_id"]),qty,safe_float(raw["unit_price"]))),("UPDATE reklet.purchase_order_items SET quantity_received=quantity_received+%s WHERE id=%s",(qty,safe_int(raw["purchase_item_id"]))),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,safe_int(raw["material_id"])))])
                for po_id in sorted({safe_int(openp.loc[int(i),"purchase_order_id"]) for i in selected.index}): statements.append(("""UPDATE reklet.purchase_orders po SET status=CASE WHEN NOT EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received<poi.quantity_ordered) THEN 'received' WHEN EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received>0) THEN 'partial' ELSE 'ordered' END WHERE po.id=%s""",(po_id,)))
                if selected.empty: st.warning("Выберите позиции и укажите количество принятого материала.")
                elif errors: st.error("Приход не выполнен:\n"+"\n".join(errors))
                else: run_transaction(statements); st.success("Приход оформлен. Материал добавлен на общий склад."); st.session_state.pop("purchase_receipt_editor",None); st.rerun()

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
            if planning.empty:
                st.info("Для выбранного объекта нет потребности в материалах.")
            else:
                scope=st.selectbox(
                    "Материалы",
                    ["Все материалы","Только необходимые для объекта"],
                    key="issue_material_scope"
                )
                issue=planning.copy()
                if scope=="Только необходимые для объекта":
                    issue=issue[issue["remaining_need"]>0].copy()
                if issue.empty:
                    st.info("Материалов для выбранного отбора нет.")
                else:
                    idf=issue[[
                        "material_id","material_name","unit_name","stock_quantity",
                        "required_quantity","issued_quantity","remaining_need"
                    ]].copy()
                    idf.insert(0,"Выбрать",False)
                    idf["Выдать"]=0.0
                    idf.columns=[
                        "Выбрать","ID","Материал","Единица","На складе",
                        "Потребность объекта","Выдано","Осталось потребно","Выдать"
                    ]
                    with st.form(f"issue_materials_form_{object_id}",clear_on_submit=False):
                        edited=st.data_editor(
                            idf,
                            key=f"issue_materials_editor_{object_id}_{scope}",
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                                "ID":st.column_config.NumberColumn("ID",disabled=True),
                                "Материал":st.column_config.TextColumn("Материал",disabled=True),
                                "Единица":st.column_config.TextColumn("Единица",disabled=True),
                                "На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),
                                "Потребность объекта":st.column_config.NumberColumn("Потребность объекта",disabled=True,format="%.4f"),
                                "Выдано":st.column_config.NumberColumn("Выдано",disabled=True,format="%.4f"),
                                "Осталось потребно":st.column_config.NumberColumn("Осталось потребно",disabled=True,format="%.4f"),
                                "Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.001,format="%.4f")
                            },
                            disabled=["ID","Материал","Единица","На складе","Потребность объекта","Выдано","Осталось потребно"]
                        )
                        execute=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
                    if execute:
                        selected=edited[edited["Выбрать"].fillna(False)&(edited["Выдать"].fillna(0)>0)].copy()
                        errors=[]; statements=[]
                        for _,row in selected.iterrows():
                            mid=safe_int(row["ID"]); qty=safe_float(row["Выдать"]); stock=safe_float(row["На складе"]); remaining=safe_float(row["Осталось потребно"])
                            if qty>stock+1e-9:
                                errors.append(f"{row['Материал']}: на складе только {stock:.4f}.")
                            if qty>remaining+1e-9:
                                errors.append(f"{row['Материал']}: требуется ещё только {remaining:.4f}.")
                            if qty>0 and qty<=min(stock,remaining)+1e-9:
                                statements.extend([
                                    (
                                        "INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",
                                        (mid,object_id,qty)
                                    ),
                                    (
                                        "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                                        (qty,mid)
                                    )
                                ])
                        if selected.empty:
                            st.warning("Выберите материалы и укажите количество.")
                        elif errors:
                            st.error("Выдача не выполнена:\n"+"\n".join(errors))
                        elif not statements:
                            st.info("Нет допустимых изменений.")
                        else:
                            run_transaction(statements)
                            st.success("Материалы выданы в производство.")
                            st.session_state.pop(f"issue_materials_editor_{object_id}_{scope}",None)
                            st.rerun()

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

        ) x ORDER BY tx_date DESC LIMIT 500""",fetch=True)
        if movements.empty: st.info("Движений материалов пока нет.")
        else:
            view=movements.rename(columns={"tx_date":"Дата","operation_name":"Операция","client_name":"Заказчик","object_name":"Объект","product_name":"Изделие","material_name":"Материал","supplier_name":"Поставщик","quantity":"Количество","unit_price":"Цена"})[["Дата","Операция","Заказчик","Объект","Изделие","Материал","Поставщик","Количество","Цена"]]; st.dataframe(view,width="stretch",hide_index=True); render_print_html("Движение материалов",view,"print_material_movements")




    # ============================================================
