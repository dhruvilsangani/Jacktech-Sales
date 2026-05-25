"""Item-code purchase history lookup (tab/page content)."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from common.purchase_register import (
    INVOICE_DATE_COL,
    INVOICE_NO_COL,
    INVOICE_RATE_COL,
    ITEM_CODE_COL,
    QUANTITY_COL,
    SUPPLIER_COL,
    default_purchase_path,
    load_purchase_register,
    purchase_filter_options,
    rows_for_price_scatter,
    subset_purchase_history,
    suppliers_by_line_count,
    unique_supplier_names,
)

TOP_SUPPLIERS_N = 10
_FILTER_NONE = "—"


def _invoice_date_year_domain(plot_df: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Jan 1 of min year through Dec 31 of max year (shared x-axis across charts)."""
    dates = plot_df[INVOICE_DATE_COL].dropna()
    if dates.empty:
        year = pd.Timestamp.today().year
        start = pd.Timestamp(year=year, month=1, day=1)
        return start, start + pd.offsets.YearEnd()
    min_year = int(dates.min().year)
    max_year = int(dates.max().year)
    return (
        pd.Timestamp(year=min_year, month=1, day=1),
        pd.Timestamp(year=max_year, month=12, day=31),
    )


def _optional_filter_selectbox(label: str, choices: list[str], key: str) -> str:
    selected = st.selectbox(
        label,
        options=[_FILTER_NONE, *choices],
        index=0,
        help="Leave as — to skip this filter.",
        key=key,
    )
    return "" if selected == _FILTER_NONE else selected


def _supplier_price_scatter_chart(
    plot_df: pd.DataFrame,
    supplier: str,
    *,
    x_domain: tuple[pd.Timestamp, pd.Timestamp],
) -> alt.Chart:
    tooltip = [
        alt.Tooltip(INVOICE_DATE_COL, title="Invoice date", format="%Y-%m-%d"),
        alt.Tooltip(INVOICE_RATE_COL, title="Invoice rate", format=",.2f"),
        alt.Tooltip(QUANTITY_COL, title="Qty", format=",.2f"),
        alt.Tooltip(INVOICE_NO_COL, title="Invoice no."),
    ]
    if ITEM_CODE_COL in plot_df.columns:
        tooltip.append(alt.Tooltip(ITEM_CODE_COL, title="Item code"))

    return (
        alt.Chart(plot_df)
        .mark_circle(size=55, opacity=0.75, color="#1f77b4")
        .encode(
            x=alt.X(
                f"{INVOICE_DATE_COL}:T",
                title="Invoice date",
                axis=alt.Axis(format="%Y", labelAngle=-45),
                scale=alt.Scale(domain=list(x_domain)),
            ),
            y=alt.Y(f"{INVOICE_RATE_COL}:Q", title="Invoice rate (purchase price)"),
            tooltip=tooltip,
        )
        .properties(height=300, title=supplier)
    )


def _render_supplier_chart(
    plot_base: pd.DataFrame,
    supplier: str,
    n_lines: int,
    *,
    x_domain: tuple[pd.Timestamp, pd.Timestamp],
) -> None:
    vendor_df = plot_base.loc[plot_base[SUPPLIER_COL].astype(str).str.strip() == supplier]
    if vendor_df.empty:
        st.info("No rows with a valid date and invoice rate for this supplier.")
        return
    st.altair_chart(
        _supplier_price_scatter_chart(
            vendor_df,
            f"{supplier} ({n_lines:,} lines)",
            x_domain=x_domain,
        ),
        use_container_width=True,
    )


def _render_supplier_price_scatters(filtered: pd.DataFrame) -> None:
    plot_base = rows_for_price_scatter(filtered)
    ranked = suppliers_by_line_count(filtered)

    # st.markdown("#### Purchase price over time (by supplier)")
    # st.caption(
    #     f"**{len(ranked):,}** supplier(s), sorted by purchase line count. "
    #     f"Top **{TOP_SUPPLIERS_N}** vendors are shown below; the rest are under **Other vendors**. "
    #     "Each chart plots **invoice date** vs **invoice rate**."
    # )

    if not ranked:
        st.warning("No supplier names found in the matching rows.")
        return

    skipped = len(filtered) - len(plot_base)
    if skipped:
        st.caption(f"{skipped:,} line(s) omitted (missing date or invoice rate).")

    x_domain = _invoice_date_year_domain(plot_base)

    top = ranked[:TOP_SUPPLIERS_N]
    rest = ranked[TOP_SUPPLIERS_N:]

    if top:
        st.markdown("##### Top vendors by purchase lines")
        for supplier, n_lines in top:
            # st.markdown(f"**{supplier}** · {n_lines:,} line(s)")
            _render_supplier_chart(plot_base, supplier, n_lines, x_domain=x_domain)

    if rest:
        other_lines = sum(n for _, n in rest)
        with st.expander(
            f"Other vendors ({len(rest):,}) · {other_lines:,} line(s)",
            expanded=False,
        ):
            for supplier, n_lines in rest:
                with st.expander(f"{supplier} — {n_lines:,} line(s)", expanded=False):
                    _render_supplier_chart(
                        plot_base, supplier, n_lines, x_domain=x_domain
                    )


def render_submaingroup_lookup() -> None:
    st.title("Purchase history")
    st.caption("Loads **`df-purchase.xlsx`**. Select an **Item code** to view purchase lines.")

    excel_path = default_purchase_path()
    if not excel_path.is_file():
        st.error(f"Missing data file: `{excel_path}`")
        return

    df = load_purchase_register(excel_path)
    filter_opts = purchase_filter_options(excel_path)

    item_code = _optional_filter_selectbox(
        "Item code",
        filter_opts["item_code"],
        key="production_item_code",
    )

    if not item_code:
        st.info("Select an **Item code** (not —) to view matching purchase lines.")
        return

    filtered = subset_purchase_history(df, item_code=item_code)
    if filtered.empty:
        st.warning(f"No rows found for Item code `{item_code}`.")
        return

    # st.markdown(f"##### Item code: `{item_code}`")
    n_suppliers = len(unique_supplier_names(filtered))
    st.caption(f"{len(filtered):,} line(s) · {n_suppliers:,} supplier(s)")

    _render_supplier_price_scatters(filtered)

    st.markdown("#### Purchase lines")
    display_cols = [c for c in filtered.columns if c != "Sub Main Group"]
    table_df = filtered[display_cols].copy()

    st.caption(
        f"**{len(table_df):,}** rows. Drag column borders to resize; use the **filter row** to search."
    )

    gb = GridOptionsBuilder.from_dataframe(table_df)
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

    AgGrid(
        table_df,
        gridOptions=gb.build(),
        height=600,
        theme="streamlit",
        update_mode=GridUpdateMode.NO_UPDATE,
        allow_unsafe_jscode=False,
        key="production_purchase_lines_aggrid",
    )
