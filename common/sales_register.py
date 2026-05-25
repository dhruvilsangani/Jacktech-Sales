"""Shared sales register loading and derived metrics (cached)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

EXCEL_NAME = "df-sales.xlsx"
INVOICE_NO_COL = "Invoice_No."
INVOICE_DATE_COL = "Invoice Date"
STANDARD_RATE_COL = "Standard Rate"
INVOICE_RATE_COL = "Invoice Rate"
QUANTITY_COL = "Invoice Qty"
DISCOUNT_COL = "Disc.Per"
TRANSPORTER_NAME_COL = "TransporterName"
DESTINATION_COL = "Destination"
ITEM_CODE_COL = "Item_code"
AGG_COL = "Amount"
PRODUCT_COL = "SubMainGroup"
GST_COL = "Gst_No"
CUSTOMER_COL = "SupplierName"
SALES_PERSON_COL = "Salesperson"
columns_of_interest = [
    INVOICE_NO_COL,
    INVOICE_DATE_COL,
    ITEM_CODE_COL,
    PRODUCT_COL,
    QUANTITY_COL,
    STANDARD_RATE_COL,
    INVOICE_RATE_COL,
    DISCOUNT_COL,
    TRANSPORTER_NAME_COL,
    DESTINATION_COL,
]


def default_excel_path() -> Path:
    """Path to ``df-sales.xlsx`` at repository root (sibling of ``common``)."""
    EXCEL_NAME = "df-sales.xlsx"
    return Path(__file__).resolve().parent.parent / EXCEL_NAME


@st.cache_data(show_spinner="Loading sales register…")
def load_sales_register(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df[INVOICE_DATE_COL] = pd.to_datetime(df[INVOICE_DATE_COL], errors="coerce")
    df[AGG_COL] = pd.to_numeric(df[AGG_COL], errors="coerce").fillna(0)
    df[GST_COL] = df[GST_COL].astype(str).str.strip().str.upper()
    df = df[df[GST_COL].notna() & (df[GST_COL] != "NAN")]
    df[PRODUCT_COL] = df[PRODUCT_COL].astype(str).str.strip()

    inv = df["Invoice Date"]
    ok = inv.notna()
    y = inv.dt.year
    mo = inv.dt.month
    df["Year"] = y
    df["MonthNum"] = mo
    df["Month"] = inv.dt.strftime("%b")

    # Indian FY: April (start year Y) → March (Y+1), label FY{YY}-{YY+1}
    df["FY_Start"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    df.loc[ok, "FY_Start"] = y[ok].to_numpy() - (mo[ok] < 4).to_numpy().astype(np.int64)
    fs = df["FY_Start"]
    df["FY"] = pd.Series(pd.NA, index=df.index, dtype=object)
    fmask = fs.notna()
    yy = fs[fmask].astype(np.int64)
    df.loc[fmask, "FY"] = (
        "FY"
        + (yy % 100).astype(str).str.zfill(2)
        + "-"
        + ((yy + 1) % 100).astype(str).str.zfill(2)
    )
    # Order months within FY: Apr=1 … Mar=12
    df["FY_MonthOrd"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    m = mo[ok].to_numpy().astype(np.int64)
    df.loc[ok, "FY_MonthOrd"] = np.where(m >= 4, m - 3, m + 9)

    return df


@st.cache_data
def gst_subset(path: Path, gstin: str) -> pd.DataFrame:
    """Single filtered slice per GSTIN; cache key is path + string (not the full DataFrame)."""
    gst_key = gstin.strip().upper()
    if not gst_key:
        return pd.DataFrame()
    df = load_sales_register(path)
    return df.loc[df[GST_COL] == gst_key].copy()


@st.cache_data
def revenue_by_fy_and_month(path: Path, gstin: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    gst_key = gstin.strip().upper()
    if not gst_key:
        return None

    d = gst_subset(path, gst_key)
    if d.empty:
        return None

    d = d[d[INVOICE_DATE_COL].notna() & d["FY_Start"].notna()]
    if d.empty:
        return None

    fy_totals = (
        d.groupby(["FY", "FY_Start"], observed=True)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
        .sort_values("FY_Start")
    )

    monthly_observed = (
        d.groupby(["FY", "FY_Start", "FY_MonthOrd", "Month"], observed=True)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
        .sort_values(["FY_Start", "FY_MonthOrd"])
    )
    month_order = pd.DataFrame(
        {
            "FY_MonthOrd": list(range(1, 13)),
            "Month": ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"],
        }
    )
    fy_keys = fy_totals[["FY", "FY_Start"]].drop_duplicates()
    monthly_template = (
        fy_keys.assign(_key=1)
        .merge(month_order.assign(_key=1), on="_key", how="inner")
        .drop(columns="_key")
    )
    monthly = (
        monthly_template.merge(
            monthly_observed[["FY", "FY_Start", "FY_MonthOrd", "Revenue"]],
            on=["FY", "FY_Start", "FY_MonthOrd"],
            how="left",
        )
        .sort_values(["FY_Start", "FY_MonthOrd"])
        .reset_index(drop=True)
    )

    if not fy_totals.empty:
        fy_totals["FY_Start"] = fy_totals["FY_Start"].astype(int)
    if not monthly.empty:
        monthly["FY_Start"] = monthly["FY_Start"].astype(int)
        monthly["FY_MonthOrd"] = monthly["FY_MonthOrd"].astype(int)

    return fy_totals, monthly


@st.cache_data
def top_products_lifetime_monthly_revenue(
    path: Path, gstin: str, top_n: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Top products by lifetime revenue; one bar per calendar month–year present in data (chronological)."""
    gst_key = gstin.strip().upper()
    if not gst_key:
        return None

    d = gst_subset(path, gst_key)
    if d.empty:
        return None

    d = d[d[INVOICE_DATE_COL].notna() & d["FY_Start"].notna()].copy()
    prod = d[PRODUCT_COL].astype(str).str.strip()
    d = d[(prod != "") & (prod.str.lower() != "nan")].copy()
    if d.empty:
        return None

    top_products = (
        d.groupby(PRODUCT_COL, observed=True)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
        .sort_values("Revenue", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    if top_products.empty:
        return None

    top_list = top_products[PRODUCT_COL].tolist()
    d_top = d[d[PRODUCT_COL].isin(top_list)].copy()

    inv = pd.to_datetime(d_top[INVOICE_DATE_COL], errors="coerce")
    d_top = d_top.assign(_cal_yr=inv.dt.year, _cal_mo=inv.dt.month)
    d_top = d_top[d_top["_cal_yr"].notna() & d_top["_cal_mo"].notna()].copy()
    if d_top.empty:
        return None

    observed = (
        d_top.groupby([PRODUCT_COL, "_cal_yr", "_cal_mo"], observed=True)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
    )

    ym_pairs = (
        d_top[["_cal_yr", "_cal_mo"]]
        .drop_duplicates()
        .sort_values(["_cal_yr", "_cal_mo"])
        .reset_index(drop=True)
    )
    ym_pairs["PeriodOrd"] = ym_pairs["_cal_yr"].astype(np.int64) * 12 + ym_pairs["_cal_mo"].astype(
        np.int64
    )
    ym_pairs["PeriodLabel"] = pd.to_datetime(
        ym_pairs["_cal_yr"].astype(str) + "-" + ym_pairs["_cal_mo"].astype(str) + "-01",
        errors="coerce",
    ).dt.strftime("%b %Y")

    product_keys = pd.DataFrame({PRODUCT_COL: top_list})
    template = (
        product_keys.assign(_k=1)
        .merge(ym_pairs.assign(_k=1), on="_k", how="inner")
        .drop(columns="_k")
    )

    monthly_lifetime = (
        template.merge(
            observed,
            on=[PRODUCT_COL, "_cal_yr", "_cal_mo"],
            how="left",
        )
        .sort_values([PRODUCT_COL, "PeriodOrd"])
        .reset_index(drop=True)
    )
    monthly_lifetime["PeriodOrd"] = monthly_lifetime["PeriodOrd"].astype(int)

    return top_products, monthly_lifetime


@st.cache_data
def discount_table_between_fy(
    path: Path,
    gstin: str,
    first_fy_start: int,
    last_fy_start: int,
) -> pd.DataFrame | None:
    """Discount table by FY start year (e.g. 2024 -> FY24-25)."""
    gst_key = gstin.strip().upper()
    if not gst_key:
        return None

    lo = min(first_fy_start, last_fy_start)
    hi = max(first_fy_start, last_fy_start)

    d = gst_subset(path, gst_key)
    if d.empty:
        return None

    d = d[d[INVOICE_DATE_COL].notna() & d["FY_Start"].notna()]
    d = d[(d["FY_Start"] >= lo) & (d["FY_Start"] <= hi)]
    if d.empty:
        return None

    keep_cols = [c for c in columns_of_interest if c in d.columns]
    out = d[keep_cols + ["FY"]].copy()
    out[INVOICE_DATE_COL] = pd.to_datetime(out[INVOICE_DATE_COL], errors="coerce")
    out[ITEM_CODE_COL] = out[ITEM_CODE_COL].apply(lambda x: "" if pd.isna(x) else str(x))
    return out.sort_values(INVOICE_DATE_COL).reset_index(drop=True)


def _nunique_dropped_na(s: pd.Series) -> int:
    return int(s.dropna().nunique())


def _item_code_match_key(x) -> str:
    """Normalize item codes for matching (Excel may store codes as int/float or string)."""
    if x is None:
        return ""
    if isinstance(x, str):
        s = x.strip()
        if not s or s.lower() in ("nan", "none"):
            return ""
    else:
        if isinstance(x, float) and (np.isnan(x) or not np.isfinite(x)):
            return ""
        if isinstance(x, (int, np.integer)):
            return str(int(x))
        if isinstance(x, float) and x == int(x):
            return str(int(x))
        s = str(x).strip()
        if not s or s.lower() in ("nan", "none"):
            return ""
    try:
        f = float(s.replace(",", ""))
        if np.isfinite(f) and f == int(f):
            return str(int(f))
    except ValueError:
        pass
    return s


@st.cache_data(show_spinner="Computing item monthly quantities…")
def monthly_quantity_by_item_code(path: Path, item_code: str) -> pd.DataFrame | None:
    """Calendar-month sums of ``Invoice Qty`` for rows whose ``Item_code`` matches ``item_code`` (trimmed / normalized)."""
    query_key = _item_code_match_key(item_code)
    if not query_key:
        return None

    df = load_sales_register(path)
    if ITEM_CODE_COL not in df.columns or QUANTITY_COL not in df.columns:
        return None

    ic = df[ITEM_CODE_COL].map(_item_code_match_key)
    d = df.loc[ic == query_key].copy()
    if d.empty:
        return None

    d = d[d[INVOICE_DATE_COL].notna()].copy()
    if d.empty:
        return None

    q = pd.to_numeric(d[QUANTITY_COL], errors="coerce").fillna(0)
    d = d.assign(_qty=q)
    d["_period"] = d[INVOICE_DATE_COL].dt.to_period("M")
    out = (
        d.groupby("_period", observed=False)["_qty"]
        .sum()
        .reset_index(name="Quantity")
    )
    ts = out["_period"].dt.to_timestamp()
    out["MonthLabel"] = ts.dt.strftime("%b %Y")
    out["PeriodOrd"] = (ts.dt.year.astype(np.int64) * 12 + ts.dt.month.astype(np.int64)).astype(int)
    return out.sort_values("PeriodOrd").reset_index(drop=True)


@st.cache_data(show_spinner="Computing item code quantity stats…")
def item_code_quantity_rank_and_options(path: Path, top_n: int = 5) -> tuple[pd.DataFrame, list[str]]:
    """Top ``top_n`` rows by total ``Invoice Qty`` (normalized ``Item_code``), plus select order.

    Returns ``(top_df, options)`` where ``top_df`` has ``Item_code`` and ``Quantity`` columns, and
    ``options`` lists every distinct code with the top ``top_n`` by quantity first, then the rest sorted A–Z.
    """
    df = load_sales_register(path)
    if ITEM_CODE_COL not in df.columns or QUANTITY_COL not in df.columns:
        return pd.DataFrame(), []

    ic = df[ITEM_CODE_COL].map(_item_code_match_key)
    d = df.assign(_icode=ic)
    d = d[d["_icode"] != ""].copy()
    if d.empty:
        return pd.DataFrame(), []

    q = pd.to_numeric(d[QUANTITY_COL], errors="coerce").fillna(0)
    d = d.assign(_qty=q)

    totals = (
        d.groupby("_icode", observed=True)["_qty"]
        .sum()
        .reset_index(name="Quantity")
        .sort_values("Quantity", ascending=False)
    )
    top_df = totals.head(int(top_n)).copy().reset_index(drop=True)
    top_df = top_df.rename(columns={"_icode": ITEM_CODE_COL})

    top_ids = top_df[ITEM_CODE_COL].tolist()
    top_set = set(top_ids)
    all_sorted = sorted(d["_icode"].unique().tolist())
    rest = [c for c in all_sorted if c not in top_set]
    options = top_ids + rest

    return top_df, options


@st.cache_data(show_spinner="Computing portfolio monthly metrics…")
def monthly_portfolio_metrics(path: Path) -> pd.DataFrame:
    """Calendar month aggregates across the full register (all GSTINs)."""
    df = load_sales_register(path)
    df = df[df[INVOICE_DATE_COL].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["_period"] = df[INVOICE_DATE_COL].dt.to_period("M")
    sn = df[CUSTOMER_COL].astype(str).str.strip()
    sn = sn.where(~sn.str.lower().isin(["", "nan", "none"]), pd.NA)
    df = df.assign(_supplier_clean=sn)

    out = (
        df.groupby("_period", observed=False)
        .agg(
            UniqueCustomersGST=(GST_COL, pd.Series.nunique),
            UniqueSupplierNames=("_supplier_clean", _nunique_dropped_na),
            TotalRevenue=(AGG_COL, "sum"),
            InvoiceLines=(AGG_COL, "count"),
        )
        .reset_index()
    )
    ts = out["_period"].dt.to_timestamp()
    out["MonthLabel"] = ts.dt.strftime("%b %Y")
    out["PeriodOrd"] = (ts.dt.year.astype(np.int64) * 12 + ts.dt.month.astype(np.int64)).astype(int)
    return out.sort_values("PeriodOrd").reset_index(drop=True)


@st.cache_data(show_spinner="Computing top products by month…")
def top_products_monthly_portfolio(path: Path, top_n: int = 5) -> tuple[pd.DataFrame, list[str]] | None:
    """Top ``top_n`` products by lifetime revenue; month-wise revenue across the full register."""
    df = load_sales_register(path)
    df = df[df[INVOICE_DATE_COL].notna()].copy()
    prod = df[PRODUCT_COL].astype(str).str.strip()
    df = df.loc[(prod != "") & (prod.str.lower() != "nan")].copy()
    if df.empty:
        return None

    lifetime = df.groupby(PRODUCT_COL, observed=True)[AGG_COL].sum().reset_index(name="_life")
    top_products = (
        lifetime.sort_values("_life", ascending=False).head(top_n)[PRODUCT_COL].tolist()
    )
    if not top_products:
        return None

    d_top = df[df[PRODUCT_COL].isin(top_products)].copy()
    d_top["_period"] = d_top[INVOICE_DATE_COL].dt.to_period("M")
    monthly = (
        d_top.groupby(["_period", PRODUCT_COL], observed=False)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
    )
    ts = monthly["_period"].dt.to_timestamp()
    monthly["MonthLabel"] = ts.dt.strftime("%b %Y")
    monthly["PeriodOrd"] = (ts.dt.year.astype(np.int64) * 12 + ts.dt.month.astype(np.int64)).astype(int)
    monthly = monthly.sort_values(["PeriodOrd", PRODUCT_COL]).reset_index(drop=True)
    return monthly, top_products


@st.cache_data(show_spinner="Computing top customers by FY…")
def top_customers_revenue_share_by_fy(path: Path, top_n: int = 5) -> pd.DataFrame:
    """Per FY: top ``top_n`` customers by revenue (``SupplierName``) plus one **Others** bucket.

    Returns columns ``FY``, ``FY_Start``, ``Segment`` (customer name or ``Others``), ``Revenue``.
    Rows with zero **Others** revenue are omitted.
    """
    df = load_sales_register(path)
    df = df[df[INVOICE_DATE_COL].notna() & df["FY_Start"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    sn = df[CUSTOMER_COL].astype(str).str.strip()
    sn = sn.where(~sn.str.lower().isin(["", "nan", "none"]), pd.NA)
    df = df.assign(_customer=sn)
    df = df[df["_customer"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    g = (
        df.groupby(["FY", "FY_Start", "_customer"], observed=True)[AGG_COL]
        .sum()
        .reset_index(name="Revenue")
    )
    g["_rank"] = g.groupby(["FY", "FY_Start"], observed=False)["Revenue"].rank(
        method="first", ascending=False
    )
    g["Segment"] = np.where(g["_rank"] <= top_n, g["_customer"], "Others")
    out = (
        g.groupby(["FY", "FY_Start", "Segment"], observed=False)["Revenue"]
        .sum()
        .reset_index()
    )
    out = out[out["Revenue"] > 0].reset_index(drop=True)
    if not out.empty:
        out["FY_Start"] = out["FY_Start"].astype(int)
    return out
