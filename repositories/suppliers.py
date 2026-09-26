from core.db import run_query


def get_suppliers():

    return run_query(
        """
        SELECT *
        FROM reklet.suppliers
        ORDER BY name
        """,
        fetch=True
    )
