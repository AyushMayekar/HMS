"""
Date picker component for appointment booking.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

import streamlit as st


def booking_date_picker(
    available_dates: list[date],
    session_key: str = "booking_selected_date",
    key_prefix: str = "cal",
    label: str = "Select date",
    clear_keys_on_change: list[str] = None,
    max_days_ahead: int = 30,
) -> Optional[date]:
    """
    Render a compact calendar-style date picker for appointment booking.

    Args:
        available_dates: List of available dates (date objects)
        session_key: Session state key to store selected date
        key_prefix: Prefix for widget keys
        label: Label for the picker
        clear_keys_on_change: Other session keys to clear when date changes
        max_days_ahead: Maximum days ahead to show

    Returns:
        Selected date or None
    """
    if clear_keys_on_change is None:
        clear_keys_on_change = []

    today = date.today()
    max_date = today + timedelta(days=max_days_ahead)

    # Filter available dates to valid range
    valid_dates = [d for d in available_dates if today <= d <= max_date]
    available_set = set(valid_dates)

    # Month/year selector
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### {label}")

    # Get current month/year from session or default to current
    month_key = f"{key_prefix}_month"
    year_key = f"{key_prefix}_year"

    if month_key not in st.session_state:
        st.session_state[month_key] = today.month
    if year_key not in st.session_state:
        st.session_state[year_key] = today.year

    current_month = st.session_state[month_key]
    current_year = st.session_state[year_key]

    # Month/Year navigation
    nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([1, 2, 2, 1])
    with nav_col1:
        if st.button("◀", key=f"{key_prefix}_prev_month", width="stretch"):
            if current_month == 1:
                st.session_state[month_key] = 12
                st.session_state[year_key] = current_year - 1
            else:
                st.session_state[month_key] = current_month - 1
            st.rerun()

    with nav_col2:
        month_name = calendar.month_name[current_month]
        st.markdown(f"**{month_name} {current_year}**")

    with nav_col3:
        # Quick month selector
        months = list(range(1, 13))
        month_labels = [calendar.month_name[m] for m in months]
        selected_idx = months.index(current_month)
        new_month = st.selectbox(
            "Month",
            months,
            format_func=lambda m: calendar.month_name[m],
            index=selected_idx,
            key=f"{key_prefix}_month_select",
            label_visibility="collapsed",
        )
        if new_month != current_month:
            st.session_state[month_key] = new_month
            st.rerun()

    with nav_col4:
        if st.button("▶", key=f"{key_prefix}_next_month", width="stretch"):
            if current_month == 12:
                st.session_state[month_key] = 1
                st.session_state[year_key] = current_year + 1
            else:
                st.session_state[month_key] = current_month + 1
            st.rerun()

    # Calendar grid
    cal = calendar.monthcalendar(current_year, current_month)

    # Day headers
    day_cols = st.columns(7, gap="small")
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for col, day_name in zip(day_cols, day_names):
        with col:
            st.markdown(f"<center><small><strong>{day_name}</strong></small></center>", unsafe_allow_html=True)

    # Calendar weeks
    for week_idx, week in enumerate(cal):
        week_cols = st.columns(7, gap="small")
        for day_idx, day in enumerate(week):
            with week_cols[day_idx]:
                if day == 0:
                    st.write(" ")
                else:
                    current_date = date(current_year, current_month, day)
                    is_today = current_date == today
                    is_past = current_date < today
                    is_future = current_date > max_date
                    is_available = current_date in available_set
                    is_selected = st.session_state.get(session_key) == current_date

                    # Determine button state
                    disabled = is_past or is_future or not is_available
                    button_type = "primary" if is_selected else ("secondary" if is_available else "tertiary")

                    # Button label (today is marked with parentheses — a
                    # glyph every platform font renders identically)
                    label_str = str(day)
                    if is_today:
                        label_str = f"({day})"

                    if st.button(
                        label_str,
                        key=f"{key_prefix}_day_{current_year}_{current_month}_{day}",
                        disabled=disabled,
                        type=button_type,
                        width="stretch",
                    ):
                        st.session_state[session_key] = current_date
                        # Clear dependent keys
                        for key in clear_keys_on_change:
                            st.session_state.pop(key, None)
                        st.rerun()

                    # Tooltip for availability
                    if is_available and not disabled:
                        st.caption("Available")
                    elif is_past:
                        st.caption("Past")
                    elif not is_available:
                        st.caption("Full")

    # Clear button
    if st.session_state.get(session_key):
        if st.button("Clear selection", key=f"{key_prefix}_clear", width="stretch"):
            st.session_state.pop(session_key, None)
            for key in clear_keys_on_change:
                st.session_state.pop(key, None)
            st.rerun()

    return st.session_state.get(session_key)


def simple_date_picker(
    label: str = "Select date",
    min_date: date = None,
    max_date: date = None,
    key: str = "simple_date",
) -> Optional[date]:
    """
    Simple date picker using Streamlit's native date_input.

    Args:
        label: Label for the picker
        min_date: Minimum selectable date
        max_date: Maximum selectable date
        key: Widget key

    Returns:
        Selected date or None
    """
    if min_date is None:
        min_date = date.today()
    if max_date is None:
        max_date = date.today() + timedelta(days=90)

    selected = st.date_input(
        label,
        value=None,
        min_value=min_date,
        max_value=max_date,
        key=key,
    )

    return selected if selected else None


def date_range_picker(
    label: str = "Date range",
    default_days: int = 30,
    key: str = "date_range",
) -> tuple[Optional[date], Optional[date]]:
    """
    Date range picker for analytics filters.

    Args:
        label: Label for the picker
        default_days: Default range in days
        key: Widget key prefix

    Returns:
        Tuple of (start_date, end_date)
    """
    end_default = date.today()
    start_default = end_default - timedelta(days=default_days)

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input(
            "Start date",
            value=start_default,
            max_value=end_default,
            key=f"{key}_start",
        )
    with col2:
        end = st.date_input(
            "End date",
            value=end_default,
            min_value=start if start else date.today() - timedelta(days=365),
            max_value=date.today(),
            key=f"{key}_end",
        )

    return start, end