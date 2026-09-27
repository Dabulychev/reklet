import pandas as pd
import streamlit as st

from core.db import run_query
from core.printing import render_print_html
from database.migrations import ensure_material_planning_tables, ensure_object_item_material_costs

def render_payroll():


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


