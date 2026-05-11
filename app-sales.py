"""Streamlit: GSTIN drilldown and portfolio overview in one page (tabs)."""

from __future__ import annotations

import streamlit as st

from sales.page_data_insights import render_data_overview
from sales.page_sales_history import render_sales_history

st.set_page_config(page_title="Jacktech Sales", layout="wide", page_icon="📊")

st.markdown("### Jacktech Hyd")

tab_gstin, tab_data = st.tabs(["GSTIN view", "Data overview"])
with tab_gstin:
    render_sales_history()
with tab_data:
    render_data_overview()
