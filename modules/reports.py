from html import escape

import pandas as pd
import streamlit as st

from core.db import run_query
from core.formatting import money
from core.printing import printable_html, render_print_html
from database.migrations import ensure_material_planning_tables


def movement_options(movements, column, first_label="Все"):
    vals = (
        movements[column]
        .fillna("")
        .astype(str)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    return [first_label] + vals

def render_reports():


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
