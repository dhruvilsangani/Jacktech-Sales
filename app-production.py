"""Streamlit: item-code quantity ranking and month-wise quantity lookup."""

from __future__ import annotations

import altair as alt
import streamlit as st
from streamlit_searchbox import st_searchbox

from common.sales_register import (
    ITEM_CODE_COL,
    QUANTITY_COL,
    default_excel_path,
    item_code_quantity_rank_and_options,
    monthly_quantity_by_item_code,
)

MAX_SEARCH_RESULTS = 50

st.set_page_config(page_title="Jacktech Production", layout="wide", page_icon="🏭")

st.markdown("### Jacktech Hyd — Production")

excel_path = default_excel_path()
if not excel_path.is_file():
    st.error(f"Missing data file: `{excel_path}`")
    st.stop()

st.subheader("Top 5 item codes by quantity")
st.caption(
    f"Ranked by total **{QUANTITY_COL}** in the register (normalized **{ITEM_CODE_COL}**). "
    "These codes also appear first in the dropdown below."
)

top5, code_options = item_code_quantity_rank_and_options(excel_path, top_n=5)
if top5.empty or not code_options:
    st.warning("No item-level quantity data found (check `Item_code` / `Invoice Qty` in the register).")
else:
    for i, row in top5.iterrows():
        st.markdown(f"**{i + 1}.** `{row[ITEM_CODE_COL]}` — **{row['Quantity']:,.2f}**")

st.markdown("---")
st.subheader("Quantity sold by month (single item)")
st.caption(
    f"Choose an **{ITEM_CODE_COL}** from the register."
)

_options_with_norm = [(c, c.lower()) for c in code_options]
_default_top5 = code_options[:5]


def _search_item_codes(searchterm: str) -> list[str]:
    """Case-insensitive **prefix** match across all item codes (empty term → top 5 by qty)."""
    q = (searchterm or "").strip().lower()
    if not q:
        return _default_top5
    matches = [code for code, lc in _options_with_norm if lc.startswith(q)]
    return matches[:MAX_SEARCH_RESULTS]


chosen = st_searchbox(
    _search_item_codes,
    placeholder="Type a prefix (e.g. 1P-)",
    # label=f"{ITEM_CODE_COL} (from register)",
    default_options=_default_top5,
    rerun_on_update=True,
    key="production_item_search",
    help=(
        f"Prefix-search across **{len(code_options):,}** codes "
        f"(showing up to {MAX_SEARCH_RESULTS} matches). "
        "Clear the box to see the top 5 by total quantity."
    ),
)

if chosen:
    monthly_q = monthly_quantity_by_item_code(excel_path, chosen)
    if monthly_q is None or monthly_q.empty:
        st.warning(f"No dated rows for `{chosen}`.")
    else:
        resolved = monthly_q["Quantity"].sum()
        st.caption(
            f"**{len(monthly_q):,}** months with sales; "
            f"total **{QUANTITY_COL}**: **{resolved:,.2f}**."
        )
        x_sort = alt.SortField("PeriodOrd", order="ascending")
        qty_chart = (
            alt.Chart(monthly_q)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#9467bd")
            .encode(
                x=alt.X(
                    "MonthLabel:O",
                    sort=x_sort,
                    title="Month",
                    axis=alt.Axis(labelAngle=-45, labelOverlap="greedy"),
                ),
                y=alt.Y("Quantity:Q", title="Quantity sold"),
                tooltip=[
                    alt.Tooltip("MonthLabel:O", title="Month"),
                    alt.Tooltip("Quantity:Q", format=",.2f", title="Quantity"),
                ],
            )
            .properties(height=320, title=f"Month-wise quantity — {chosen!r}")
        )
        st.altair_chart(qty_chart, use_container_width=True)

        with st.expander("Monthly quantity table"):
            show = monthly_q[["MonthLabel", "Quantity"]].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)
