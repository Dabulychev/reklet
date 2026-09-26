import pandas as pd
import streamlit as st
from html import escape


def printable_html(title, df=None, body_html=None, subtitle=None):
    """Build a self-contained printable HTML document from a dataframe/body."""
    if df is not None:
        if df.empty:
            table_html = "<p>Нет данных для печати.</p>"
        else:
            clean = df.copy()
            for col in clean.columns:
                if pd.api.types.is_datetime64_any_dtype(clean[col]):
                    clean[col] = clean[col].dt.strftime("%d.%m.%Y %H:%M").fillna("")
            clean = clean.where(pd.notna(clean), "")
            table_html = clean.to_html(index=False, border=0, classes="data-table")
    else:
        table_html = body_html or ""

    subtitle_html = f"<p class='subtitle'>{escape(str(subtitle))}</p>" if subtitle else ""
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(str(title))}</title>
<style>
    @page {{ margin: 14mm; }}
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; color: #111; font-size: 12px; }}
    h1 {{ font-size: 20px; margin: 0 0 8px; }}
    .subtitle {{ margin: 0 0 14px; color: #444; }}
    table.data-table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
    table.data-table th, table.data-table td {{ border: 1px solid #777; padding: 5px 7px; text-align: left; vertical-align: top; }}
    table.data-table th {{ background: #eee; font-weight: 700; }}
    .toolbar {{ margin: 0 0 16px; }}
    .print-btn {{ padding: 7px 14px; border: 1px solid #555; background: #f3f3f3; cursor: pointer; }}
    .sign {{ margin-top: 35px; display: flex; justify-content: space-between; gap: 40px; }}
    @media print {{ .toolbar {{ display: none; }} }}
</style>
</head>
<body>
<div class="toolbar"><button class="print-btn" onclick="window.print()">Печать</button></div>
<h1>{escape(str(title))}</h1>
{subtitle_html}
{table_html}
</body>
</html>
"""


def render_print_html(title, df, key, subtitle=None):
    """Render the compact page-level HTML print option."""
    st.download_button(
        "Печать HTML",
        data=printable_html(title, df=df, subtitle=subtitle),
        file_name="".join(
            ch if ch.isalnum() or ch in "_-" else "_"
            for ch in str(title)
        )[:120] + ".html",
        mime="text/html",
        key=key,
        use_container_width=False,
    )
