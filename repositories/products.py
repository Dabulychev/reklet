from core.db import run_query
from database.migrations import ensure_product_category_table


def get_templates():

    return run_query(
        """
        SELECT
            id,
            name,
            type,
            client_name,
            category

        FROM reklet.product_templates

        ORDER BY name
        """,
        fetch=True
    )


def get_product_categories():
    ensure_product_category_table()

    return run_query(
        "SELECT id, name FROM reklet.product_categories ORDER BY name",
        fetch=True
    )


def get_product_category_names():
    cats = get_product_categories()

    return cats["name"].astype(str).tolist() if not cats.empty else []
