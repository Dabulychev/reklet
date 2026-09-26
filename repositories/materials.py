import pandas as pd

from core.db import run_query


def get_materials():

    # Keep this query limited to the core columns used by the product/material picker.
    materials = run_query(
        """
        SELECT
            m.id,
            m.name,
            m.unit_id,
            u.name AS unit_name,
            m.cost_per_unit,
            m.stock_quantity
        FROM reklet.materials m
        LEFT JOIN reklet.units u
            ON u.id = m.unit_id
        ORDER BY m.name
        """,
        fetch=True
    )

    if "default_waste_coefficient" not in materials.columns:
        materials["default_waste_coefficient"] = 1.20

    return materials


def get_materials_with_categories():
    try:
        return run_query(
            """
            SELECT
                m.id,
                m.name,
                m.unit_id,
                u.name AS unit_name,
                m.cost_per_unit,
                m.stock_quantity,
                m.default_waste_coefficient,
                m.category_id,
                mc.name AS category_name
            FROM reklet.materials m
            LEFT JOIN reklet.material_categories mc
                ON mc.id = m.category_id
            LEFT JOIN reklet.units u
                ON u.id = m.unit_id
            ORDER BY m.name
            """,
            fetch=True
        )
    except Exception:
        materials = get_materials().copy()
        materials["category_id"] = None
        materials["category_name"] = None
        return materials


def get_material_categories():
    try:
        return run_query(
            """
            SELECT id, name
            FROM reklet.material_categories
            ORDER BY name
            """,
            fetch=True
        )
    except Exception:
        return pd.DataFrame(columns=["id", "name"])
