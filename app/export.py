"""Export Excel/CSV en mémoire pour bouton download Streamlit."""
from __future__ import annotations

import io

import pandas as pd


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "resultats") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
