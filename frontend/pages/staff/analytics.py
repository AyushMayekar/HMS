"""
Staff Analytics page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, breadcrumb
from frontend.components.analytics import (
    department_selector,
    view_by_range_control,
    render_appointment_analytics,
    render_timeseries,
    render_billing_analytics,
    render_satisfaction_analytics,
    render_booking_channel_analytics,
    render_no_show_analytics,
    render_waiting_time_analytics,
    guard_response,
)
from frontend.utils.session import require_role, current_user
from frontend.api.analytics_services import AnalyticsService


def render():
    page_head(
        "Analytics & Insights",
        "Hospital-wide operational analysis computed live from patient records — "
        "every section explains what its numbers mean.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Analytics"])
    render_analytics_content()


def _days_control(key_prefix: str) -> int:
    """Analysis-window slider shared by the day-based tabs."""
    return st.slider(
        "Analysis window (days)",
        7, 365, 30,
        step=1,
        key=f"{key_prefix}_days",
        help="How many days of history to include in the analysis.",
    )


def render_analytics_content() -> None:
    """Render the full analytics tab set. Also used by the admin analytics page."""
    service = AnalyticsService()

    tabs = st.tabs([
        "Appointments",
        "Patient Flow",
        "Bed Demand",
        "Billing",
        "Satisfaction",
        "Booking Channel",
        "No-Show",
        "Waiting Time",
    ])

    # ---------- Appointments ----------
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_appt")
        with c2:
            days = _days_control("an_appt")
        res = service.appointments(department_id=dept_id, days=days)
        if guard_response(res):
            pass
        else:
            render_appointment_analytics(res.data or {})

    # ---------- Patient Flow ----------
    with tabs[1]:
        c1, c2 = st.columns([1, 2])
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_flow")
        with c2:
            view_by, range_index = view_by_range_control(key_prefix="an_flow")
        res = service.patient_flow(department_id=dept_id, view_by=view_by, range_index=range_index)
        if guard_response(res):
            pass
        else:
            render_timeseries(
                res.data or {},
                "Patient flow",
                y_label="Patient visits (total per period)",
                explanation=(
                    "Patient visits recorded on the days inside each period, summed per period — "
                    "use it to see when the hospital is busiest."
                ),
            )

    # ---------- Bed Demand ----------
    with tabs[2]:
        c1, c2 = st.columns([1, 2])
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_bed")
        with c2:
            view_by, range_index = view_by_range_control(key_prefix="an_bed")
        res = service.bed_demand(department_id=dept_id, view_by=view_by, range_index=range_index)
        if guard_response(res):
            pass
        else:
            render_timeseries(
                res.data or {},
                "Bed demand",
                y_label="Beds demanded (total per period)",
                explanation=(
                    "Recorded next-day bed demand summed across the days inside each period — "
                    "use it to see when bed pressure is highest."
                ),
            )

    # ---------- Billing ----------
    with tabs[3]:
        c1, c2 = st.columns(2)
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_bill")
        with c2:
            days = _days_control("an_bill")
        res = service.billing(department_id=dept_id, days=days)
        if guard_response(res):
            pass
        else:
            render_billing_analytics(res.data or {})

    # ---------- Satisfaction ----------
    with tabs[4]:
        c1, c2 = st.columns(2)
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_sat")
        with c2:
            days = _days_control("an_sat")
        res = service.satisfaction(department_id=dept_id, days=days)
        if guard_response(res):
            pass
        else:
            render_satisfaction_analytics(res.data or {})

    # ---------- Booking Channel ----------
    with tabs[5]:
        c1, c2 = st.columns([1, 2])
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_chan")
        with c2:
            view_by, range_index = view_by_range_control(key_prefix="an_chan")
        res = service.booking_channel(department_id=dept_id, view_by=view_by, range_index=range_index)
        if guard_response(res):
            pass
        else:
            render_booking_channel_analytics(res.data or {})

    # ---------- No-Show ----------
    with tabs[6]:
        c1, c2 = st.columns(2)
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_ns")
        with c2:
            days = _days_control("an_ns")
        res = service.no_show(department_id=dept_id, days=days)
        if guard_response(res):
            pass
        else:
            render_no_show_analytics(res.data or {})

    # ---------- Waiting Time ----------
    with tabs[7]:
        c1, c2 = st.columns(2)
        with c1:
            dept_label, dept_id = department_selector(key_prefix="an_wait")
        with c2:
            days = _days_control("an_wait")
        res = service.waiting_time(department_id=dept_id, days=days)
        if guard_response(res):
            pass
        else:
            render_waiting_time_analytics(res.data or {})


if __name__ == "__main__":
    render()
