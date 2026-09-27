import pandas as pd
import streamlit as st

from repositories.clients import get_clients
from repositories.objects import get_objects


def select_object_by_customer(prefix):
    clients = get_clients()
    objects = get_objects().sort_values("id", ascending=False).copy()

    if clients.empty:
        st.info("Заказчики отсутствуют.")
        return None, None
    if objects.empty:
        st.info("Объектов нет.")
        return None, None

    client_rows = clients[["id", "name"]].copy()
    client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
    client_rows = client_rows[client_rows["name"] != ""].drop_duplicates(subset=["id"])
    client_options = [
        f"{int(r['id'])} — {r['name']}"
        for _, r in client_rows.iterrows()
    ]

    selected_client = st.selectbox(
        "Заказчик",
        ["— Выберите заказчика —"] + client_options,
        index=0,
        key=f"{prefix}_customer_select"
    )

    if selected_client == "— Выберите заказчика —":
        st.info("Сначала выберите заказчика.")
        return None, None

    client_id = int(selected_client.split(" — ")[0])
    client_objects = objects[
        pd.to_numeric(objects["client_id"], errors="coerce").eq(client_id)
    ].copy()

    if client_objects.empty:
        st.info("У выбранного заказчика нет объектов.")
        return None, None

    object_options = [
        f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
        for _, r in client_objects.iterrows()
    ]

    selected_object = st.selectbox(
        "Объект",
        ["— Выберите объект —"] + object_options,
        index=0,
        key=f"{prefix}_object_select_{client_id}"
    )

    if selected_object == "— Выберите объект —":
        st.info("Теперь выберите объект.")
        return None, None

    object_id = int(selected_object.split(" — ")[0])
    object_row = client_objects[client_objects["id"] == object_id].iloc[0]
    return object_id, object_row
