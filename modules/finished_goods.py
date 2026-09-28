import pandas as pd
import streamlit as st

from core.db import run_query, run_transaction
from core.formatting import safe_int
from core.printing import render_print_html
from core.instructions import render_page_instruction
from database.migrations import ensure_stage_movement_tables
from repositories.objects import get_stage_objects


def render_finished_goods():

    st.header("Готовая продукция")
    ensure_stage_movement_tables()

    stage_objects = get_stage_objects("finished_goods").sort_values("id", ascending=False).copy()
    if stage_objects.empty:
        st.success("На складе готовой продукции нет незавершённых заданий.")
    else:
        customer_options = ["Все заказчики"] + sorted(
            stage_objects["client_name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].unique().tolist()
        )
        selected_customer = st.selectbox(
            "Заказчик", customer_options, key="finished_goods_customer_filter_v2"
        )

        filtered_objects = stage_objects.copy()
        if selected_customer != "Все заказчики":
            filtered_objects = filtered_objects[
                filtered_objects["client_name"].fillna("").astype(str).str.strip().eq(selected_customer)
            ].copy()

        object_options = ["Все объекты"] + [
            f"{int(r['id'])} — {str(r['object_name']).strip()}"
            for _, r in filtered_objects.iterrows()
        ]
        selected_object = st.selectbox(
            "Объект", object_options, key="finished_goods_object_filter_v2"
        )

        if selected_object == "Все объекты":
            overview_query = """
                SELECT o.id AS object_id, o.object_name, c.name AS client_name,
                       oi.id AS object_item_id, oi.item_name, oi.quantity_needed,
                       COALESCE(oi.qty_ready,0) AS qty_ready
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                WHERE COALESCE(oi.qty_ready,0)>0
            """
            params = []
            if selected_customer != "Все заказчики":
                overview_query += " AND c.name=%s"
                params.append(selected_customer)
            overview_query += " ORDER BY o.object_name, oi.item_name"
            overview = run_query(overview_query, tuple(params), fetch=True)
            if overview.empty:
                st.info("Для выбранного заказчика нет изделий на складе готовой продукции.")
            else:
                overview.columns = ["Объект ID","Объект","Заказчик","Изделие","Заказано","На складе"]
                for col in ["Заказано","На складе"]:
                    overview[col] = pd.to_numeric(overview[col], errors="coerce").fillna(0).round(0).astype(int)
                st.dataframe(overview, width="stretch", hide_index=True)
            st.info("Для передачи изделия в транспорт выберите конкретный объект.")
        else:
            object_id = int(selected_object.split(" — ")[0])
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
                editor = df[["id","item_name","ordered","ready","shipped","arrived"]].copy()
                editor.columns = ["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
                editor["Передать в транспорт"] = 0
                finished_goods_print = editor[["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]].copy()
                render_print_html(
                    f"Готовая продукция — {selected_object}",
                    finished_goods_print,
                    f"print_finished_goods_{object_id}"
                )
                with st.form(f"finished_goods_form_{object_id}", clear_on_submit=False):
                    edited = st.data_editor(
                        editor, key=f"finished_goods_editor_{object_id}", width="stretch", hide_index=True,
                        column_config={
                            "ID": st.column_config.NumberColumn("ID",disabled=True),
                            "Изделие": st.column_config.TextColumn("Изделие",disabled=True),
                            "Заказано": st.column_config.NumberColumn("Заказано",disabled=True),
                            "На складе": st.column_config.NumberColumn("На складе",disabled=True),
                            "Уже отправлено": st.column_config.NumberColumn("Уже отправлено",disabled=True),
                            "Доставлено": st.column_config.NumberColumn("Доставлено",disabled=True),
                            "Передать в транспорт": st.column_config.NumberColumn("Передать в транспорт",min_value=0,step=1,format="%d"),
                        },
                        disabled=["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
                    )
                    execute = st.form_submit_button("Выполнить", use_container_width=True)
                if execute:
                    errors=[]; statements=[]
                    for _,r in edited.iterrows():
                        qty=safe_int(r["Передать в транспорт"]); available=safe_int(r["На складе"]); item_id=safe_int(r["ID"])
                        if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, на складе только {available}.")
                        if qty>0 and qty<=available:
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
    movements = run_query("""SELECT fgt.id,o.object_name,c.name AS client_name,oi.item_name,fgt.operation_type,fgt.quantity,fgt.created_at FROM reklet.finished_goods_transactions fgt LEFT JOIN reklet.objects o ON o.id=fgt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=fgt.object_item_id ORDER BY fgt.created_at DESC LIMIT 500""", fetch=True)
    if movements.empty:
        st.info("Движений пока нет.")
    else:
        movements = movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"})
        finished_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy()
        st.dataframe(finished_movement_view, width="stretch", hide_index=True)
        render_print_html("Движения по складу готовой продукции", finished_movement_view, "print_finished_goods_movements")
    render_page_instruction("finished_goods")
