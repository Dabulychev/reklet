import pandas as pd


def movement_options(movements, column, first_label="Все"):
    vals = (
        movements[column]
        .fillna("")
        .astype(str)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    return [first_label] + vals
