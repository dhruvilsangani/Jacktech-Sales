"""Portfolio-level metrics (tab content)."""

from __future__ import annotations

import altair as alt
import numpy as np
import streamlit as st

from common.sales_register import (
    PRODUCT_COL,
    default_excel_path,
    monthly_portfolio_metrics,
    top_customers_revenue_share_by_fy,
    top_products_monthly_portfolio,
)


def render_data_overview() -> None:
    st.title("Data overview")
    st.caption(
        "Calendar-month aggregates across **all** rows in the register. "
        "**Unique customers (GST)** counts distinct `Gst_No` values with activity that month; "
        "**Unique supplier names** counts distinct non-empty `SupplierName` values."
    )

    excel_path = default_excel_path()
    if not excel_path.is_file():
        st.error(f"Missing data file: `{excel_path}`")
        return

    m = monthly_portfolio_metrics(excel_path)
    if m.empty:
        st.warning("No dated invoice rows available for overview charts.")
        return

    x_sort = alt.SortField("PeriodOrd", order="ascending")

    cust_chart = (
        alt.Chart(m)
        .mark_line(point=True, color="#1f77b4", strokeWidth=2)
        .encode(
            x=alt.X("MonthLabel:O", sort=x_sort, title="Month", axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
            y=alt.Y("UniqueCustomersGST:Q", title="Count"),
            tooltip=[
                alt.Tooltip("MonthLabel:O", title="Month"),
                alt.Tooltip("UniqueCustomersGST:Q", title="Unique GSTINs", format=",d"),
                alt.Tooltip("UniqueSupplierNames:Q", title="Unique names", format=",d"),
            ],
        )
        .properties(height=280, title="Unique customers per month (by GSTIN)")
    )

    names_chart = (
        alt.Chart(m)
        .mark_area(opacity=0.35, color="#ff7f0e")
        .encode(
            x=alt.X("MonthLabel:O", sort=x_sort, title="Month", axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
            y=alt.Y("UniqueSupplierNames:Q", title="Count"),
            tooltip=[
                alt.Tooltip("MonthLabel:O", title="Month"),
                alt.Tooltip("UniqueSupplierNames:Q", title="Unique supplier names", format=",d"),
            ],
        )
        .properties(height=220, title="Unique supplier names per month")
    )

    rev_chart = (
        alt.Chart(m)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#2ca02c")
        .encode(
            x=alt.X("MonthLabel:O", sort=x_sort, title="Month", axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
            y=alt.Y("TotalRevenue:Q", title="Revenue"),
            tooltip=[
                alt.Tooltip("MonthLabel:O", title="Month"),
                alt.Tooltip("TotalRevenue:Q", format=",.2f"),
                alt.Tooltip("InvoiceLines:Q", title="Invoice lines", format=",d"),
            ],
        )
        .properties(height=280, title="Total revenue per month (all customers)")
    )

    st.altair_chart(cust_chart & names_chart & rev_chart, use_container_width=True)

    top_m = top_products_monthly_portfolio(excel_path, top_n=5)
    if top_m is not None:
        monthly_top, product_order = top_m
        st.subheader("Top 5 products by revenue — month-wise (portfolio)")
        st.caption(
            "Products ranked by **total lifetime revenue** in the register; each chart is **that product’s** "
            "revenue summed across all customers in each calendar month."
        )

        top_charts: list[alt.Chart] = []
        for product_name in product_order:
            d_prod = monthly_top.loc[monthly_top[PRODUCT_COL] == product_name]
            ch = (
                alt.Chart(d_prod)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#9467bd")
                .encode(
                    x=alt.X(
                        "MonthLabel:O",
                        sort=alt.SortField("PeriodOrd", order="ascending"),
                        title="Month",
                        axis=alt.Axis(labelAngle=-45, labelOverlap=False),
                    ),
                    y=alt.Y("Revenue:Q", title="Revenue"),
                    tooltip=[
                        alt.Tooltip("MonthLabel:O", title="Month"),
                        alt.Tooltip("Revenue:Q", format=",.2f"),
                    ],
                )
                .properties(height=200, title=str(product_name))
            )
            top_charts.append(ch)

        combo_top = top_charts[0]
        for ch in top_charts[1:]:
            combo_top = combo_top & ch
        st.altair_chart(combo_top, use_container_width=True)

    st.subheader("Revenue share — top customers vs Others (by FY)")
    pie_top_n = st.slider(
        "Top N customers (by FY revenue); remaining revenue → Others",
        min_value=1,
        max_value=25,
        value=5,
        step=1,
        key="pie_top_customers_n",
    )
    st.caption(
        f"Each financial year (Apr–Mar): **top {pie_top_n}** customers by **that year’s** revenue "
        "(``SupplierName``); remaining revenue is **Others**."
    )
    pie_src = top_customers_revenue_share_by_fy(excel_path, top_n=int(pie_top_n))
    if not pie_src.empty:
        fy_order = pie_src.sort_values("FY_Start", ascending=False)["FY"].unique().tolist()
        sel_fy = st.selectbox("Financial year", fy_order, index=0, key="pie_top_customers_fy")
        d_pie = pie_src.loc[pie_src["FY"] == sel_fy].copy()
        d_pie["_others_last"] = np.where(d_pie["Segment"].eq("Others"), 1, 0)
        d_pie = d_pie.sort_values(["_others_last", "Revenue"], ascending=[True, False]).drop(
            columns="_others_last"
        )

        color_domain = d_pie["Segment"].tolist()
        base_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        color_range = [base_colors[i % len(base_colors)] for i in range(len(color_domain))]
        if "Others" in color_domain:
            color_range[color_domain.index("Others")] = "#bcbd22"

        pie_chart = (
            alt.Chart(d_pie)
            .mark_arc(innerRadius=48, stroke="#fff", strokeWidth=1)
            .encode(
                theta=alt.Theta("Revenue:Q", stack=True),
                color=alt.Color(
                    "Segment:N",
                    scale=alt.Scale(domain=color_domain, range=color_range),
                    legend=alt.Legend(title="Customer"),
                ),
                order=alt.Order("Revenue:Q", sort="descending"),
                tooltip=[
                    alt.Tooltip("Segment:N", title="Customer"),
                    alt.Tooltip("Revenue:Q", format=",.2f", title="Revenue"),
                    alt.Tooltip(
                        "pct:Q",
                        format=".1f",
                        title="% of FY",
                    ),
                ],
            )
            .transform_joinaggregate(total="sum(Revenue)")
            .transform_calculate(pct="100 * datum.Revenue / datum.total")
            .properties(
                width=380,
                height=380,
                title=f"FY revenue mix — {sel_fy} (top {pie_top_n} + Others)",
            )
        )
        st.altair_chart(pie_chart, use_container_width=True)
    else:
        st.warning("No customer-level FY revenue available for the pie chart (check ``SupplierName`` rows).")

    with st.expander("Monthly summary table"):
        show = m[
            [
                "MonthLabel",
                "UniqueCustomersGST",
                "UniqueSupplierNames",
                "TotalRevenue",
                "InvoiceLines",
            ]
        ].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)
