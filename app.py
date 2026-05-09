"""Streamlit: GSTIN revenue dashboard with financial year (Apr–Mar) drilldown."""

from __future__ import annotations

from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

EXCEL_NAME = "df_of_interest.xlsx"
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
    out[INVOICE_DATE_COL] = pd.to_datetime(out[INVOICE_DATE_COL], errors="coerce").dt.date
    out[ITEM_CODE_COL] = out[ITEM_CODE_COL].apply(lambda x: "" if pd.isna(x) else str(x))
    return out.sort_values(INVOICE_DATE_COL).reset_index(drop=True)


def main() -> None:
    st.set_page_config(page_title="Sales History", layout="wide")
    st.title("Sales History")
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
                axis=alt.Axis(labelAngle=0),
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

    lifetime_top = top_products_lifetime_monthly_revenue(excel_path, gst_key, top_n=5)
    if lifetime_top is not None:
        top_products_life, monthly_lifetime = lifetime_top
        product_order_life = top_products_life[PRODUCT_COL].tolist()

        with st.expander("Top 5 products — lifetime month-wise revenue (charts)", expanded=False):
            st.caption(
                "Products ranked by total revenue across all invoices for this customer. "
                "Each chart uses **every calendar month–year** that appears in this customer’s data for the top 5 products; "
                "missing product sales in a period show as no bar."
            )
            st.dataframe(top_products_life, use_container_width=True, hide_index=True)

            product_charts: list[alt.Chart] = []
            for product_name in product_order_life:
                d_prod = monthly_lifetime.loc[monthly_lifetime[PRODUCT_COL] == product_name].copy()
                ch = (
                    alt.Chart(d_prod)
                    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#9467bd")
                    .encode(
                        x=alt.X(
                            "PeriodLabel:O",
                            sort=alt.SortField("PeriodOrd", order="ascending"),
                            title="Month–year",
                            axis=alt.Axis(labelAngle=-45, labelOverlap=False),
                            scale=alt.Scale(paddingInner=0.1, paddingOuter=0.1),
                        ),
                        y=alt.Y("Revenue:Q", title="Revenue"),
                        tooltip=[
                            alt.Tooltip("PeriodLabel:O", title="Period"),
                            alt.Tooltip("Revenue:Q", format=",.2f"),
                        ],
                    )
                    .properties(
                        height=200,
                        title=f"{product_name}",
                    )
                )
                product_charts.append(ch)

            if product_charts:
                combo = product_charts[0]
                for ch in product_charts[1:]:
                    combo = combo & ch
                st.altair_chart(combo, use_container_width=True)

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

    st.caption(
        f"**{len(discount_df):,}** rows loaded. Columns **start fitted** to the grid width; **drag** a column "
        "border wider and the grid **scrolls horizontally** when total width exceeds the view. "
        "Use the **filter row** and column menu for **Starts with** / **Contains** / etc."
    )

    gb = GridOptionsBuilder.from_dataframe(discount_df)
    gb.configure_default_column(
        filter=True,
        sortable=True,
        resizable=True,
        minWidth=90,
    )
    gb.configure_grid_options(
        floatingFilter=True,
        enableCellTextSelection=True,
        ensureDomOrder=True,
        suppressHorizontalScroll=False,
        autoSizeStrategy={"type": "fitGridWidth", "defaultMinWidth": 90},
    )
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=100)
    grid_options = gb.build()

    AgGrid(
        discount_df,
        gridOptions=grid_options,
        height=520,
        theme="streamlit",
        update_mode=GridUpdateMode.NO_UPDATE,
        allow_unsafe_jscode=False,
        key="discount_aggrid",
    )


if __name__ == "__main__":
    main()
