from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
THREE = Decimal("3")
FIVE = Decimal("5")
TWENTY = Decimal("20")
FRACTION_2_3 = TWO / THREE


def as_decimal(value: Any) -> Decimal:
    if value is None:
        return ZERO
    try:
        return Decimal(str(value))
    except Exception:
        return ZERO


def round_minutes(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_production_minutes(unit_material_cost: Any, quantity: Any) -> dict[str, Decimal | str]:
    """Calculate production time by cumulative quantity bands.

    Base time per item is half of the current material cost per one item.
    Quantity bands are cumulative:
      1-5   -> x1.5
      6-20  -> x1
      21+   -> x2/3
    """
    cost = max(as_decimal(unit_material_cost), ZERO)
    qty = max(as_decimal(quantity), ZERO)
    qty_int = int(qty)
    base_per_item = cost / TWO

    first_band = min(qty_int, 5)
    second_band = min(max(qty_int - 5, 0), 15)
    third_band = max(qty_int - 20, 0)

    first_minutes = Decimal(first_band) * base_per_item * Decimal("1.5")
    second_minutes = Decimal(second_band) * base_per_item * ONE
    third_minutes = Decimal(third_band) * base_per_item * FRACTION_2_3
    total = first_minutes + second_minutes + third_minutes

    if qty_int <= 0:
        quantity_class = "Нет количества"
        multiplier = ONE
    elif qty_int <= 5:
        quantity_class = "1-5"
        multiplier = Decimal("1.5")
    elif qty_int <= 20:
        quantity_class = "6-20"
        multiplier = ONE
    else:
        quantity_class = "21+"
        multiplier = FRACTION_2_3

    return {
        "unit_cost": round_minutes(cost),
        "quantity": Decimal(qty_int),
        "base_production_minutes": round_minutes(base_per_item),
        "quantity_class": quantity_class,
        "time_multiplier": round_minutes(multiplier),
        "production_minutes": round_minutes(total),
        "installation_minutes": round_minutes(total / TWO),
    }


def calculate_transport_minutes(distance_km: Any) -> dict[str, Decimal]:
    """Calculate whole-object transport time from distance only.

    Loading = 240 min, unloading = 240 min.
    Road time is at least 240 min; every km above 120 adds 3 min.
    """
    distance = max(as_decimal(distance_km), ZERO)
    loading = Decimal("240")
    unloading = Decimal("240")
    road = Decimal("240") if distance <= Decimal("120") else Decimal("240") + (distance - Decimal("120")) * THREE
    total = loading + road + unloading
    return {
        "distance_km": distance,
        "loading_minutes": loading,
        "road_minutes": round_minutes(road),
        "unloading_minutes": unloading,
        "transport_minutes": round_minutes(total),
    }


def calculate_time_snapshot(rows: list[dict[str, Any]], distance_km: Any) -> dict[str, Any]:
    """Calculate a complete planning snapshot for one object."""
    items: list[dict[str, Any]] = []
    production_total = ZERO
    installation_total = ZERO

    for row in rows:
        quantity = as_decimal(row.get("quantity_needed"))
        if quantity <= 0:
            continue

        item = calculate_production_minutes(row.get("material_unit_cost"), quantity)
        item_row = {
            **row,
            "quantity": int(item["quantity"]),
            "unit_cost": item["unit_cost"],
            "base_production_minutes": item["base_production_minutes"],
            "quantity_class": item["quantity_class"],
            "time_multiplier": item["time_multiplier"],
            "production_minutes": item["production_minutes"],
            "installation_minutes": item["installation_minutes"],
        }
        items.append(item_row)
        production_total += item["production_minutes"]
        installation_total += item["installation_minutes"]

    transport = calculate_transport_minutes(distance_km)
    total = production_total + installation_total + transport["transport_minutes"]

    return {
        "items": items,
        "production_minutes": round_minutes(production_total),
        "installation_minutes": round_minutes(installation_total),
        "transport": transport,
        "transport_minutes": round_minutes(transport["transport_minutes"]),
        "total_minutes": round_minutes(total),
    }
