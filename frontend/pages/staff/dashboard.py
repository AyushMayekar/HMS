"""
Staff Operations page — one surface for the floor view and the full list.

The former Staff Dashboard and Staff Appointments pages are merged behind a
radio switch, following the same pattern as Administration › Management:

    Overview      -> last-30-day KPIs plus today's visits, grouped by department
    Appointments  -> status / department / date filters over every visit

Both sections render through the shared row renderer in
``frontend.pages.staff.appointments``, so Check In and Mark No-Show exist
exactly once for the staff role instead of once per page. Start / End Service
belongs to the clinician, so it lives only on the doctor's Consultations page.
Reminder and no-show prediction actions stay exclusively on the Staff
Reminders page, so opening this page never triggers the reminder or ML
endpoints.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import loading
from frontend.components.analytics import hospital_today, parse_timestamp
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error
from frontend.api.staff_admin_services import StaffAppointmentService
from frontend.api.analytics_services import AnalyticsService

from frontend.pages.staff import appointments as appointments_page

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")

TODAY_PAGE_KEY = "staff_ops_today_page"

SECTIONS = {
    "Overview": (
        "Today's floor view: the last 30 days of appointment KPIs plus every visit "
        "scheduled for today, grouped by department."
    ),
    "Appointments": (
        "The complete appointment list, soonest first, with status, department and "
        "scheduled-date filters."
    ),
}


def render():
    page_head(
        "Operations",
        "Today's visits, waiting queue, and appointment operations across the hospital floor.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Operations"])

    # Feedback from a check-in / lifecycle action run on either section.
    appointments_page.render_flash()

    choice = st.radio(
        "Section",
        list(SECTIONS.keys()),
        key="staff_ops_section",
        horizontal=True,
        help="Switch between today's floor view and the full appointment list without leaving the page.",
    )
    st.caption(SECTIONS[choice])

    analytics = AnalyticsService()
    appt_service = StaffAppointmentService()

    if choice == "Overview":
        render_overview(analytics, appt_service)
    else:
        appointments_page.render_content()


def render_overview(analytics: AnalyticsService, appt_service: StaffAppointmentService) -> None:
    """30-day KPIs plus today's visits, grouped by department."""
    # ---------- Appointment KPIs (last 30 days) ----------
    with loading("Loading today's overview"):
        appt_res = analytics.appointments(days=30)
    if not appt_res.success:
        display_api_error(appt_res)
    else:
        summary = (appt_res.data or {}).get("summary") or {}
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Appointments booked (30 days)", f"{int(summary.get('total_appointments', 0) or 0):,}")
        k2.metric("Completed visits", f"{int(summary.get('completed', 0) or 0):,}")
        k3.metric("No-show visits", f"{int(summary.get('no_shows', 0) or 0):,}")
        k4.metric(
            "No-show rate (30 days)",
            f"{float(summary.get('no_show_rate', 0) or 0):.1f}%",
            help="Share of booked appointments that ended as a no-show.",
        )
        k5.metric("Cancelled visits", f"{int(summary.get('cancelled', 0) or 0):,}")

    st.divider()

    # ---------- Today's appointments, grouped by department ----------
    section_title(
        "Today's Appointments",
        "Visits scheduled for today, grouped by department. Open a row for the check-in actions.",
    )
    today = hospital_today()
    with loading("Loading today's appointments"):
        today_res = appt_service.list(limit=200)
    if not today_res.success:
        display_api_error(today_res)
        return

    today_appts = []
    for a in today_res.data or []:
        start = parse_timestamp(a.get("scheduled_start"))
        if start is not None and start.date() == today:
            today_appts.append(a)
    today_appts.sort(key=lambda a: str(a.get("scheduled_start") or ""))

    if not today_appts:
        empty_state("No appointments scheduled for today.", icon="")
        return

    active = [a for a in today_appts if a.get("appointment_status") not in RESOLVED_STATUSES]
    if not active:
        st.success("All of today's appointments have been resolved.")
        return

    # One shared row renderer (and one pagination) for every staff list.
    appointments_page.render_paginated_rows(
        active,
        appt_service,
        page_key=TODAY_PAGE_KEY,
        group_by_department=True,
    )


if __name__ == "__main__":
    render()
