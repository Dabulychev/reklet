from core.db import run_query


def get_clients():

    return run_query(
        """
        SELECT
            id,
            name,
            phone,
            address,
            email,
            website,
            notes,
            contact_info
        FROM reklet.clients
        ORDER BY name
        """,
        fetch=True
    )
