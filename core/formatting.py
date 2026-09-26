import pandas as pd


def safe_int(value, default=0):
    try:
        if pd.isna(value):
            return default

        return int(value)

    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default

        return float(value)

    except Exception:
        return default


def money(value):
    try:
        return f"{float(value):,.2f}"

    except Exception:
        return "0.00"
