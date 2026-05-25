"""Streamlit: purchase history lookup by Item code."""

from __future__ import annotations

import streamlit as st

from production.page_submaingroup import render_submaingroup_lookup

st.set_page_config(page_title="Jacktech Purchase", layout="wide", page_icon="🏭")

st.markdown("### Jacktech Hyd")

render_submaingroup_lookup()
