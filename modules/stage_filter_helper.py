import pandas as pd
import streamlit as st

from core.db import run_query
from repositories.objects import get_stage_objects


STAGE_CONDITIONS = {
    "production": "COALESCE(oi.qty_new,0) > 0 OR COALESCE(oi.qty_production,0) > 0",
    "finished_goods": "COALESCE(oi.qty_ready,0) > 0",
    "transport": "COALESCE(oi.qty_shipped,0) > COALESCE(oi.qty_arrived,0)",
    "installation": "COALESCE(oi.qty_arrived,0) > 0",
}


def render_stage_object_filters(stage: str, prefix: str):
    """Return only stage-relevant customer/object choices.

    Returns (stage_objects, filtered_objects, selected_client, selected_object_label, object_id).
    The special 'Все объекты' value means: show all currently relevant work for this department.
    """
    if stage not in STAGE_CONDITIONS:
        raise ValueError(f"Unknown work stage: {stage}")

    stage_objects = get_stage_objects(stage).copy()
    if not stage_objects.empty:
        stage_objects = stage_objects.sort_values("id", ascending=False).copy()
        stage_objects["client_name"] = stage_objects["client_name"].fillna("").astype(str).str.strip()
        stage_objects["object_name"] = stage_objects["object_name"].fillna("").astype(str).str.strip()

    if stage_objects.empty:
        return stage_objects, stage_objects, "Все заказчики", "Все объекты", None

    client_options = ["Все заказчики"] + sorted(
        [x for x in stage_objects["client_name"].drop_duplicates().tolist() if x]
    )
    selected_client = st.selectbox(
        "Заказчик",
        client_options,
        index=0,
        key=f"{prefix}_customer_filter",
    )

    filtered_objects = stage_objects.copy()
    if selected_client != "Все заказчики":
        filtered_objects = filtered_objects[
            filtered_objects["client_name"].eq(selected_client)
        ].copy()

    if filtered_objects.empty:
        st.info("У выбранного заказчика нет актуальной работы для этого отдела.")
        return stage_objects, filtered_objects, selected_client, "Все объекты", None

    object_options = [
        f"{int(r['id'])} — {r['object_name']} — {r['client_name']}"
        for _, r in filtered_objects.iterrows()
    ]
    selected_object_label = st.selectbox(
        "Объект",
        ["Все объекты"] + object_options,
        index=0,
        key=f"{prefix}_object_filter",
    )

    if selected_object_label == "Все объекты":
        return stage_objects, filtered_objects, selected_client, selected_object_label, None

    object_id = int(selected_object_label.split(" — ", 1)[0])
    return stage_objects, filtered_objects, selected_client, selected_object_label, object_id


def get_stage_work_items(stage: str, object_ids):
    """Read-only overview rows for all currently relevant items in selected objects."""
    if stage not in STAGE_CONDITIONS:
        raise ValueError(f"Unknown work stage: {stage}")
    object_ids = [int(x) for x in object_ids if x is not None]
    if not object_ids:
        return pd.DataFrame()

    placeholders = ",".join(["%s"] * len(object_ids))
    return run_query(
        f"""
        SELECT
            o.id AS object_id,
            o.object_name,
            c.name AS client_name,
            oi.id,
            oi.item_name,
            COALESCE(oi.quantity_needed,0) AS quantity_needed,
            COALESCE(oi.qty_new,0) AS qty_new,
            COALESCE(oi.qty_production,0) AS qty_production,
            COALESCE(oi.qty_ready,0) AS qty_ready,
            COALESCE(oi.qty_shipped,0) AS qty_shipped,
            COALESCE(oi.qty_arrived,0) AS qty_arrived,
            COALESCE(oi.qty_installing,0) AS qty_installing,
            COALESCE(oi.qty_installed,0) AS qty_installed
        FROM reklet.object_items oi
        JOIN reklet.objects o ON o.id=oi.object_id
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        WHERE oi.object_id IN ({placeholders})
          AND ({STAGE_CONDITIONS[stage]})
        ORDER BY o.id DESC, oi.id
        """,
        tuple(object_ids),
        fetch=True,
    )
