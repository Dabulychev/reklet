from __future__ import annotations

from typing import Any

import pandas as pd

from core.db import run_query, run_transaction


SOURCE_QUERY = """
SELECT
    o.id AS object_id,
    o.object_name,
    c.name AS client_name,
    COALESCE(o.transport_distance_km, 0) AS distance_km,
    oi.id AS object_item_id,
    oi.item_name,
    COALESCE(oi.quantity_needed, 0) AS quantity_needed,
    COALESCE(
        SUM(
            COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)
            * COALESCE(m.cost_per_unit, 0)
            * COALESCE(
                oimc.waste_coefficient,
                ptm.waste_coefficient,
                m.default_waste_coefficient,
                1
            )
        ),
        0
    ) AS material_unit_cost
FROM reklet.object_items oi
JOIN reklet.objects o
  ON o.id = oi.object_id
LEFT JOIN reklet.clients c
  ON c.id = o.client_id
LEFT JOIN reklet.product_template_materials ptm
  ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
LEFT JOIN reklet.materials m
  ON m.id = ptm.material_id
LEFT JOIN reklet.object_item_material_costs oimc
  ON oimc.object_item_id = oi.id
 AND oimc.material_id = ptm.material_id
WHERE COALESCE(oi.quantity_needed, 0) > 0
GROUP BY
    o.id,
    o.object_name,
    c.name,
    o.transport_distance_km,
    oi.id,
    oi.item_name,
    oi.quantity_needed
ORDER BY c.name, o.object_name, oi.item_name
"""


def get_time_calculation_source() -> pd.DataFrame:
    return run_query(SOURCE_QUERY, fetch=True)


def save_time_calculation(header: dict[str, Any], items: list[dict[str, Any]]) -> int:
    inserted = run_query(
        """
        INSERT INTO reklet.work_time_calculations
        (
            object_id,
            client_name,
            object_name,
            distance_km,
            loading_minutes,
            road_minutes,
            unloading_minutes,
            production_minutes,
            installation_minutes,
            transport_minutes,
            total_minutes
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            int(header["object_id"]),
            str(header.get("client_name") or ""),
            str(header.get("object_name") or ""),
            header["distance_km"],
            header["loading_minutes"],
            header["road_minutes"],
            header["unloading_minutes"],
            header["production_minutes"],
            header["installation_minutes"],
            header["transport_minutes"],
            header["total_minutes"],
        ),
        fetch=True,
    )
    if inserted.empty:
        raise RuntimeError("Не удалось создать расчёт времени.")

    calculation_id = int(inserted.iloc[0]["id"])

    statements = []
    for item in items:
        statements.append(
            (
                """
                INSERT INTO reklet.work_time_calculation_items
                (
                    calculation_id,
                    object_item_id,
                    item_name,
                    quantity,
                    unit_cost,
                    base_production_minutes,
                    quantity_class,
                    time_multiplier,
                    production_minutes,
                    installation_minutes
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    calculation_id,
                    int(item["object_item_id"]),
                    str(item.get("item_name") or ""),
                    int(item["quantity"]),
                    item["unit_cost"],
                    item["base_production_minutes"],
                    str(item["quantity_class"]),
                    item["time_multiplier"],
                    item["production_minutes"],
                    item["installation_minutes"],
                ),
            )
        )

    try:
        if statements:
            run_transaction(statements)
    except Exception:
        try:
            run_query(
                "DELETE FROM reklet.work_time_calculations WHERE id=%s",
                (calculation_id,),
            )
        except Exception:
            pass
        raise

    return calculation_id


def get_saved_time_calculations() -> pd.DataFrame:
    return run_query(
        """
        SELECT
            id,
            object_id,
            client_name,
            object_name,
            distance_km,
            loading_minutes,
            road_minutes,
            unloading_minutes,
            production_minutes,
            installation_minutes,
            transport_minutes,
            total_minutes,
            calculated_at
        FROM reklet.work_time_calculations
        ORDER BY calculated_at DESC, id DESC
        """,
        fetch=True,
    )


def get_saved_time_calculation_items(calculation_id: int) -> pd.DataFrame:
    return run_query(
        """
        SELECT
            calculation_id,
            object_item_id,
            item_name,
            quantity,
            unit_cost,
            base_production_minutes,
            quantity_class,
            time_multiplier,
            production_minutes,
            installation_minutes
        FROM reklet.work_time_calculation_items
        WHERE calculation_id=%s
        ORDER BY id
        """,
        (int(calculation_id),),
        fetch=True,
    )


def delete_time_calculation(calculation_id: int) -> None:
    run_query(
        "DELETE FROM reklet.work_time_calculations WHERE id=%s",
        (int(calculation_id),),
    )
