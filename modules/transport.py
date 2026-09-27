import streamlit as st

from core.db import run_query, run_transaction
from core.printing import render_print_html
from core.formatting import safe_int
from database.migrations import ensure_stage_movement_tables
from modules.stage_filter_helper import get_stage_work_items, render_stage_object_filters


def render_transport():

    st.header("Транспорт и логистика")
    ensure_stage_movement_tables()
    stage_objects, filtered_objects, selected_client, selected_object, object_id = render_stage_object_filters(
        "transport", "transport"
    )
    if stage_objects.empty:
        st.success("В транспорте нет незавершённых заданий.")
    elif selected_object == "Все объекты":
        overview = get_stage_work_items("transport", filtered_objects["id"].tolist())
        if overview.empty:
            st.info("Для выбранного отбора нет изделий в пути.")
        else:
            overview["in_transit"] = (
                overview["qty_shipped"] - overview["qty_arrived"]
            ).clip(lower=0)
            view = overview[[
                "client_name", "object_name", "item_name", "quantity_needed",
                "qty_shipped", "qty_arrived", "in_transit"
            ]].copy()
            view.columns = [
                "Заказчик", "Объект", "Изделие", "Заказано",
                "Отправлено", "Доставлено", "В пути"
            ]
            st.dataframe(view, width="stretch", hide_index=True)
            render_print_html(
                "Транспорт — актуальные задания",
                view,
                "print_transport_all"
            )
            st.caption("Для выполнения доставки выберите конкретный объект в отборе выше.")
    else:
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
