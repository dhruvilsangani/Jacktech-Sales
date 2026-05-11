"""GSTIN sales history dashboard (tab content)."""

from __future__ import annotations

import altair as alt
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from common.sales_register import (
    AGG_COL,
    CUSTOMER_COL,
    GST_COL,
    INVOICE_DATE_COL,
    ITEM_CODE_COL,
    PRODUCT_COL,
    columns_of_interest,
    default_excel_path,
    discount_table_between_fy,
    gst_subset,
    revenue_by_fy_and_month,
    top_products_lifetime_monthly_revenue,
)


def render_sales_history() -> None:
    st.title("Sales History")
    st.caption(
        "Financial years are **Apr–Mar** (e.g. FY23-24 = Apr 2023–Mar 2024). "
        "Click an FY bar for month-wise revenue in FY order (Apr → Mar)."
    )

    excel_path = default_excel_path()
    if not excel_path.is_file():
        st.error(f"Missing data file: `{excel_path}`")
        return

    gstin = st.text_input(
        "GSTIN",
        placeholder="e.g. 24ADGFS4973B1Z4",
        help="Matched exactly after trimming spaces; case-insensitive.",
        key="sales_history_gstin",
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
        .properties(height=260, title="FY-wise revenue")
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
            key="sales_history_fy_from",
        )
    with c2:
        last_fy_start = st.number_input(
            "To FY (April year)",
            min_value=2000,
            max_value=2100,
            value=2026,
            step=1,
            help="Inclusive range on FY start year (same convention as From).",
            key="sales_history_fy_to",
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
