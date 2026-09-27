import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_float, safe_int
from core.printing import render_print_html
from database.migrations import (
    ensure_material_planning_tables,
    ensure_stage_movement_tables,
    ensure_object_item_material_costs,
)
from modules.stage_filter_helper import get_stage_work_items, render_stage_object_filters


def render_production():

    ensure_material_planning_tables()
    st.header("Производство")
    ensure_stage_movement_tables()

    stage_objects, filtered_objects, selected_client, selected_object, object_id = render_stage_object_filters(
        "production", "production"
    )
    if stage_objects.empty:
        st.success("На производстве нет незавершённых заданий.")
    elif selected_object == "Все объекты":
        overview = get_stage_work_items("production", filtered_objects["id"].tolist())
        if overview.empty:
            st.info("Для выбранного отбора нет актуальных изделий для производства.")
        else:
            view = overview[[
                "client_name", "object_name", "item_name", "quantity_needed", "qty_new", "qty_production", "qty_ready"
            ]].copy()
            view.columns = [
                "Заказчик", "Объект", "Изделие", "Заказано", "Осталось произвести", "В производстве", "Готовая продукция"
            ]
            st.dataframe(view, width="stretch", hide_index=True)
            render_print_html(
                "Производство — актуальные задания",
                view,
                "print_production_all"
            )
            st.caption("Для выполнения операции выберите конкретный объект в отборе выше.")
    else:
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
