from core.db import run_query


def get_objects():

    return run_query(
        """
        SELECT
            o.id,
            o.object_name,
            o.client_id,
            c.name AS client_name,
            o.address,
            o.transport_distance_km,
            o.created_at,
            o.phone,
            o.contact_person,
            o.notes,
            o.contract_date,
            o.production_start_date,
            o.production_end_date,
            o.installation_date,
            o.installation_end_date
        FROM reklet.objects o

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        ORDER BY o.id DESC
        """,
        fetch=True
    )


def get_stage_objects(stage):
    """Объекты только с актуальными изделиями для конкретного этапа."""
    conditions = {
        "production": """
            COALESCE(oi.qty_new, 0) > 0
            OR COALESCE(oi.qty_production, 0) > 0
        """,
        "finished_goods": """
            COALESCE(oi.qty_ready, 0) > 0
        """,
        "transport": """
            COALESCE(oi.qty_shipped, 0) > COALESCE(oi.qty_arrived, 0)
        """,
        "installation": """
            COALESCE(oi.qty_arrived, 0) > 0
        """
    }

    if stage not in conditions:
        raise ValueError(f"Unknown work stage: {stage}")

    return run_query(
        f"""
        SELECT DISTINCT o.id, o.object_name, o.client_id,
               c.name AS client_name, o.address
        FROM reklet.objects o
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        JOIN reklet.object_items oi ON oi.object_id = o.id
        WHERE {conditions[stage]}
        ORDER BY o.id DESC
        """,
        fetch=True
    )
