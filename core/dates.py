import pandas as pd


def as_date(value):
    if value is None or pd.isna(value):
        return None

    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts.date()
