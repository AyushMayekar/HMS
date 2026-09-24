"""
Staff Dashboard page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.analytics import (
    extract_predicted_wait,
    get_predicted_wait,
    hospital_today,
    parse_timestamp,
    render_no_show_risk,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.staff_admin_services import StaffAppointmentService
from frontend.api.analytics_services import AnalyticsService

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")


def render():
    page_head(
        "Operations Dashboard",
        "Today's visits, waiting queue, and no-show risk across the hospital floor.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Dashboard"])

    analytics = AnalyticsService()
    appt_service = StaffAppointmentService()

    # ---------- Appointment KPIs (last 30 days) ----------
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

    # ---------- Today's appointments ----------
    section_title(
        "Today's Appointments",
        "Visits scheduled for today in the hospital's local time. Full check-in controls are on the Appointments page.",
    )
    today = hospital_today()
    today_res = appt_service.list(limit=200)
    today_appts = []
    if today_res.success:
        for a in today_res.data or []:
            start = parse_timestamp(a.get("scheduled_start"))
            if start is not None and start.date() == today:
                today_appts.append(a)
        today_appts.sort(key=lambda a: str(a.get("scheduled_start") or ""))
    else:
        display_api_error(today_res)

    if not today_appts:
        empty_state("No appointments scheduled for today.", icon="")
    else:
        active = [a for a in today_appts if a.get("appointment_status") not in RESOLVED_STATUSES]
        if not active:
            st.success("All of today's appointments have been resolved.")
        for a in active[:8]:
            render_today_card(a)

    st.divider()

    # ---------- No-show risk ----------
    section_title(
        "No-Show Risk Queue",
        "Upcoming bookings in the next 48 hours with the model's predicted no-show likelihood. "
        "Reminders can be sent from the Reminders page.",
    )
    risk_res = analytics.no_show_risk()
    if not risk_res.success:
        display_api_error(risk_res)
    else:
        render_no_show_risk(risk_res.data or {})


def render_today_card(a: dict) -> None:
    """Render one of today's visit cards with identity, timing and predicted wait."""
    status = a.get("appointment_status") or "unknown"
    with st.container(border=True):
        col1, col2, col3 = st.columns([3.4, 1.4, 1])
        with col1:
            patient = a.get("patient_name") or "Patient name not available"
            email = a.get("patient_email")
            st.write(
                f"**{patient}** · {a.get('department_name') or 'Department not set'} · "
                f"Dr. {a.get('doctor_name') or 'Doctor'}"
            )
            details = [format_datetime(a.get("scheduled_start"))]
            if email:
                details.append(str(email))
            details.append(f"Appointment `#{str(a.get('appointment_id') or '')[:8]}`")
            st.caption(" · ".join(details))
        with col2:
            wait = None
            if a.get("actual_checkin_time") and status != "completed":
                wait = extract_predicted_wait(a)
                if wait is None:
                    wait = get_predicted_wait(a.get("appointment_id"))
            if wait is not None:
                st.metric(
                    "Predicted wait",
                    f"{round(wait)} min",
                    help="Waiting time predicted when this patient was checked in. Not shown once the visit is completed.",
                )
            else:
                st.write(" ")
        with col3:
            status_pill(status)


if __name__ == "__main__":
    render()
