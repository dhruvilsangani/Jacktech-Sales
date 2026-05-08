"""Streamlit: GSTIN revenue dashboard with financial year (Apr–Mar) drilldown."""

from __future__ import annotations

from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

EXCEL_NAME = "Sales Invoice Register 2020-2026 Mitesh 260508.xlsx"
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
    out[INVOICE_DATE_COL] = pd.to_datetime(out[INVOICE_DATE_COL], errors="coerce").dt.date
    out[ITEM_CODE_COL] = out[ITEM_CODE_COL].apply(lambda x: "" if pd.isna(x) else str(x))
    return out.sort_values(INVOICE_DATE_COL).reset_index(drop=True)


def main() -> None:
    st.set_page_config(page_title="Customer History Dashboard", layout="centered")
    st.title("Customer History Dashboard")
    st.caption(
        "Financial years are **Apr–Mar** (e.g. FY23-24 = Apr 2023–Mar 2024). "
        "Click an FY bar for month-wise revenue in FY order (Apr → Mar)."
    )

    base = Path(__file__).resolve().parent
    excel_path = base / EXCEL_NAME
    if not excel_path.is_file():
        st.error(f"Missing data file: `{excel_path}`")
        st.stop()

    gstin = st.text_input(
        "GSTIN",
        placeholder="e.g. 24ADGFS4973B1Z4",
        help="Matched exactly after trimming spaces; case-insensitive.",
    ).strip()

    if not gstin:
        st.info("Enter a GSTIN to view financial-year and monthly revenue.")
        return

    gst_key = gstin.upper()
    result = revenue_by_fy_and_month(excel_path, gst_key)

    if result is None:
        st.warning(f"No invoice lines found for GSTIN `{gst_key}` in the loaded register.")
        return

    fy_totals, monthly = result

    cust = gst_subset(excel_path, gst_key)[CUSTOMER_COL].dropna().astype(str)
    if not cust.empty:
        st.subheader(cust.mode().iloc[0] if len(cust.mode()) else cust.iloc[0])

    default_fy = fy_totals.sort_values("FY_Start").iloc[-1]["FY"]

    fy_pick = alt.selection_point(
        fields=["FY"],
        value=[{"FY": str(default_fy)}],
        on="click",
        empty=False,
    )

    fy_chart = (
        alt.Chart(fy_totals)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "FY:O",
                sort=alt.SortField("FY_Start", order="ascending"),
                title="Financial year",
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y("Revenue:Q", title="Revenue"),
            color=alt.condition(fy_pick, alt.value("#1f77b4"), alt.value("#9ecae1")),
            tooltip=[
                alt.Tooltip("FY:O"),
                alt.Tooltip("FY_Start:O", title="FY starts (April, year)"),
                alt.Tooltip("Revenue:Q", format=",.2f"),
            ],
        )
        .properties(height=260, title=f"FY-wise revenue")
        .add_params(fy_pick)
    )

    monthly_chart = (
        alt.Chart(monthly)
        .transform_filter(fy_pick)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#2ca02c")
        .encode(
            x=alt.X(
                "Month:O",
                sort=alt.SortField("FY_MonthOrd", order="ascending"),
                title="Month (FY order)",
            ),
            y=alt.Y("Revenue:Q", title="Revenue"),
            tooltip=[
                alt.Tooltip("FY:O"),
                alt.Tooltip("Month:O"),
                alt.Tooltip("Revenue:Q", format=",.2f"),
            ],
        )
        .properties(height=260, title="Month-wise revenue (selected FY, Apr → Mar)")
    )

    st.altair_chart(fy_chart & monthly_chart, use_container_width=True)

    with st.expander("Revenue tables"):
        st.markdown("**FY-wise revenue**")
        st.dataframe(fy_totals, use_container_width=True, hide_index=True)
        st.markdown("**Month-wise revenue (within each FY)**")
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Discount table by financial year")

    c1, c2 = st.columns([1, 1])
    with c1:
        first_fy_start = st.number_input(
            "From FY (April year)",
            min_value=2000,
            max_value=2100,
            value=2025,
            step=1,
            help="Calendar year in which the FY starts (April). Example: 2024 -> FY24-25.",
        )
    with c2:
        last_fy_start = st.number_input(
            "To FY (April year)",
            min_value=2000,
            max_value=2100,
            value=2026,
            step=1,
            help="Inclusive range on FY start year (same convention as From).",
        )

    discount_df = discount_table_between_fy(excel_path, gst_key, int(first_fy_start), int(last_fy_start))
    if discount_df is None:
        st.warning("No rows found for this GSTIN in the selected FY range.")
        return

    st.dataframe(discount_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
