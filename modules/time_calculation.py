from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.printing import printable_html
from database.migrations import ensure_time_calculation_tables
from repositories.time_calculations import (
    delete_time_calculation,
    get_saved_time_calculation_items,
    get_saved_time_calculations,
    get_time_calculation_source,
    save_time_calculation,
)
from services.time_calculation import calculate_time_snapshot


def _as_display_number(value) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _format_minutes(value) -> str:
    """Display minutes as HH:MM; hours are not capped at 24."""
    try:
        total_minutes = int(round(float(value)))
    except Exception:
        total_minutes = 0
    total_minutes = max(total_minutes, 0)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _format_datetime(value) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    try:
        return pd.to_datetime(value).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def _render_saved_detail(calculation_id: int, calculations: pd.DataFrame) -> None:
    header_rows = calculations[calculations["id"] == calculation_id]
    if header_rows.empty:
        st.info("Расчёт не найден.")
        return

    header = header_rows.iloc[0]
    items = get_saved_time_calculation_items(calculation_id)

    st.markdown("### Расчёт времени")
    st.caption(
        f"Заказчик: {str(header.get('client_name') or '')}  |  "
        f"Объект: {str(header.get('object_name') or '')}  |  "
        f"Расстояние: {_as_display_number(header.get('distance_km'))} км"
    )

    rows = []
    for _, item in items.iterrows():
        rows.append(
            {
                "Заказчик": str(header.get("client_name") or ""),
                "Объект": str(header.get("object_name") or ""),
                "Элемент": str(item.get("item_name") or ""),
                "Количество": int(item.get("quantity") or 0),
                "Время производства": _format_minutes(item.get("production_minutes")),
                "Время транспортировки": "",
                "Время монтажа": _format_minutes(item.get("installation_minutes")),
                "Общее время": _format_minutes(
                    float(item.get("production_minutes") or 0)
                    + float(item.get("installation_minutes") or 0)
                ),
            }
        )

    transport_minutes = _as_display_number(header.get("transport_minutes"))
    if rows:
        # Transport belongs to the whole object, not to each individual element.
        # Show it once in the total row to avoid multiplying it by the number of elements.
        total_row = {
            "Заказчик": str(header.get("client_name") or ""),
            "Объект": str(header.get("object_name") or ""),
            "Элемент": "ИТОГО",
            "Количество": int(sum(int(x["Количество"]) for x in rows)),
            "Время производства": _format_minutes(header.get("production_minutes")),
            "Время транспортировки": _format_minutes(transport_minutes),
            "Время монтажа": _format_minutes(header.get("installation_minutes")),
            "Общее время": _format_minutes(header.get("total_minutes")),
        }
        rows.append(total_row)

    detail_view = pd.DataFrame(rows)
    if detail_view.empty:
        st.info("В сохранённом расчёте нет элементов.")
    else:
        st.dataframe(detail_view, width="stretch", hide_index=True)
        st.download_button(
            "Печать",
            data=printable_html(
                "Расчёт времени",
                df=detail_view,
                subtitle=(
                    f"Заказчик: {str(header.get('client_name') or '')}; "
                    f"Объект: {str(header.get('object_name') or '')}"
                ),
            ),
            file_name=f"raschet_vremeni_{calculation_id}.html",
            mime="text/html",
            key=f"time_print_{calculation_id}",
        )


def _render_delete_confirmation(calculation_id: int, calculations: pd.DataFrame) -> None:
    row = calculations[calculations["id"] == calculation_id]
    if row.empty:
        st.session_state.pop("time_delete_pending", None)
        return
    current = row.iloc[0]
    st.warning(
        "Вы уверены, что хотите удалить сохранённый расчёт "
        f"№{calculation_id} — {str(current.get('object_name') or '')}?"
    )
    c1, c2 = st.columns(2)
    with c1:
        confirm = st.button(
            "Подтвердить",
            key=f"time_delete_confirm_{calculation_id}",
            type="primary",
            width="stretch",
        )
    with c2:
        cancel = st.button(
            "Отмена",
            key=f"time_delete_cancel_{calculation_id}",
            width="stretch",
        )

    if cancel:
        st.session_state.pop("time_delete_pending", None)
        st.rerun()

    if confirm:
        delete_time_calculation(calculation_id)
        st.session_state.pop("time_delete_pending", None)
        if st.session_state.get("time_detail_id") == calculation_id:
            st.session_state.pop("time_detail_id", None)
        st.success(f"Расчёт №{calculation_id} удалён.")
        st.rerun()


def render_time_calculation() -> None:
    ensure_time_calculation_tables()
    st.subheader("Расчёт времени")

    source = get_time_calculation_source()
    if source.empty:
        st.info("Нет объектов с заказанным количеством изделий для расчёта времени.")
        return

    customer_names = (
        source["client_name"]
        .fillna("Без заказчика")
        .astype(str)
        .str.strip()
        .replace("", "Без заказчика")
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    filter_customer_col, filter_object_col = st.columns(2, gap="small")
    with filter_customer_col:
        selected_customer = st.selectbox(
            "Заказчик",
            customer_names,
            key="time_calculation_customer",
        )
    customer_source = source[
        source["client_name"].fillna("Без заказчика").astype(str).str.strip().replace("", "Без заказчика")
        == selected_customer
    ].copy()

    object_options = {
        f"{int(row['object_id'])} — {str(row['object_name'] or '').strip()}": int(row["object_id"])
        for _, row in customer_source[["object_id", "object_name"]].drop_duplicates().iterrows()
    }
    if not object_options:
        st.info("Для выбранного заказчика нет объектов с количеством изделий.")
        return

    with filter_object_col:
        selected_object_label = st.selectbox(
            "Объект",
            list(object_options.keys()),
            key="time_calculation_object",
        )
    selected_object_id = object_options[selected_object_label]
    selected_rows = customer_source[customer_source["object_id"] == selected_object_id].copy()
    selected_rows = selected_rows[selected_rows["quantity_needed"] > 0].copy()

    if selected_rows.empty:
        st.info("В выбранном объекте нет положительного количества изделий для расчёта.")
        return

    source_rows = selected_rows.to_dict("records")
    distance_km = selected_rows.iloc[0]["distance_km"]
    snapshot = calculate_time_snapshot(source_rows, distance_km)

    summary_view = pd.DataFrame([
        {
            "Производство": _format_minutes(snapshot["production_minutes"]),
            "Транспортировка": _format_minutes(snapshot["transport_minutes"]),
            "Монтаж": _format_minutes(snapshot["installation_minutes"]),
            "Всего": _format_minutes(snapshot["total_minutes"]),
        }
    ])
    st.dataframe(summary_view, width="stretch", hide_index=True)
    st.caption(
        f"Транспорт: погрузка {_format_minutes(snapshot['transport']['loading_minutes'])} + "
        f"дорога {_format_minutes(snapshot['transport']['road_minutes'])} + "
        f"разгрузка {_format_minutes(snapshot['transport']['unloading_minutes'])}; "
        f"расстояние {_as_display_number(snapshot['transport']['distance_km'])} км."
    )

    if st.button(
        "Сохранить",
        key=f"time_save_{selected_object_id}",
        width="stretch",
    ):
        header = {
            "object_id": selected_object_id,
            "client_name": selected_customer,
            "object_name": str(selected_rows.iloc[0]["object_name"] or "").strip(),
            "distance_km": snapshot["transport"]["distance_km"],
            "loading_minutes": snapshot["transport"]["loading_minutes"],
            "road_minutes": snapshot["transport"]["road_minutes"],
            "unloading_minutes": snapshot["transport"]["unloading_minutes"],
            "production_minutes": snapshot["production_minutes"],
            "installation_minutes": snapshot["installation_minutes"],
            "transport_minutes": snapshot["transport_minutes"],
            "total_minutes": snapshot["total_minutes"],
        }
        try:
            calculation_id = save_time_calculation(header, snapshot["items"])
            st.session_state["time_detail_id"] = calculation_id
            st.success(f"Расчёт №{calculation_id} сохранён.")
            st.rerun()
        except Exception as exc:
            st.error("Не удалось сохранить расчёт времени.")
            st.code(str(exc))

    st.markdown("---")
    st.subheader("Сохранённые расчёты")
    calculations = get_saved_time_calculations()

    if calculations.empty:
        st.info("Сохранённых расчётов пока нет.")
        return

    # Filters apply only to the saved calculations list.
    # "Все заказчики" + "Все объекты" shows the complete history.
    saved_client_values = (
        calculations["client_name"]
        .fillna("Без заказчика")
        .astype(str)
        .str.strip()
        .replace("", "Без заказчика")
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    saved_client_options = ["Все заказчики"] + saved_client_values

    sf1, sf2 = st.columns(2)
    with sf1:
        saved_customer_filter = st.selectbox(
            "Заказчик",
            saved_client_options,
            key="time_saved_filter_customer",
        )

    filtered_for_objects = calculations.copy()
    filtered_for_objects["_client_filter_name"] = (
        filtered_for_objects["client_name"]
        .fillna("Без заказчика")
        .astype(str)
        .str.strip()
        .replace("", "Без заказчика")
    )
    if saved_customer_filter != "Все заказчики":
        filtered_for_objects = filtered_for_objects[
            filtered_for_objects["_client_filter_name"] == saved_customer_filter
        ].copy()

    saved_object_values = (
        filtered_for_objects["object_name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Без названия")
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    with sf2:
        saved_object_filter = st.selectbox(
            "Объект",
            ["Все объекты"] + saved_object_values,
            key="time_saved_filter_object",
        )

    calculations["_client_filter_name"] = (
        calculations["client_name"]
        .fillna("Без заказчика")
        .astype(str)
        .str.strip()
        .replace("", "Без заказчика")
    )
    calculations["_object_filter_name"] = (
        calculations["object_name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Без названия")
    )

    if saved_customer_filter != "Все заказчики":
        calculations = calculations[
            calculations["_client_filter_name"] == saved_customer_filter
        ].copy()
    if saved_object_filter != "Все объекты":
        calculations = calculations[
            calculations["_object_filter_name"] == saved_object_filter
        ].copy()

    calculations = calculations.drop(columns=["_client_filter_name", "_object_filter_name"], errors="ignore")

    if calculations.empty:
        st.info("По выбранным фильтрам сохранённых расчётов нет.")
        return

    header_cols = st.columns([0.45, 1.45, 1.55, 1.0, 0.85, 0.85, 0.75, 0.85, 0.95, 0.85])
    headers = [
        "№", "Заказчик", "Объект", "Дата", "Производство",
        "Транспорт", "Монтаж", "Всего", "", ""
    ]
    for col, label in zip(header_cols, headers):
        with col:
            if label:
                st.markdown(f"**{label}**")

    if "time_detail_id" not in st.session_state:
        st.session_state["time_detail_id"] = None
    if "time_delete_pending" not in st.session_state:
        st.session_state["time_delete_pending"] = None

    for _, row in calculations.iterrows():
        calculation_id = int(row["id"])
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns(
            [0.45, 1.45, 1.55, 1.0, 0.85, 0.85, 0.75, 0.85, 0.95, 0.85]
        )
        with c1:
            st.write(calculation_id)
        with c2:
            st.write(str(row.get("client_name") or ""))
        with c3:
            st.write(str(row.get("object_name") or ""))
        with c4:
            st.write(_format_datetime(row.get("calculated_at")))
        with c5:
            st.write(_format_minutes(row.get("production_minutes")))
        with c6:
            st.write(_format_minutes(row.get("transport_minutes")))
        with c7:
            st.write(_format_minutes(row.get("installation_minutes")))
        with c8:
            st.write(_format_minutes(row.get("total_minutes")))
        with c9:
            if st.button("Подробнее", key=f"time_detail_{calculation_id}", width="stretch"):
                st.session_state["time_detail_id"] = calculation_id
                st.session_state.pop("time_delete_pending", None)
                st.rerun()
        with c10:
            if st.button("Удалить", key=f"time_delete_{calculation_id}", width="stretch"):
                st.session_state["time_delete_pending"] = calculation_id
                st.session_state.pop("time_detail_id", None)
                st.rerun()

    detail_id = st.session_state.get("time_detail_id")
    if detail_id:
        st.markdown("---")
        _render_saved_detail(int(detail_id), calculations)

    delete_id = st.session_state.get("time_delete_pending")
    if delete_id:
        st.markdown("---")
        _render_delete_confirmation(int(delete_id), calculations)
