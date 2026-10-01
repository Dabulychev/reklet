import pandas as pd
import streamlit as st

from core.db import get_connection, run_query, run_transaction
from core.formatting import safe_float, safe_int
from core.printing import render_print_html
from core.instructions import render_page_instruction
from database.migrations import ensure_material_planning_tables, ensure_task_three_tables
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
    filter_customer_col, filter_object_col = st.columns(2, gap="small")
    with filter_customer_col:
        selected_client=st.selectbox("Заказчик",["— Выберите заказчика —"]+client_options,key=f"{prefix}_customer")
    if selected_client=="— Выберите заказчика —":
        st.info("Сначала выберите заказчика."); return None,None
    client_id=int(selected_client.split(" — ")[0])
    client_objects=objects[pd.to_numeric(objects["client_id"],errors="coerce").eq(client_id)].copy()
    if client_objects.empty:
        st.info("У выбранного заказчика нет объектов."); return None,None
    object_options=[f"{int(r['id'])} — {str(r['object_name'] or '').strip()}" for _,r in client_objects.iterrows()]
    with filter_object_col:
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



def _get_production_excess_rows():
    """Return global production excess by material, normalized to 2 decimals."""
    ensure_task_three_tables()
    df = run_query(
        """
        SELECT
            m.id AS material_id,
            m.name AS material_name,
            u.name AS unit_name,
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
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        ORDER BY m.name
        """,
        fetch=True,
    )
    if df.empty:
        return df
    df['excess_quantity'] = pd.to_numeric(df['excess_quantity'], errors='coerce').fillna(0.0).round(2)
    # Do not show floating-point dust such as 0.000002 as a real excess.
    df = df[df['excess_quantity'] > 0].copy()
    return df


def _get_production_excess_map():
    df = _get_production_excess_rows()
    if df.empty:
        return {}
    return {
        safe_int(row['material_id']): safe_float(row['excess_quantity'])
        for _, row in df.iterrows()
    }


def _get_production_requests_open():
    """Open production requests together with linked PO/order/receipt totals."""
    ensure_task_three_tables()
    return run_query(
        """
        SELECT
            r.id AS request_id,
            r.object_id,
            r.object_item_id,
            r.material_id,
            c.name AS client_name,
            o.object_name,
            oi.item_name,
            m.name AS material_name,
            u.name AS unit_name,
            COALESCE(m.stock_quantity,0) AS stock_quantity,
            r.quantity_requested,
            r.quantity_supplied,
            COALESCE(SUM(CASE WHEN po.id IS NOT NULL THEN poi.quantity_ordered ELSE 0 END),0) AS quantity_ordered,
            COALESCE(SUM(CASE WHEN po.id IS NOT NULL THEN poi.quantity_received ELSE 0 END),0) AS quantity_received
        FROM reklet.material_production_requests r
        JOIN reklet.objects o ON o.id=r.object_id
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        JOIN reklet.object_items oi ON oi.id=r.object_item_id
        JOIN reklet.materials m ON m.id=r.material_id
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        LEFT JOIN reklet.purchase_order_items poi ON poi.production_request_id=r.id
        LEFT JOIN reklet.purchase_orders po
          ON po.id=poi.purchase_order_id
         AND po.status<>'cancelled'
       WHERE r.status IN ('sent','purchasing','ready')
  AND ROUND(r.quantity_supplied::numeric, 6)
      < ROUND(r.quantity_requested::numeric, 6)
        GROUP BY
            r.id,r.object_id,r.object_item_id,r.material_id,
            c.name,o.object_name,oi.item_name,m.name,u.name,
            m.stock_quantity,
            r.quantity_requested,r.quantity_supplied
        ORDER BY r.created_at,r.id
        """,
        fetch=True,
    )


def _render_production_requests_expander():
    """Render production-to-warehouse requests above the warehouse content."""
    requests = _get_production_requests_open()
    if requests.empty:
        return

    st.markdown('---')
    with st.expander('Заказ с производства', expanded=False):
        st.subheader('Заказать материалы для производства')

        view = requests[[
            'request_id','client_name','object_name','item_name','material_name',
            'unit_name','quantity_requested','quantity_supplied',
            'quantity_ordered','quantity_received'
        ]].copy()
        view['quantity_to_produce'] = (
            pd.to_numeric(view['quantity_requested'], errors='coerce').fillna(0)
            - pd.to_numeric(view['quantity_supplied'], errors='coerce').fillna(0)
        ).clip(lower=0)
        view['outstanding_order'] = (
            pd.to_numeric(view['quantity_ordered'], errors='coerce').fillna(0)
            - pd.to_numeric(view['quantity_received'], errors='coerce').fillna(0)
        ).clip(lower=0)
        view['Заказать'] = 0.0
        view = view.rename(columns={
            'request_id':'Заявка ID',
            'client_name':'Заказчик',
            'object_name':'Объект',
            'item_name':'Изделие',
            'material_name':'Материал',
            'unit_name':'Единица',
            'quantity_to_produce':'Требуется производству',
            'quantity_supplied':'Уже передано',
            'quantity_ordered':'Заказано у поставщика',
            'quantity_received':'Получено на склад',
            'outstanding_order':'Ожидается',
        })
        first_cols = [
            'Заявка ID','Заказчик','Объект','Изделие','Материал','Единица',
            'Требуется производству','Уже передано','Заказано у поставщика',
            'Получено на склад','Ожидается','Заказать'
        ]
        view = view[first_cols]

        with st.form('production_request_purchase_form', clear_on_submit=False):
            edited = st.data_editor(
                view,
                key='production_request_purchase_editor',
                width='stretch',
                hide_index=True,
                column_config={
                    'Заявка ID': st.column_config.NumberColumn('Заявка ID', disabled=True),
                    'Заказчик': st.column_config.TextColumn('Заказчик', disabled=True),
                    'Объект': st.column_config.TextColumn('Объект', disabled=True),
                    'Изделие': st.column_config.TextColumn('Изделие', disabled=True),
                    'Материал': st.column_config.TextColumn('Материал', disabled=True),
                    'Единица': st.column_config.TextColumn('Единица', disabled=True),
                    'Требуется производству': st.column_config.NumberColumn('Требуется производству', disabled=True, format='%.2f'),
                    'Уже передано': st.column_config.NumberColumn('Уже передано', disabled=True, format='%.2f'),
                    'Заказано у поставщика': st.column_config.NumberColumn('Заказано у поставщика', disabled=True, format='%.2f'),
                    'Получено на склад': st.column_config.NumberColumn('Получено на склад', disabled=True, format='%.2f'),
                    'Ожидается': st.column_config.NumberColumn('Ожидается', disabled=True, format='%.2f'),
                    'Заказать': st.column_config.NumberColumn('Заказать', min_value=0.0, step=0.01, format='%.2f'),
                },
                disabled=[
                    'Заявка ID','Заказчик','Объект','Изделие','Материал','Единица',
                    'Требуется производству','Уже передано','Заказано у поставщика',
                    'Получено на склад','Ожидается'
                ],
            )
            execute = st.form_submit_button('Выполнить', use_container_width=True)

        pending_key = 'pending_production_purchase_order'
        if execute:
            lines = []
            errors = []
            for idx, row in edited.iterrows():
                qty = safe_float(row['Заказать'])
                if qty <= 1e-9:
                    continue
                raw = requests.loc[int(idx)]
                request_id = safe_int(raw['request_id'])
                material_id = safe_int(raw['material_id'])
                material_name = str(raw['material_name'])
                supplier_df = run_query(
                    """
                    SELECT ms.supplier_id, ms.purchase_price, s.name AS supplier_name
                    FROM reklet.material_suppliers ms
                    JOIN reklet.suppliers s ON s.id=ms.supplier_id
                    WHERE ms.material_id=%s
                    ORDER BY ms.is_preferred DESC, ms.id
                    LIMIT 1
                    """,
                    (material_id,),
                    fetch=True,
                )
                if supplier_df.empty:
                    price_df = run_query(
                        'SELECT COALESCE(cost_per_unit,0) AS cost_per_unit FROM reklet.materials WHERE id=%s',
                        (material_id,), fetch=True,
                    )
                    supplier_name = 'ООО «Поставщик»'
                    supplier_id = None
                    unit_price = safe_float(price_df.iloc[0]['cost_per_unit']) if not price_df.empty else 0.0
                else:
                    supplier_id = safe_int(supplier_df.iloc[0]['supplier_id'])
                    supplier_name = str(supplier_df.iloc[0]['supplier_name'])
                    unit_price = safe_float(supplier_df.iloc[0]['purchase_price'])
                lines.append({
                    'request_id': request_id,
                    'material_id': material_id,
                    'material_name': material_name,
                    'supplier_id': supplier_id,
                    'supplier_name': supplier_name,
                    'quantity': qty,
                    'unit_price': unit_price,
                })
            if not lines:
                st.warning('Укажите количество для заказа хотя бы по одной позиции.')
            else:
                st.session_state[pending_key] = lines

        pending = st.session_state.get(pending_key)
        if pending:
            st.markdown('---')
            st.subheader('Подтвердить заказ материалов')
            preview = pd.DataFrame(pending)[[
                'material_name','supplier_name','quantity','unit_price'
            ]].copy()
            preview.columns = ['Материал','Поставщик','Количество','Цена']
            st.dataframe(preview, width='stretch', hide_index=True)
            c1, c2 = st.columns(2)
            with c1:
                confirm = st.button('Подтвердить заказ', key='confirm_production_purchase_order', type='primary', use_container_width=True)
            with c2:
                cancel = st.button('Отмена', key='cancel_production_purchase_order', use_container_width=True)
            if cancel:
                st.session_state.pop(pending_key, None)
                st.rerun()
            if confirm:
                grouped = {}
                for line in pending:
                    grouped.setdefault(line['supplier_id'], []).append(line)
                statements = []
                for sid, lines in grouped.items():
                    if sid is None:
                        for line in lines:
                            statements.append((
                                """
                                WITH existing_supplier AS (
                                    SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1
                                ), created_supplier AS (
                                    INSERT INTO reklet.suppliers(name,type,category,conditions)
                                    SELECT %s,'material_supplier','Служебный','Условный поставщик для заказов производства'
                                    WHERE NOT EXISTS (SELECT 1 FROM existing_supplier)
                                    RETURNING id
                                ), supplier AS (
                                    SELECT id FROM existing_supplier
                                    UNION ALL SELECT id FROM created_supplier
                                    LIMIT 1
                                ), new_po AS (
                                    INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                                    SELECT id,'ordered','Заказ материалов по заявке производства' FROM supplier
                                    RETURNING id
                                )
                                INSERT INTO reklet.purchase_order_items(
                                    purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price,production_request_id
                                )
                                SELECT id,NULL,%s,%s,0,%s,%s FROM new_po
                                """,
                                ('ООО «Поставщик»','ООО «Поставщик»',line['material_id'],line['quantity'],line['unit_price'],line['request_id'])
                            ))
                            statements.append((
                                "UPDATE reklet.material_production_requests SET status='purchasing',updated_at=timezone('utc'::text,now()) WHERE id=%s",
                                (line['request_id'],),
                            ))
                    else:
                        for line in lines:
                            statements.append((
                                """
                                WITH new_po AS (
                                    INSERT INTO reklet.purchase_orders(supplier_id,status,notes)
                                    VALUES (%s,'ordered','Заказ материалов по заявке производства')
                                    RETURNING id
                                )
                                INSERT INTO reklet.purchase_order_items(
                                    purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price,production_request_id
                                )
                                SELECT id,NULL,%s,%s,0,%s,%s FROM new_po
                                """,
                                (sid,line['material_id'],line['quantity'],line['unit_price'],line['request_id'])
                            ))
                            statements.append((
                                "UPDATE reklet.material_production_requests SET status='purchasing',updated_at=timezone('utc'::text,now()) WHERE id=%s",
                                (line['request_id'],),
                            ))
                run_transaction(statements)
                st.session_state.pop(pending_key, None)
                st.session_state.pop('production_request_purchase_editor', None)
                st.success('Заказ материалов для производства создан.')
                st.rerun()

        st.markdown('---')
        st.subheader('Выполнить заказ производства')

        # Передача возможна не только из материалов, которые пришли по этой
        # закупке. Любой фактический остаток на общем складе можно передать
        # производству. Поэтому заявка может исполняться частями.
        ready = requests.copy()
        ready['stock_available'] = pd.to_numeric(ready['stock_quantity'], errors='coerce').fillna(0.0).clip(lower=0)
        ready['supplied_total'] = pd.to_numeric(ready['quantity_supplied'], errors='coerce').fillna(0.0)
        ready['requested_total'] = pd.to_numeric(ready['quantity_requested'], errors='coerce').fillna(0.0)
        ready['request_remaining'] = (ready['requested_total'] - ready['supplied_total']).clip(lower=0)

        if ready.empty:
            st.info('Открытых заявок производства нет.')
        else:
            second = ready[[
                'request_id','client_name','object_name','item_name','material_name','unit_name',
                'requested_total','supplied_total','request_remaining','stock_available'
            ]].copy()
            second['Передать в производство'] = 0.0
            second.columns = [
                'Заявка ID','Заказчик','Объект','Изделие','Материал','Единица',
                'Заказано производством','Уже передано','Осталось по заявке','Свободно на складе',
                'Передать в производство'
            ]

            with st.form('production_request_issue_form', clear_on_submit=False):
                issue_edit = st.data_editor(
                    second,
                    key='production_request_issue_editor',
                    width='stretch',
                    hide_index=True,
                    column_config={
                        'Заявка ID': st.column_config.NumberColumn('Заявка ID', disabled=True),
                        'Заказчик': st.column_config.TextColumn('Заказчик', disabled=True),
                        'Объект': st.column_config.TextColumn('Объект', disabled=True),
                        'Изделие': st.column_config.TextColumn('Изделие', disabled=True),
                        'Материал': st.column_config.TextColumn('Материал', disabled=True),
                        'Единица': st.column_config.TextColumn('Единица', disabled=True),
                        'Заказано производством': st.column_config.NumberColumn('Заказано производством', disabled=True, format='%.2f'),
                        'Уже передано': st.column_config.NumberColumn('Уже передано', disabled=True, format='%.2f'),
                        'Осталось по заявке': st.column_config.NumberColumn('Осталось по заявке', disabled=True, format='%.2f'),
                        'Свободно на складе': st.column_config.NumberColumn('Свободно на складе', disabled=True, format='%.2f'),
                        'Передать в производство': st.column_config.NumberColumn('Передать в производство', min_value=0.0, step=0.01, format='%.2f'),
                    },
                    disabled=[
                        'Заявка ID','Заказчик','Объект','Изделие','Материал','Единица',
                        'Заказано производством','Уже передано','Осталось по заявке','Свободно на складе'
                    ],
                )
                execute_issue = st.form_submit_button('Выполнить', use_container_width=True)

            pending_issue_key = 'pending_production_issue'
            if execute_issue:
                issue_lines = []
                errors = []
                totals_by_material = {}

                for idx, row in issue_edit.iterrows():
                    qty = safe_float(row['Передать в производство'])
                    if qty <= 1e-9:
                        continue
                    raw = ready.iloc[int(idx)]
                    request_remaining = max(safe_float(raw['request_remaining']), 0.0)
                    stock_available = max(safe_float(raw['stock_available']), 0.0)
                    material_id = safe_int(raw['material_id'])
                    totals_by_material[material_id] = totals_by_material.get(material_id, 0.0) + qty
                    issue_lines.append({
                        'request_id': safe_int(raw['request_id']),
                        'object_id': safe_int(raw['object_id']),
                        'material_id': material_id,
                        'material_name': str(raw['material_name']),
                        'object_name': str(raw['object_name']),
                        'requested_remaining': request_remaining,
                        'quantity': qty,
                        'stock_available': stock_available,
                        'unit_name': str(raw['unit_name'] or ''),
                    })

                # Several open requests may reference the same material.
                # Validate the whole batch against the real stock so one
                # material cannot be issued twice from the same remaining balance.
                stock_by_material = {}
                for _, raw in ready.iterrows():
                    mid = safe_int(raw['material_id'])
                    stock_by_material[mid] = max(safe_float(raw['stock_quantity']), 0.0)
                for mid, total in totals_by_material.items():
                    available = stock_by_material.get(mid, 0.0)
                    if total > available + 1e-9:
                        material_name = next(
                            (x['material_name'] for x in issue_lines if x['material_id'] == mid),
                            str(mid),
                        )
                        unit_name = next(
                            (x['unit_name'] for x in issue_lines if x['material_id'] == mid),
                            '',
                        )
                        errors.append(
                            f"{material_name}: суммарная передача {_format_qty(total)} {unit_name}, "
                            f"а на складе только {_format_qty(available)} {unit_name}."
                        )

                if not issue_lines:
                    st.warning('Укажите количество для передачи хотя бы по одной заявке.')
                elif errors:
                    st.error('Передача не выполнена:\n' + '\n'.join(errors))
                else:
                    st.session_state[pending_issue_key] = issue_lines

            pending_issue = st.session_state.get(pending_issue_key)
            if pending_issue:
                st.markdown('---')
                st.subheader('Подтверждение передачи в производство')
                preview = pd.DataFrame(pending_issue)[[
                    'material_name','object_name','quantity','requested_remaining'
                ]].copy()
                preview.columns = ['Материал','Объект','Передать','Осталось по заявке']
                preview['Передать'] = preview['Передать'].map(_format_qty)
                preview['Осталось по заявке'] = preview['Осталось по заявке'].map(_format_qty)
                st.dataframe(preview, width='stretch', hide_index=True)
                c1,c2=st.columns(2)
                with c1:
                    confirm_issue=st.button('Подтвердить',key='confirm_production_issue',type='primary',use_container_width=True)
                with c2:
                    cancel_issue=st.button('Отмена',key='cancel_production_issue',use_container_width=True)
                if cancel_issue:
                    st.session_state.pop(pending_issue_key,None)
                    st.rerun()
                if confirm_issue:
                    statements=[]
                    for line in pending_issue:
                        to_object=min(line['quantity'], line['requested_remaining'])
                        excess=max(line['quantity']-to_object,0.0)
                        if to_object>1e-9:
                            statements.extend([
                                (
                                    "INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",
                                    (line['material_id'],line['object_id'],to_object),
                                ),
                                (
                                    "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                                    (to_object,line['material_id']),
                                ),
                            ])
                        if excess>1e-9:
                            statements.extend([
                                (
                                    "INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,NULL,'production_transfer',%s,'OUT')",
                                    (line['material_id'],excess),
                                ),
                                (
                                    "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",
                                    (excess,line['material_id']),
                                ),
                            ])
                        supplied_increment=to_object
                        if supplied_increment>1e-9:
                            statements.append((
                                "UPDATE reklet.material_production_requests SET quantity_supplied=LEAST(quantity_requested,quantity_supplied+%s),status=CASE WHEN quantity_supplied+%s>=quantity_requested THEN 'completed' ELSE 'ready' END,updated_at=timezone('utc'::text,now()) WHERE id=%s",
                                (supplied_increment,supplied_increment,line['request_id']),
                            ))
                    if statements:
                        run_transaction(statements)
                    st.session_state.pop(pending_issue_key,None)
                    st.session_state.pop('production_request_issue_editor',None)
                    st.success('Материалы переданы в производство. Заявка останется открытой до полного исполнения; излишки учтены отдельно.')
                    st.rerun()

def render_warehouse():

    ensure_task_three_tables()
    st.header("Склад материалов")

    # Только шесть актуальных разделов. Дополнительный блок
    # «Заказ с производства» не является пунктом навигации и рисуется
    # ниже этих шести кнопок, поэтому при входе в склад всегда видно ровно
    # шесть пунктов меню.
    # callback, поэтому нет промежуточного рендера старого набора кнопок.
    material_sections = (
        ("Перечень материалов", "list"),
        ("Потребность материалов", "planning"),
        ("Закупка материалов", "purchase"),
        ("Приход материалов", "receipt"),
        ("Выдача материалов в производство", "issue"),
        ("Движение материалов", "movement"),
    )

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

    # Заявки производства показываются непосредственно под шестью кнопками
    # навигации и над содержимым выбранного раздела. Блок полностью скрыт,
    # если открытых заявок нет.
    _render_production_requests_expander()

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
            # Do not expose floating-point artefacts such as 0.000002 in
            # the user-facing material register. Quantity values are shown
            # with at most two decimals; underlying DB values stay numeric.
            display["Цена за единицу"] = pd.to_numeric(
                display["Цена за единицу"], errors="coerce"
            ).fillna(0.0).map(lambda v: f"{v:.2f}")
            display["На складе"] = display["На складе"].map(_format_qty)
            display["Коэффициент отходов"] = pd.to_numeric(
                display["Коэффициент отходов"], errors="coerce"
            ).fillna(0.0).map(lambda v: f"{v:.2f}")

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

        # --------------------------------------------------------
        # ИЗЛИШКИ НА ПРОИЗВОДСТВЕ — ОБЩИЙ ОСТАТОК
        # Всегда после перечня материалов.
        # --------------------------------------------------------
        st.markdown("---")
        st.subheader("Излишки на производстве")
        list_excess = _get_production_excess_rows()
        if list_excess.empty:
            st.info("Излишков на производстве нет.")
        else:
            excess_view = list_excess[["material_id","material_name","unit_name","excess_quantity"]].copy()
            excess_view.columns = ["ID","Материал","Единица","Излишки на производстве"]
            excess_view["Излишки на производстве"] = excess_view["Излишки на производстве"].map(_format_qty)
            st.dataframe(excess_view, width="stretch", hide_index=True)
            render_print_html("Излишки на производстве", excess_view, "print_production_excess_list")

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
        openp=run_query(
            """
            SELECT
                poi.id AS purchase_item_id,
                po.id AS purchase_order_id,
                s.id AS supplier_id,
                s.name AS supplier_name,
                poi.production_request_id,
                o.id AS object_id,
                o.object_name,
                c.name AS client_name,
                m.id AS material_id,
                m.name AS material_name,
                u.name AS unit_name,
                poi.quantity_ordered,
                poi.quantity_received,
                GREATEST(poi.quantity_ordered-poi.quantity_received,0) AS remaining_quantity,
                poi.unit_price
            FROM reklet.purchase_order_items poi
            JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
            JOIN reklet.suppliers s ON s.id=po.supplier_id
            LEFT JOIN reklet.objects o ON o.id=poi.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            JOIN reklet.materials m ON m.id=poi.material_id
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            WHERE po.status<>'cancelled'
              AND poi.quantity_received<poi.quantity_ordered
            ORDER BY po.id DESC,COALESCE(o.object_name,'Общий склад'),m.name
            LIMIT 500
            """,
            fetch=True,
        )
        if openp.empty:
            st.info("Ожидающих закупок для прихода нет.")
        else:
            edf=openp[[
                "purchase_item_id","purchase_order_id","supplier_name","client_name","object_name",
                "material_name","unit_name","quantity_ordered","quantity_received","remaining_quantity","unit_price","production_request_id"
            ]].copy()
            edf["object_name"]=edf["object_name"].fillna("Общий склад")
            edf.insert(0,"Выбрать",False)
            edf["Принять"]=0.0
            edf.columns=[
                "Выбрать","ID позиции","№ закупки","Поставщик","Заказчик","Объект",\
                "Материал","Единица","Заказано","Получено","Осталось","Цена","Заявка производства","Принять"
            ]
            with st.form("purchase_receipt_form",clear_on_submit=False):
                edited=st.data_editor(
                    edf,
                    key="purchase_receipt_editor",
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "ID позиции":st.column_config.NumberColumn("ID позиции",disabled=True),
                        "№ закупки":st.column_config.NumberColumn("№ закупки",disabled=True),
                        "Поставщик":st.column_config.TextColumn("Поставщик",disabled=True),
                        "Заказчик":st.column_config.TextColumn("Заказчик",disabled=True),
                        "Объект":st.column_config.TextColumn("Объект",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Единица":st.column_config.TextColumn("Единица",disabled=True),
                        "Заказано":st.column_config.NumberColumn("Заказано",disabled=True,format="%.2f"),
                        "Получено":st.column_config.NumberColumn("Получено",disabled=True,format="%.2f"),
                        "Осталось":st.column_config.NumberColumn("Осталось",disabled=True,format="%.2f"),
                        "Цена":st.column_config.NumberColumn("Цена",disabled=True,format="%.2f"),
                        "Заявка производства":st.column_config.NumberColumn("Заявка производства",disabled=True),
                        "Принять":st.column_config.NumberColumn("Принять",min_value=0.0,step=0.01,format="%.2f"),
                    },
                    disabled=[
                        "ID позиции","№ закупки","Поставщик","Заказчик","Объект","Материал","Единица",
                        "Заказано","Получено","Осталось","Цена","Заявка производства"
                    ],
                )
                execute=st.form_submit_button("Оформить приход",use_container_width=True)
            if execute:
                selected=edited[edited["Выбрать"].fillna(False)&(pd.to_numeric(edited["Принять"],errors="coerce").fillna(0)>0)].copy()
                errors=[]; statements=[]
                for idx,row in selected.iterrows():
                    raw=openp.loc[int(idx)]
                    qty=safe_float(row["Принять"]); rem=safe_float(row["Осталось"])
                    if qty>rem+1e-9:
                        errors.append(f"{row['Материал']} / закупка №{safe_int(row['№ закупки'])}: можно принять максимум {rem:.2f}.")
                        continue
                    statements.extend([
                        (
                            "INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",
                            (safe_int(raw["material_id"]),safe_int(raw["supplier_id"]),safe_int(raw["object_id"]) if pd.notna(raw["object_id"]) else None,qty,safe_float(raw["unit_price"])),
                        ),
                        ("UPDATE reklet.purchase_order_items SET quantity_received=quantity_received+%s WHERE id=%s",(qty,safe_int(raw["purchase_item_id"]))),
                        ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,safe_int(raw["material_id"]))),
                    ])
                    req_id=safe_int(raw["production_request_id"]) if pd.notna(raw["production_request_id"]) else None
                    if req_id:
                        statements.append((
                            "UPDATE reklet.material_production_requests SET status='ready',updated_at=timezone('utc'::text,now()) WHERE id=%s AND status IN ('sent','purchasing','ready')",
                            (req_id,),
                        ))
                for po_id in sorted({safe_int(openp.loc[int(i),"purchase_order_id"]) for i in selected.index}):
                    statements.append((
                        """
                        UPDATE reklet.purchase_orders po
                        SET status=CASE
                            WHEN NOT EXISTS(
                                SELECT 1 FROM reklet.purchase_order_items poi
                                WHERE poi.purchase_order_id=po.id AND poi.quantity_received<poi.quantity_ordered
                            ) THEN 'received'
                            WHEN EXISTS(
                                SELECT 1 FROM reklet.purchase_order_items poi
                                WHERE poi.purchase_order_id=po.id AND poi.quantity_received>0
                            ) THEN 'partial'
                            ELSE 'ordered'
                        END
                        WHERE po.id=%s
                        """,
                        (po_id,),
                    ))
                if selected.empty:
                    st.warning("Выберите позиции и укажите количество принятого материала.")
                elif errors:
                    st.error("Приход не выполнен:\n"+"\n".join(errors))
                else:
                    run_transaction(statements)
                    st.success("Приход оформлен. Материал добавлен на общий склад.")
                    st.session_state.pop("purchase_receipt_editor",None)
                    st.rerun()

        st.markdown("---")
        with st.expander("Приход без предварительной закупки"):
            suppliers=get_suppliers(); smap={str(r["name"]):int(r["id"]) for _,r in suppliers.iterrows()} if not suppliers.empty else {}
            filter_category_col, filter_supplier_col = st.columns(2, gap="small")
            with filter_category_col:
                cat_options=["Все категории","Без категории"]+(categories["name"].astype(str).tolist() if not categories.empty else []); cat=st.selectbox("Категория материала",cat_options,key="manual_receipt_category")
            manual=materials.copy()
            if cat=="Без категории": manual=manual[manual["category_id"].isna()].copy()
            elif cat!="Все категории": manual=manual[manual["category_name"].fillna("").astype(str).eq(cat)].copy()
            mdf=manual[["id","name","unit_name"]].copy(); mdf.insert(0,"Выбрать",False); mdf["Количество"]=0.0; mdf["Цена"]=0.0; mdf.columns=["Выбрать","ID","Материал","Единица","Количество","Цена"]
            default_supplier_name="ООО «Поставщик»"
            supplier_options=[default_supplier_name]+list(smap.keys()) if default_supplier_name not in smap else list(smap.keys())
            with filter_supplier_col:
                supplier=st.selectbox("Поставщик",supplier_options,key="manual_receipt_supplier")
            with st.form("manual_receipt_form",clear_on_submit=False):
                edited=st.data_editor(mdf,key="manual_receipt_editor",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Количество":st.column_config.NumberColumn("Количество",min_value=0.0,step=0.01,format="%.2f"),"Цена":st.column_config.NumberColumn("Цена",min_value=0.0,step=0.01,format="%.2f")},disabled=["ID","Материал","Единица"])
                execute=st.form_submit_button("Выполнить приход",use_container_width=True)
            if execute:
                sel=edited[edited["Выбрать"].fillna(False)&(edited["Количество"].fillna(0)>0)].copy()
                if sel.empty: st.warning("Выберите материалы и укажите количество.")
                else:
                    sid=smap.get(supplier)
                    if sid is None and supplier==default_supplier_name:
                        existing_default=run_query("SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1",(default_supplier_name,),fetch=True)
                        if existing_default.empty:
                            created_default=run_query("""INSERT INTO reklet.suppliers(name,type,category,conditions) VALUES (%s,'material_supplier','Служебный','Условный поставщик по умолчанию') RETURNING id""",(default_supplier_name,),fetch=True)
                            sid=safe_int(created_default.iloc[0]["id"])
                        else: sid=safe_int(existing_default.iloc[0]["id"])
                    statements=[]
                    for _,row in sel.iterrows():
                        mid=safe_int(row["ID"]); qty=safe_float(row["Количество"]); price=safe_float(row["Цена"])
                        statements.extend([
                            ("INSERT INTO reklet.material_transactions(material_id,supplier_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,'purchase',%s,%s,'IN')",(mid,sid,qty,price)),
                            ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,mid)),
                            ("INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",(mid,sid,price)),
                        ])
                    run_transaction(statements); st.success(f"Приход выполнен: {len(sel)} поз."); st.session_state.pop("manual_receipt_editor",None); st.rerun()
        history=run_query("""SELECT mt.created_at AS \"Дата\",s.name AS \"Поставщик\",o.object_name AS \"Объект\",m.name AS \"Материал\",u.name AS \"Единица\",mt.quantity AS \"Количество\",mt.unit_price AS \"Цена\",mt.quantity*COALESCE(mt.unit_price,0) AS \"Сумма\" FROM reklet.material_transactions mt LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id LEFT JOIN reklet.objects o ON o.id=mt.object_id JOIN reklet.materials m ON m.id=mt.material_id LEFT JOIN reklet.units u ON u.id=m.unit_id WHERE mt.operation_type='purchase' AND mt.transaction_type='IN' ORDER BY mt.created_at DESC LIMIT 500""",fetch=True)
        st.markdown("---")
        st.subheader("История прихода материалов")
        if not history.empty:
            st.dataframe(history,width="stretch",hide_index=True)
            render_print_html("Ведомость прихода материалов",history,"print_material_receipt_history")

    elif active_material_section=="issue":
        st.subheader("Выдача материалов в производство")
        object_id,object_row=warehouse_select_object("material_issue")
        excess_map=_get_production_excess_map()

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
                issue["global_excess"]=issue["material_id"].map(excess_map).fillna(0.0)
                issue["issue_remaining_need"]=(issue["remaining_need"]-issue["global_excess"]).clip(lower=0)
                if scope=="Только необходимые для объекта":
                    issue=issue[issue["issue_remaining_need"]>1e-9].copy()
                if issue.empty:
                    st.info("Материалов для выбранного отбора нет.")
                else:
                    idf=issue[[
                        "material_id","material_name","unit_name","stock_quantity",
                        "required_quantity","issued_quantity","issue_remaining_need","global_excess"
                    ]].copy()
                    idf.insert(0,"Выбрать",False)
                    idf["Выдать"]=0.0
                    idf.columns=[
                        "Выбрать","ID","Материал","Единица","На складе",
                        "Потребность объекта","Выдано","Осталось потребно","Излишки на производстве","Выдать"
                    ]
                    with st.form(f"issue_materials_form_{object_id}",clear_on_submit=False):
                        edited=st.data_editor(
                            idf,key=f"issue_materials_editor_{object_id}_{scope}",width="stretch",hide_index=True,
                            column_config={
                                "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                                "ID":st.column_config.NumberColumn("ID",disabled=True),
                                "Материал":st.column_config.TextColumn("Материал",disabled=True),
                                "Единица":st.column_config.TextColumn("Единица",disabled=True),
                                "На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.2f"),
                                "Потребность объекта":st.column_config.NumberColumn("Потребность объекта",disabled=True,format="%.2f"),
                                "Выдано":st.column_config.NumberColumn("Выдано",disabled=True,format="%.2f"),
                                "Осталось потребно":st.column_config.NumberColumn("Осталось потребно",disabled=True,format="%.2f"),
                                "Излишки на производстве":st.column_config.NumberColumn("Излишки на производстве",disabled=True,format="%.2f"),
                                "Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.01,format="%.2f")
                            },
                            disabled=["ID","Материал","Единица","На складе","Потребность объекта","Выдано","Осталось потребно","Излишки на производстве"]
                        )
                        execute=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
                    if execute:
                        selected=edited[edited["Выбрать"].fillna(False)&(pd.to_numeric(edited["Выдать"],errors="coerce").fillna(0)>0)].copy()
                        errors=[]; statements=[]
                        for _,row in selected.iterrows():
                            mid=safe_int(row["ID"]); qty=safe_float(row["Выдать"]); stock=safe_float(row["На складе"]); need=safe_float(row["Осталось потребно"])
                            if qty>stock+1e-9:
                                errors.append(f"{row['Материал']}: на складе только {stock:.2f}.")
                            to_object=min(max(need,0.0),qty)
                            excess=max(qty-to_object,0.0)
                            if qty>stock+1e-9:
                                continue
                            if to_object>1e-9:
                                statements.extend([
                                    ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,object_id,to_object)),
                                    ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(to_object,mid)),
                                ])
                            if excess>1e-9:
                                statements.extend([
                                    ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,NULL,'production_transfer',%s,'OUT')",(mid,excess)),
                                    ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(excess,mid)),
                                ])
                        if selected.empty:
                            st.warning("Выберите материалы и укажите количество.")
                        elif errors:
                            st.error("Выдача не выполнена:\n"+"\n".join(errors))
                        elif statements:
                            run_transaction(statements)
                            st.success("Материалы выданы в производство. Излишки учтены отдельно.")
                            st.session_state.pop(f"issue_materials_editor_{object_id}_{scope}",None)
                            st.rerun()
                        else:
                            st.info("Нет допустимых изменений.")

        # ------------------------------------------------------------
        # ИЗЛИШКИ НА ПРОИЗВОДСТВЕ — ОБЩИЙ ОСТАТОК
        # ------------------------------------------------------------
        excess_rows=run_query(
            """
            SELECT
                m.id AS material_id,m.name AS material_name,u.name AS unit_name,
                GREATEST(
                    COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.material_id=m.id AND mt.object_id IS NULL AND mt.operation_type='production_transfer' AND mt.transaction_type='OUT'),0)
                    - COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.material_id=m.id AND mt.operation_type='production_allocation' AND mt.transaction_type='IN'),0)
                    - COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.material_id=m.id AND mt.object_id IS NULL AND mt.operation_type='production_return' AND mt.transaction_type='IN'),0)
                    - COALESCE((SELECT SUM(mw.quantity) FROM reklet.material_waste_transactions mw WHERE mw.material_id=m.id AND mw.object_id IS NULL AND mw.source_type='production'),0),0
                ) AS excess_quantity
            FROM reklet.materials m
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            ORDER BY m.name
            """,fetch=True
        )
        excess_rows["excess_quantity"]=pd.to_numeric(excess_rows["excess_quantity"],errors="coerce").fillna(0.0) if not excess_rows.empty else pd.Series(dtype=float)
        excess_rows=excess_rows[excess_rows["excess_quantity"]>1e-9].copy() if not excess_rows.empty else excess_rows
        st.markdown("---")
        st.subheader("Излишки на производстве")
        if excess_rows.empty:
            st.info("Излишков на производстве нет.")
        else:
            excess_editor=excess_rows[["material_id","material_name","unit_name","excess_quantity"]].copy()
            excess_editor.insert(0,"Выбрать",False)
            excess_editor["Вернуть количество"]=0.0
            excess_editor.columns=["Выбрать","ID","Материал","Единица","Излишки всего","Вернуть количество"]
            with st.form("production_excess_return_form",clear_on_submit=False):
                edited_excess=st.data_editor(
                    excess_editor,key="production_excess_return_editor",width="stretch",hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "ID":st.column_config.NumberColumn("ID",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Единица":st.column_config.TextColumn("Единица",disabled=True),
                        "Излишки всего":st.column_config.NumberColumn("Излишки всего",disabled=True,format="%.2f"),
                        "Вернуть количество":st.column_config.NumberColumn("Вернуть количество",min_value=0.0,step=0.01,format="%.2f")
                    },
                    disabled=["ID","Материал","Единица","Излишки всего"]
                )
                request_return=st.form_submit_button("Вернуть на склад",use_container_width=True)
            if request_return:
                selected_return=edited_excess[edited_excess["Выбрать"].fillna(False)&(pd.to_numeric(edited_excess["Вернуть количество"],errors="coerce").fillna(0)>0)].copy()
                errors=[]; pending=[]
                for idx,row in selected_return.iterrows():
                    raw=excess_rows.iloc[int(idx)]; qty=safe_float(row["Вернуть количество"]); available=safe_float(row["Излишки всего"]);
                    if qty>available+1e-9:
                        errors.append(f"{row['Материал']}: вернуть можно максимум {available:.2f}.")
                    else:
                        pending.append({"material_id":safe_int(raw["material_id"]),"material_name":str(raw["material_name"]),"unit_name":str(raw["unit_name"] or ''),"quantity":qty})
                if selected_return.empty:
                    st.warning("Выберите материал и укажите количество.")
                elif errors:
                    st.error("Возврат не подготовлен:\n"+"\n".join(errors))
                else:
                    st.session_state["pending_production_excess_return"]=pending
            pending=st.session_state.get("pending_production_excess_return")
            if pending:
                st.markdown("#### Подтверждение возврата на склад")
                confirm_df=pd.DataFrame(pending)
                confirm_df.columns=["ID материала","Материал","Единица","Количество"]
                st.dataframe(confirm_df,width="stretch",hide_index=True)
                c1,c2=st.columns(2)
                with c1:
                    confirm_return=st.button("Подтвердить",key="confirm_production_excess_return",use_container_width=True)
                with c2:
                    cancel_return=st.button("Отмена",key="cancel_production_excess_return",use_container_width=True)
                if cancel_return:
                    st.session_state.pop("pending_production_excess_return",None)
                    st.rerun()
                if confirm_return:
                    statements=[]
                    for line in pending:
                        price_df=run_query("SELECT COALESCE(cost_per_unit,0) AS cost FROM reklet.materials WHERE id=%s",(line["material_id"],),fetch=True)
                        price=safe_float(price_df.iloc[0]["cost"]) if not price_df.empty else 0.0
                        statements.extend([
                            ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,NULL,'production_return',%s,%s,'IN')",(line["material_id"],line["quantity"],price)),
                            ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(line["quantity"],line["material_id"]))
                        ])
                    run_transaction(statements)
                    st.session_state.pop("pending_production_excess_return",None)
                    st.session_state.pop("production_excess_return_editor",None)
                    st.success("Излишки возвращены на склад.")
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
    if active_material_section == "planning":
        render_page_instruction("planning")
    elif active_material_section == "purchase":
        render_page_instruction("purchase")
    elif active_material_section == "issue":
        render_page_instruction("issue")
    else:
        render_page_instruction("materials")




    # ============================================================
