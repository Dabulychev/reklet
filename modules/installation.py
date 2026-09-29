import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_int
from core.printing import render_print_html
from database.migrations import ensure_stage_movement_tables
from repositories.objects import get_stage_objects


def render_installation():

    st.header("Монтаж")
    ensure_stage_movement_tables()

    stage_objects = get_stage_objects("installation").sort_values("id", ascending=False).copy()
    if stage_objects.empty:
        st.info("В монтаже нет незавершённых заданий.")
    else:
        customer_options = ["Все заказчики"] + sorted(
            stage_objects["client_name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].unique().tolist()
        )
        selected_customer = st.selectbox(
            "Заказчик", customer_options, key="installation_customer_filter_v2"
        )

        filtered_objects = stage_objects.copy()
        if selected_customer != "Все заказчики":
            filtered_objects = filtered_objects[
                filtered_objects["client_name"].fillna("").astype(str).str.strip().eq(selected_customer)
            ].copy()

        object_options = ["Все объекты"] + [
            f"{int(r['id'])} — {str(r['object_name']).strip()}"
            for _,r in filtered_objects.iterrows()
        ]
        selected_object = st.selectbox(
            "Объект", object_options, key="installation_object_filter_v2"
        )

        if selected_object == "Все объекты":
            overview_query = """
                SELECT o.id AS object_id,o.object_name,c.name AS client_name,
                       oi.item_name,oi.quantity_needed,
                       COALESCE(oi.qty_arrived,0) AS qty_arrived
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                WHERE COALESCE(oi.qty_arrived,0)>0
            """
            params=[]
            if selected_customer != "Все заказчики":
                overview_query += " AND c.name=%s"
                params.append(selected_customer)
            overview_query += " ORDER BY o.object_name,oi.item_name"
            overview=run_query(overview_query,tuple(params),fetch=True)
            if overview.empty:
                st.info("Для выбранного заказчика нет изделий, доступных для монтажа.")
            else:
                overview.columns=["Объект ID","Объект","Заказчик","Изделие","Заказано","Прибыло"]
                for col in ["Заказано","Прибыло"]:
                    overview[col]=pd.to_numeric(overview[col],errors="coerce").fillna(0).round(0).astype(int)
                st.dataframe(overview,width="stretch",hide_index=True)
            st.info("Для выполнения монтажа выберите конкретный объект.")
        else:
            object_id=int(selected_object.split(" — ")[0])
            df=run_query(
                """SELECT oi.id,oi.item_name,oi.quantity_needed AS ordered,
                          COALESCE(oi.qty_arrived,0) AS arrived,
                          COALESCE(oi.qty_installing,0) AS installing,
                          COALESCE(oi.qty_installed,0) AS installed
                   FROM reklet.object_items oi
                   WHERE oi.object_id=%s AND COALESCE(oi.qty_arrived,0)>0
                   ORDER BY oi.id""",
                (object_id,),fetch=True
            )
            if df.empty:
                st.success("Для выбранного объекта нет изделий, доступных для монтажа.")
            else:
                editor=df[["id","item_name","ordered","arrived","installing","installed"]].copy()
                editor.columns=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"]
                editor["Смонтировать"]=0
                installation_print=editor[["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"]].copy()
                render_print_html(f"Задание на монтаж — {selected_object}",installation_print,f"print_installation_{object_id}")
                with st.form(f"installation_form_{object_id}",clear_on_submit=False):
                    edited=st.data_editor(
                        editor,key=f"installation_editor_{object_id}",width="stretch",hide_index=True,column_config={
                            "ID":st.column_config.NumberColumn("ID",disabled=True),
                            "Изделие":st.column_config.TextColumn("Изделие",disabled=True),
                            "Заказано":st.column_config.NumberColumn("Заказано",disabled=True),
                            "Прибыло":st.column_config.NumberColumn("Прибыло",disabled=True),
                            "В монтаже":st.column_config.NumberColumn("В монтаже",disabled=True),
                            "Смонтировано":st.column_config.NumberColumn("Смонтировано",disabled=True),
                            "Смонтировать":st.column_config.NumberColumn("Смонтировать",min_value=0,step=1,format="%d")
                        },disabled=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"]
                    )
                    execute=st.form_submit_button("Выполнить",use_container_width=True)
                if execute:
                    errors=[]; statements=[]
                    for _,r in edited.iterrows():
                        qty=safe_int(r["Смонтировать"]); available=safe_int(r["Прибыло"]); item_id=safe_int(r["ID"])
                        if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, доступно для монтажа {available}.")
                        if qty>0 and qty<=available:
                            statements.extend([
                                ("UPDATE reklet.object_items SET qty_arrived=GREATEST(COALESCE(qty_arrived,0)-%s,0), qty_installed=COALESCE(qty_installed,0)+%s, installation_status=CASE WHEN COALESCE(qty_installed,0)+%s>=quantity_needed THEN 'completed' ELSE 'in_progress' END, installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND((COALESCE(qty_installed,0)+%s)::numeric/quantity_needed*100)) ELSE 0 END WHERE id=%s",(qty,qty,qty,qty,item_id)),
                                ("INSERT INTO reklet.installation_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'complete',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                            ])
                    if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                    elif not statements: st.info("Введите количество хотя бы для одной строки.")
                    else:
                        run_transaction(statements); st.success("Монтаж выполнен."); st.rerun()

    st.markdown("---")
    st.subheader("Движения по монтажу")
    movements=run_query("""SELECT it.id,o.object_name,c.name AS client_name,oi.item_name,it.operation_type,it.quantity,it.created_at FROM reklet.installation_transactions it LEFT JOIN reklet.objects o ON o.id=it.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=it.object_item_id ORDER BY it.created_at DESC LIMIT 500""",fetch=True)
    if not movements.empty:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"})
        installation_movement_view=movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy()
        st.dataframe(installation_movement_view,width="stretch",hide_index=True)
        render_print_html("Движения по монтажу",installation_movement_view,"print_installation_movements")
    else:
        st.info("Движений монтажа пока нет.")
