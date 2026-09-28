import pandas as pd

from core.db import run_query
from core.formatting import safe_float, safe_int
from database.migrations import ensure_material_planning_tables, ensure_object_item_material_costs, ensure_task_three_tables


def get_object_material_planning(object_id):
    """Return material demand for an object without changing completed history.

    For the quantity already progressed through production, the frozen
    object_item_material_costs snapshot is authoritative.

    For the quantity that is still new/not produced, the current product
    specification is used. This means a material added to a product later can
    affect future production, but it is never retroactively added to the
    already-produced quantity.
    """
    ensure_material_planning_tables()
    ensure_task_three_tables()
    ensure_object_item_material_costs(object_id)

    df = run_query(
        """
        WITH item_state AS (
            SELECT
                oi.id AS object_item_id,
                oi.quantity_needed,
                GREATEST(COALESCE(oi.qty_new,0),0) AS remaining_qty,
                GREATEST(
                    COALESCE(oi.quantity_needed,0)
                    - COALESCE(oi.qty_new,0),
                    0
                ) AS progressed_qty,
                COALESCE(oi.product_template_id, oi.template_id) AS template_id
            FROM reklet.object_items oi
            WHERE oi.object_id=%s
        ),
        historical_demand AS (
            SELECT
                s.material_id,
                SUM(s.progressed_qty * COALESCE(oimc.quantity_per_unit,0)) AS base_required_quantity,
                SUM(
                    s.progressed_qty
                    * COALESCE(oimc.quantity_per_unit,0)
                    * COALESCE(oimc.waste_coefficient,1)
                ) AS required_quantity
            FROM item_state s
            JOIN reklet.object_item_material_costs oimc
              ON oimc.object_item_id=s.object_item_id
            WHERE s.progressed_qty > 0
            GROUP BY s.material_id
        ),
        future_demand AS (
            SELECT
                ptm.material_id,
                SUM(s.remaining_qty * COALESCE(ptm.quantity_per_unit,0)) AS base_required_quantity,
                SUM(
                    s.remaining_qty
                    * COALESCE(ptm.quantity_per_unit,0)
                    * COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1)
                ) AS required_quantity
            FROM item_state s
            JOIN reklet.product_template_materials ptm
              ON ptm.product_template_id=s.template_id
            JOIN reklet.materials m ON m.id=ptm.material_id
            WHERE s.remaining_qty > 0
            GROUP BY ptm.material_id
        ),
        demand AS (
            SELECT
                material_id,
                SUM(base_required_quantity) AS base_required_quantity,
                SUM(required_quantity) AS required_quantity
            FROM (
                SELECT material_id,base_required_quantity,required_quantity FROM historical_demand
                UNION ALL
                SELECT material_id,base_required_quantity,required_quantity FROM future_demand
            ) x
            GROUP BY material_id
        ),
        issued AS (
            SELECT material_id,SUM(quantity) AS issued_quantity
            FROM reklet.material_transactions
            WHERE object_id=%s
              AND operation_type='production_transfer'
              AND transaction_type='OUT'
            GROUP BY material_id
        ),
        consumed AS (
            SELECT material_id,SUM(quantity) AS consumed_quantity
            FROM reklet.material_consumption
            WHERE object_id=%s
            GROUP BY material_id
        ),
        production_waste AS (
            SELECT material_id,SUM(quantity) AS production_waste_quantity
            FROM reklet.material_waste_transactions
            WHERE object_id=%s AND source_type='production'
            GROUP BY material_id
        ),
        open_orders AS (
            SELECT
                poi.material_id,
                SUM(GREATEST(poi.quantity_ordered-poi.quantity_received,0)) AS ordered_outstanding
            FROM reklet.purchase_order_items poi
            JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
            WHERE poi.object_id=%s
              AND po.status<>'cancelled'
              AND poi.quantity_received<poi.quantity_ordered
            GROUP BY poi.material_id
        )
        SELECT
            d.material_id,
            m.name AS material_name,
            u.name AS unit_name,
            COALESCE(m.stock_quantity,0) AS stock_quantity,
            COALESCE(d.base_required_quantity,0) AS base_required_quantity,
            GREATEST(
                COALESCE(d.required_quantity,0)-COALESCE(d.base_required_quantity,0),
                0
            ) AS waste_quantity,
            COALESCE(d.required_quantity,0) AS required_quantity,
            COALESCE(i.issued_quantity,0) AS issued_quantity,
            COALESCE(c.consumed_quantity,0) AS consumed_quantity,
            GREATEST(
                COALESCE(i.issued_quantity,0)
                - COALESCE(c.consumed_quantity,0)
                - COALESCE(pw.production_waste_quantity,0),
                0
            ) AS work_in_process_quantity,
            COALESCE(oo.ordered_outstanding,0) AS ordered_outstanding,
            COALESCE(pw.production_waste_quantity,0) AS production_waste_quantity
        FROM demand d
        JOIN reklet.materials m ON m.id=d.material_id
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        LEFT JOIN issued i ON i.material_id=d.material_id
        LEFT JOIN consumed c ON c.material_id=d.material_id
        LEFT JOIN production_waste pw ON pw.material_id=d.material_id
        LEFT JOIN open_orders oo ON oo.material_id=d.material_id
        ORDER BY m.name
        """,
        (object_id,object_id,object_id,object_id,object_id),
        fetch=True,
    )

    if df.empty:
        return df

    quantity_columns = [
        "stock_quantity",
        "base_required_quantity",
        "waste_quantity",
        "required_quantity",
        "issued_quantity",
        "consumed_quantity",
        "work_in_process_quantity",
        "ordered_outstanding",
        "production_waste_quantity",
    ]
    for col in quantity_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["remaining_need"] = (
        df["required_quantity"] - df["issued_quantity"]
    ).clip(lower=0)
    df["available_quantity"] = df["stock_quantity"].clip(lower=0)
    df["need_to_buy"] = (
        df["remaining_need"]
        - df["stock_quantity"]
        - df["ordered_outstanding"]
    ).clip(lower=0)

    return df
