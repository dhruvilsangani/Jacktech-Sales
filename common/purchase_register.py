"""Shared purchase history loading and multi-field filtering (cached)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

EXCEL_NAME = "df-purchase.xlsx"
INVOICE_DATE_COL = "Invoice Date"
INVOICE_RATE_COL = "Invoice Rate"
INVOICE_NO_COL = "Invoice_No."
QUANTITY_COL = "Invoice Qty"
ITEM_CODE_COL = "Item_code"
MAIN_GROUP_COL = "Main Group"
SUPPLIER_COL = "SupplierName"
PRODUCT_COL = "Sub Main Group"


def default_purchase_path() -> Path:
    """Path to ``df-purchase.xlsx`` at repository root (sibling of ``common``)."""
    return Path(__file__).resolve().parent.parent / EXCEL_NAME


@st.cache_data(show_spinner="Loading purchase history…")
def load_purchase_register(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df[INVOICE_DATE_COL] = pd.to_datetime(df[INVOICE_DATE_COL], errors="coerce")

    subgroup = df[PRODUCT_COL] if PRODUCT_COL in df.columns else pd.Series(dtype=object)
    df[PRODUCT_COL] = subgroup.astype(str).str.strip().replace({"nan": pd.NA, "": pd.NA})

    return df


def _col_equals_query(df: pd.DataFrame, column: str, query: str) -> pd.Series:
    """Case-insensitive exact match on trimmed string values."""
    col = df[column].astype(str).str.strip().str.upper()
    return col == query.strip().upper()


def subset_purchase_history(
    df: pd.DataFrame,
    *,
    main_group: str = "",
    submaingroup: str = "",
    item_code: str = "",
) -> pd.DataFrame:
    """Filter purchase rows; non-empty filters are combined with **AND**.

    Returns no rows when all three query strings are empty.
    """
    q_mg = main_group.strip()
    q_smg = submaingroup.strip()
    q_item = item_code.strip()

    if not (q_mg or q_smg or q_item):
        return df.iloc[0:0]

    mask = pd.Series(True, index=df.index)

    if q_mg:
        if MAIN_GROUP_COL not in df.columns:
            return df.iloc[0:0]
        mask &= _col_equals_query(df, MAIN_GROUP_COL, q_mg)

    if q_smg:
        mask &= _col_equals_query(df, PRODUCT_COL, q_smg)

    if q_item:
        if ITEM_CODE_COL not in df.columns:
            return df.iloc[0:0]
        mask &= _col_equals_query(df, ITEM_CODE_COL, q_item)

    return df.loc[mask].copy()


def _distinct_sorted_values(df: pd.DataFrame, column: str) -> list[str]:
    if column not in df.columns or df.empty:
        return []
    values = df[column].astype(str).str.strip()
    values = values[(values != "") & (values.str.lower() != "nan")]
    return sorted(values.unique().tolist())


@st.cache_data(show_spinner=False)
def purchase_filter_options(path: Path) -> dict[str, list[str]]:
    """Distinct values for filter selectboxes (from full purchase register)."""
    df = load_purchase_register(path)
    return {
        "main_group": _distinct_sorted_values(df, MAIN_GROUP_COL),
        "submaingroup": _distinct_sorted_values(df, PRODUCT_COL),
        "item_code": _distinct_sorted_values(df, ITEM_CODE_COL),
    }


def subset_by_submaingroup(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Rows whose SubMainGroup matches ``query`` (case-insensitive, trimmed)."""
    return subset_purchase_history(df, submaingroup=query)


def rows_for_price_scatter(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a valid invoice date and numeric invoice rate (for scatter plots)."""
    out = df.copy()
    out[INVOICE_RATE_COL] = pd.to_numeric(out[INVOICE_RATE_COL], errors="coerce")
    return out.dropna(subset=[INVOICE_DATE_COL, INVOICE_RATE_COL])


def unique_supplier_names(df: pd.DataFrame) -> list[str]:
    """Distinct non-empty ``SupplierName`` values (alphabetical)."""
    ranked = suppliers_by_line_count(df)
    return sorted(name for name, _ in ranked)


def suppliers_by_line_count(df: pd.DataFrame) -> list[tuple[str, int]]:
    """``(SupplierName, line count)`` pairs, descending by purchase lines."""
    if SUPPLIER_COL not in df.columns or df.empty:
        return []
    names = df[SUPPLIER_COL].astype(str).str.strip()
    valid = df.loc[(names != "") & (names.str.lower() != "nan")]
    if valid.empty:
        return []
    counts = valid[SUPPLIER_COL].astype(str).str.strip().value_counts()
    return [(str(name), int(n)) for name, n in counts.items()]
