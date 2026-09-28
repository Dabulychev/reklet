import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_float, safe_int
from core.printing import render_print_html
from core.instructions import render_page_instruction
from database.migrations import (
    ensure_material_planning_tables,
    ensure_task_three_tables,
    ensure_stage_movement_tables,
    ensure_object_item_material_costs,
)
from repositories.objects import get_stage_objects


def _production_object_wip(object_id):
    issued = run_query(
        """
        SELECT material_id,COALESCE(SUM(quantity),0) AS issued_quantity
        FROM reklet.material_transactions
        WHERE object_id=%s
          AND operation_type='production_transfer'
          AND transaction_type='OUT'
        GROUP BY material_id
        """,
        (object_id,), fetch=True,
    )
    consumed = run_query(
        """
        SELECT material_id,COALESCE(SUM(quantity),0) AS consumed_quantity
        FROM reklet.material_consumption
        WHERE object_id=%s
        GROUP BY material_id
        """,
        (object_id,), fetch=True,
    )
    wasted = run_query(
        """
        SELECT material_id,COALESCE(SUM(quantity),0) AS waste_quantity
        FROM reklet.material_waste_transactions
        WHERE object_id=%s AND source_type='production'
        GROUP BY material_id
        """,
        (object_id,), fetch=True,
    )
    result={}
    for _,row in issued.iterrows():
        mid=safe_int(row['material_id'])
        result[mid]=result.get(mid,0.0)+safe_float(row['issued_quantity'])
    for _,row in consumed.iterrows():
        mid=safe_int(row['material_id'])
        result[mid]=result.get(mid,0.0)-safe_float(row['consumed_quantity'])
    for _,row in wasted.iterrows():
        mid=safe_int(row['material_id'])
        result[mid]=result.get(mid,0.0)-safe_float(row['waste_quantity'])
    return {mid:max(qty,0.0) for mid,qty in result.items()}


def _production_global_excess():
    ensure_task_three_tables()
    df=run_query(
        """
        SELECT
            m.id AS material_id,
            GREATEST(
                COALESCE((
                    SELECT SUM(mt.quantity)
                    FROM reklet.material_transactions mt
                    WHERE mt.material_id=m.id
                      AND mt.object_id IS NULL
                      AND mt.operation_type='production_transfer'
                      AND mt.transaction_type='OUT'
                ),0)
                - COALESCE((
                    SELECT SUM(mt.quantity)
                    FROM reklet.material_transactions mt
                    WHERE mt.material_id=m.id
                      AND mt.operation_type='production_allocation'
                      AND mt.transaction_type='IN'
                ),0)
                - COALESCE((
                    SELECT SUM(mt.quantity)
                    FROM reklet.material_transactions mt
                    WHERE mt.material_id=m.id
                      AND mt.object_id IS NULL
                      AND mt.operation_type='production_return'
                      AND mt.transaction_type='IN'
                ),0)
                - COALESCE((
                    SELECT SUM(mw.quantity)
                    FROM reklet.material_waste_transactions mw
                    WHERE mw.material_id=m.id
                      AND mw.object_id IS NULL
                      AND mw.source_type='production'
                ),0),
                0
            ) AS excess_quantity
        FROM reklet.materials m
        """,
        fetch=True,
    )
    if df.empty:
        return {}
    return {
        safe_int(row['material_id']):max(safe_float(row['excess_quantity']),0.0)
        for _,row in df.iterrows()
    }


def _save_production_material_requests(object_id, shortage_lines):
    """Create/update open material requests for the current object."""
    statements=[]
    for line in shortage_lines:
        request_df=run_query(
            """
            SELECT id,quantity_requested,quantity_supplied
            FROM reklet.material_production_requests
            WHERE object_item_id=%s
              AND material_id=%s
              AND status IN ('sent','purchasing','ready')
              AND quantity_supplied<quantity_requested
            ORDER BY id
            LIMIT 1
            """,
            (line['object_item_id'],line['material_id']),
            fetch=True,
        )
        if request_df.empty:
            statements.append((
                """
                INSERT INTO reklet.material_production_requests(
                    object_id,object_item_id,material_id,quantity_requested,status,notes
                ) VALUES (%s,%s,%s,%s,'sent','Заявка производства на недостающий материал')
                """,
                (object_id,line['object_item_id'],line['material_id'],line.get('order_quantity',line['shortage'])),
            ))
        else:
            row=request_df.iloc[0]
            rid=safe_int(row['id'])
            requested=safe_float(row['quantity_requested'])
            supplied=safe_float(row['quantity_supplied'])
            new_requested=max(requested,supplied+line.get('order_quantity',line['shortage']))
            statements.append((
                "UPDATE reklet.material_production_requests SET quantity_requested=%s,status='sent',updated_at=timezone('utc'::text,now()) WHERE id=%s",
                (new_requested,rid),
            ))
    if statements:
        run_transaction(statements)


def render_production():
    ensure_material_planning_tables()
    ensure_task_three_tables()
    st.header("Производство")
    ensure_stage_movement_tables()

    stage_objects=get_stage_objects("production").sort_values("id",ascending=False).copy()
    if stage_objects.empty:
        st.info("В производстве нет незавершённых заданий.")
        return

    customer_options=["Все заказчики"] + sorted(
        stage_objects["client_name"].fillna("").astype(str).str.strip().loc[lambda x: x!=""].unique().tolist()
    )
    selected_customer=st.selectbox(
        "Заказчик",
        customer_options,
        key="production_customer_filter_v5"
    )

    filtered_objects=stage_objects.copy()
    if selected_customer!="Все заказчики":
        filtered_objects=filtered_objects[
            filtered_objects["client_name"].fillna("").astype(str).str.strip().eq(selected_customer)
        ].copy()

    object_options=["Все объекты"] + [
        f"{int(r['id'])} — {str(r['object_name']).strip()}"
        for _,r in filtered_objects.iterrows()
    ]
    selected_object=st.selectbox(
        "Объект",
        object_options,
        key="production_object_table"
    )

    if selected_object=="Все объекты":
        overview_query="""
            SELECT o.id AS object_id,o.object_name,c.name AS client_name,
                   oi.id AS object_item_id,oi.item_name,oi.quantity_needed,
                   COALESCE(oi.qty_new,0) AS qty_new,
                   COALESCE(oi.qty_production,0) AS qty_production
            FROM reklet.object_items oi
            JOIN reklet.objects o ON o.id=oi.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            WHERE (COALESCE(oi.qty_new,0)>0 OR COALESCE(oi.qty_production,0)>0)
        """
        overview_params=[]
        if selected_customer!="Все заказчики":
            overview_query += " AND c.name=%s"
            overview_params.append(selected_customer)
        overview_query += " ORDER BY o.object_name,oi.item_name"
        overview=run_query(overview_query,tuple(overview_params),fetch=True)
        overview.columns=["Объект ID","Объект","Заказчик","Изделие","Заказано","Осталось нового","В производстве"]
        for col in ["Заказано","Осталось нового","В производстве"]:
            overview[col]=pd.to_numeric(overview[col],errors="coerce").fillna(0).round(0).astype(int)
        render_print_html("Производство — перечень заданий",overview,"print_production_overview_v5")
        st.dataframe(overview,width="stretch",hide_index=True)
        st.info("Для выполнения производственной операции выберите конкретный объект.")
        return

    object_id=int(selected_object.split(" — ")[0])

    production_df=run_query(
        """
        SELECT oi.id,oi.item_name,oi.quantity_needed,
               COALESCE(oi.qty_new,0) AS qty_new,
               COALESCE(oi.qty_production,0) AS qty_production,
               COALESCE(oi.qty_ready,0) AS qty_ready,
               (COALESCE(oi.quantity_needed,0)-COALESCE(oi.qty_new,0)) AS manufactured_total
        FROM reklet.object_items oi
        WHERE oi.object_id=%s
          AND (COALESCE(oi.qty_new,0)>0 OR COALESCE(oi.qty_production,0)>0)
        ORDER BY oi.id
        """,
        (object_id,),fetch=True
    )
    if production_df.empty:
        st.info("Для выбранного объекта сейчас нет незавершённых производственных заданий.")
        return

    ensure_object_item_material_costs(object_id)
    production_material_requirements=run_query(
        """
        SELECT oi.id AS object_item_id,ptm.material_id,
               SUM(COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)
                   * COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS material_per_product
        FROM reklet.object_items oi
        JOIN reklet.product_template_materials ptm
          ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
        JOIN reklet.materials m ON m.id=ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc
          ON oimc.object_item_id=oi.id
         AND oimc.material_id=ptm.material_id
        WHERE oi.object_id=%s
        GROUP BY oi.id,ptm.material_id
        """,
        (object_id,),fetch=True
    )
    object_wip=_production_object_wip(object_id)
    global_excess=_production_global_excess()

    req_map={}
    if not production_material_requirements.empty:
        for _,rr in production_material_requirements.iterrows():
            req_map.setdefault(safe_int(rr['object_item_id']),[]).append((safe_int(rr['material_id']),safe_float(rr['material_per_product'])))

    editor=production_df[["id","item_name","quantity_needed","manufactured_total","qty_production","qty_ready"]].copy()
    editor.columns=["ID","Изделие","Заказано","Изготовлено","В производстве","Уже на готовой продукции"]
    editor["Передать на склад"]=0

    production_print=editor[["ID","Изделие","Заказано","Изготовлено","В производстве","Уже на готовой продукции"]].copy()
    render_print_html(f"Производственное задание — {selected_object}",production_print,f"print_production_{object_id}")

    with st.form(f"production_form_{object_id}",clear_on_submit=False):
        edited=st.data_editor(
            editor,key=f"production_excel_editor_{object_id}",width="stretch",hide_index=True,
            column_config={
                "ID":st.column_config.NumberColumn("ID",disabled=True),
                "Изделие":st.column_config.TextColumn("Изделие",disabled=True),
                "Заказано":st.column_config.NumberColumn("Заказано",disabled=True),
                "Изготовлено":st.column_config.NumberColumn("Изготовлено",min_value=0,step=1,format="%d"),
                "В производстве":st.column_config.NumberColumn("В производстве",disabled=True),
                "Уже на готовой продукции":st.column_config.NumberColumn("Уже на готовой продукции",disabled=True),
                "Передать на склад":st.column_config.NumberColumn("Передать на склад",min_value=0,step=1,format="%d"),
            },
            disabled=["ID","Изделие","Заказано","В производстве","Уже на готовой продукции"],
        )
        execute=st.form_submit_button("Выполнить",use_container_width=True)

    pending_order_key=f"pending_production_material_order_{object_id}"

    if execute:
        errors=[]
        statements=[]
        consumption_plan=[]
        consumption_by_material={}
        item_for_material={}

        for idx,row in edited.iterrows():
            src=production_df.iloc[idx]
            item_id=safe_int(row['ID'])
            ordered=safe_int(src['quantity_needed'])
            old_manufactured=safe_int(src['manufactured_total'])
            new_manufactured=safe_int(row['Изготовлено'])
            in_prod=safe_int(src['qty_production'])
            to_stock=safe_int(row['Передать на склад'])

            if new_manufactured<old_manufactured:
                errors.append(f"{row['Изделие']}: количество изготовленного нельзя уменьшить ниже {old_manufactured}.")
            if new_manufactured>ordered:
                errors.append(f"{row['Изделие']}: изготовлено {new_manufactured}, заказано только {ordered}.")
            added=new_manufactured-old_manufactured

            if added>0:
                for material_id,per_product in req_map.get(item_id,[]):
                    qty_material=added*per_product
                    consumption_plan.append((item_id,material_id,qty_material))
                    consumption_by_material[material_id]=consumption_by_material.get(material_id,0.0)+qty_material
                    item_for_material.setdefault(material_id,item_id)

            available_for_transfer=in_prod+max(added,0)
            if to_stock>available_for_transfer:
                errors.append(f"{row['Изделие']}: передача {to_stock} шт., доступно максимум {available_for_transfer} шт.")
            if to_stock<0:
                errors.append(f"{row['Изделие']}: количество не может быть отрицательным.")

            if new_manufactured!=old_manufactured:
                statements.append((
                    "UPDATE reklet.object_items SET qty_new=GREATEST(quantity_needed-%s-COALESCE(qty_ready,0)-COALESCE(qty_shipped,0)-COALESCE(qty_arrived,0)-COALESCE(qty_installing,0)-COALESCE(qty_installed,0),0), qty_production=COALESCE(qty_production,0)+%s, production_status='in_progress' WHERE id=%s",
                    (new_manufactured,added,item_id),
                ))

            if to_stock:
                statements.extend([
                    ("UPDATE reklet.object_items SET qty_production=GREATEST(COALESCE(qty_production,0)-%s,0),qty_ready=COALESCE(qty_ready,0)+%s WHERE id=%s",(to_stock,to_stock,item_id)),
                    ("INSERT INTO reklet.production_transactions(object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'completed',%s FROM reklet.object_items WHERE id=%s",(to_stock,item_id)),
                    ("INSERT INTO reklet.finished_goods(object_item_id,object_id,quantity,status) SELECT id,object_id,%s,'ready' FROM reklet.object_items WHERE id=%s",(to_stock,item_id)),
                    ("INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s",(to_stock,item_id)),
                ])

        shortage_lines=[]
        for material_id,required_qty in consumption_by_material.items():
            object_available=max(object_wip.get(material_id,0.0),0.0)
            excess_available=max(global_excess.get(material_id,0.0),0.0)
            total_available=object_available+excess_available
            if required_qty>total_available+1e-9:
                nm=run_query("SELECT name FROM reklet.materials WHERE id=%s",(material_id,),fetch=True)
                name=str(nm.iloc[0]['name']) if not nm.empty else str(material_id)
                shortage=max(required_qty-total_available,0.0)
                shortage_lines.append({
                    'object_item_id':item_for_material.get(material_id),
                    'material_id':material_id,
                    'material_name':name,
                    'required':required_qty,
                    'available':total_available,
                    'shortage':shortage,
                })
            else:
                # Use existing object-specific WIP first, then allocate the
                # remaining quantity from the global production excess pool.
                from_excess=max(required_qty-object_available,0.0)
                from_excess=min(from_excess,excess_available)
                if from_excess>1e-9:
                    statements.append((
                        "INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_allocation',%s,'IN')",
                        (material_id,object_id,from_excess),
                    ))

        if shortage_lines:
            # Material shortage is no longer shown as a generic warning.
            # Store the order form data and discard this attempted production operation.
            statements=[]
            st.session_state[pending_order_key]=shortage_lines
        elif errors:
            st.error("Операция не выполнена:\n"+"\n".join(errors))
        elif not statements:
            st.info("Изменений нет.")
        else:
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
                    (item_id,object_id,material_id,qty_material,item_id,material_id,material_id),
                ))
            run_transaction(statements)
            st.success("Производственные данные обновлены. Выполненные позиции исчезнут из рабочего списка.")
            st.rerun()

    pending_order=st.session_state.get(pending_order_key)
    if pending_order:
        st.markdown('---')
        st.subheader('Заказ материала на производстве')
        order_view=pd.DataFrame(pending_order)[[
            'material_name','required','available','shortage'
        ]].copy()
        order_view.columns=['Материал','Требуется','Доступно в производстве','Не хватает']
        st.dataframe(order_view,width='stretch',hide_index=True)
        with st.form(f"production_material_order_form_{object_id}",clear_on_submit=False):
            order_button=st.form_submit_button('Заказать на складе',use_container_width=True)
        if order_button:
            _save_production_material_requests(object_id,pending_order)
            st.session_state.pop(pending_order_key,None)
            st.success('Заявка на материалы отправлена на склад.')
            st.rerun()
    render_page_instruction("production")
