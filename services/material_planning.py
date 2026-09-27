import pandas as pd

from core.db import run_query
from database.migrations import (
    ensure_material_planning_tables,
    ensure_object_item_material_costs,
)


def get_object_material_planning(object_id):
    """Material demand plus issued/reserved/purchased state for one object."""
    ensure_material_planning_tables()
    ensure_object_item_material_costs(object_id)

    df = run_query(
        """
        WITH demand AS (
            SELECT ptm.material_id,
                   SUM(COALESCE(oi.quantity_needed,0)
                       * COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit,0)
                       * COALESCE(oimc.waste_coefficient, ptm.waste_coefficient,1)) AS required_quantity
            FROM reklet.object_items oi
            JOIN reklet.product_template_materials ptm
              ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
            LEFT JOIN reklet.object_item_material_costs oimc
              ON oimc.object_item_id=oi.id
             AND oimc.material_id=ptm.material_id
            WHERE oi.object_id=%s
            GROUP BY ptm.material_id
        ),
        issued AS (
            SELECT material_id,SUM(quantity) AS issued_quantity
            FROM reklet.material_transactions
            WHERE object_id=%s AND operation_type='production_transfer' AND transaction_type='OUT'
            GROUP BY material_id
        ),
        consumed AS (
            SELECT material_id,SUM(quantity) AS consumed_quantity
            FROM reklet.material_consumption
            WHERE object_id=%s
            GROUP BY material_id
        ),
        reservations AS (
            SELECT material_id,quantity_reserved
            FROM reklet.material_reservations
            WHERE object_id=%s
        ),
        all_reservations AS (
            SELECT material_id,SUM(quantity_reserved) AS total_reserved
            FROM reklet.material_reservations
            GROUP BY material_id
        ),
        open_orders AS (
            SELECT poi.material_id,
                   SUM(GREATEST(poi.quantity_ordered-poi.quantity_received,0)) AS ordered_outstanding
            FROM reklet.purchase_order_items poi
            JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
            WHERE poi.object_id=%s
              AND po.status<>'cancelled'
              AND poi.quantity_received<poi.quantity_ordered
            GROUP BY poi.material_id
        )
        SELECT d.material_id,m.name AS material_name,u.name AS unit_name,
               COALESCE(m.stock_quantity,0) AS stock_quantity,
               COALESCE(d.required_quantity,0) AS required_quantity,
               COALESCE(i.issued_quantity,0) AS issued_quantity,
               COALESCE(c.consumed_quantity,0) AS consumed_quantity,
               GREATEST(COALESCE(i.issued_quantity,0)-COALESCE(c.consumed_quantity,0),0) AS work_in_process_quantity,
               COALESCE(r.quantity_reserved,0) AS reserved_quantity,
               COALESCE(ar.total_reserved,0) AS total_reserved_quantity,
               GREATEST(COALESCE(m.stock_quantity,0)-COALESCE(ar.total_reserved,0),0) AS available_quantity,
               COALESCE(oo.ordered_outstanding,0) AS ordered_outstanding
        FROM demand d
        JOIN reklet.materials m ON m.id=d.material_id
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        LEFT JOIN issued i ON i.material_id=d.material_id
        LEFT JOIN consumed c ON c.material_id=d.material_id
        LEFT JOIN reservations r ON r.material_id=d.material_id
        LEFT JOIN all_reservations ar ON ar.material_id=d.material_id
        LEFT JOIN open_orders oo ON oo.material_id=d.material_id
        ORDER BY m.name
        """,
        (object_id, object_id, object_id, object_id, object_id),
        fetch=True,
    )

    if df.empty:
        return df

    for col in [
        "stock_quantity",
        "required_quantity",
        "issued_quantity",
        "consumed_quantity",
        "work_in_process_quantity",
        "reserved_quantity",
        "total_reserved_quantity",
        "available_quantity",
        "ordered_outstanding",
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        ).fillna(0.0)

    df["remaining_need"] = (
        df["required_quantity"] - df["issued_quantity"]
    ).clip(lower=0)

    df["need_to_buy"] = (
        df["remaining_need"]
        - df["reserved_quantity"]
        - df["ordered_outstanding"]
    ).clip(lower=0)

    return df
