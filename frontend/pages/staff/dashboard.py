"""
Staff Dashboard page — one unified operations view.

Combines today's appointment operations and department grouping on a single
screen. Reminder and no-show prediction actions live exclusively on the
Staff Reminders page, so opening the dashboard never triggers the reminder
or ML endpoints.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import expandable_row, loading
from frontend.components.analytics import (
    extract_predicted_wait,
    get_predicted_wait,
    hospital_today,
    parse_timestamp,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.staff_admin_services import StaffAppointmentService
from frontend.api.analytics_services import AnalyticsService

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")

FLASH_KEY = "staff_action_flash"


def render():
    page_head(
        "Operations Dashboard",
        "Today's visits and waiting queue across the hospital floor.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Dashboard"])

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash.get("message", "Action completed.") if isinstance(flash, dict) else str(flash))

    analytics = AnalyticsService()
    appt_service = StaffAppointmentService()

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
        else:
            grouped: dict[str, list[dict]] = {}
            for a in active:
                grouped.setdefault(a.get("department_name") or "Unassigned department", []).append(a)
            for dept in sorted(grouped):
                section_title(dept, f"{len(grouped[dept])} visit(s) in this department today.")
                for a in grouped[dept]:
                    render_today_row(a, appt_service)

    st.divider()

    # Link to the fuller appointment view that supports this screen.
    st.page_link(
        "pages/staff/appointments.py",
        label="View all appointments",
        icon=":material/checklist:",
        width="stretch",
        help="Search and filter the complete appointment list.",
    )


def render_today_row(a: dict, service: StaffAppointmentService) -> None:
    """Compact expandable row for one of today's visits, with lifecycle actions."""
    status = a.get("appointment_status") or "unknown"
    appointment_id = a.get("appointment_id")
    patient = a.get("patient_name") or "Patient name not available"
    checked_in = bool(a.get("actual_checkin_time"))
    service_started = bool(a.get("actual_service_start"))
    service_ended = bool(a.get("actual_service_end"))
    resolved = status in RESOLVED_STATUSES

    wait = None
    if checked_in and status != "completed":
        wait = extract_predicted_wait(a)
        if wait is None:
            wait = get_predicted_wait(appointment_id)

    details = [format_datetime(a.get("scheduled_start"))]
    if a.get("patient_email"):
        details.append(str(a.get("patient_email")))
    if wait is not None:
        details.append(f"Predicted wait {round(wait)} min")
    if checked_in:
        details.append(f"Checked in {format_datetime(a.get('actual_checkin_time'))}")
    if service_started:
        details.append(f"Service started {format_datetime(a.get('actual_service_start'))}")
    if service_ended:
        details.append(f"Service ended {format_datetime(a.get('actual_service_end'))}")

    def actions():
        if resolved:
            st.caption("This visit is resolved — no further actions are available.")
            return
        can_checkin = status == "booked" and not checked_in
        can_start = checked_in and not service_started
        can_end = service_started and not service_ended
        cols = st.columns(3, gap="small")
        with cols[0]:
            if st.button(
                "Check In",
                key=f"dash_checkin_{appointment_id}",
                type="primary" if can_checkin else "secondary",
                width="stretch",
                disabled=not can_checkin,
            ):
                run_action(service.check_in, a, f"{patient} checked in successfully.")
        with cols[1]:
            if st.button(
                "Mark No-Show",
                key=f"dash_noshow_{appointment_id}",
                width="stretch",
                disabled=not (status == "booked" and not checked_in),
            ):
                run_action(service.mark_no_show, a, f"{patient} marked as no-show.")
        with cols[2]:
            if service_started and not service_ended:
                if st.button("End Service", key=f"dash_end_{appointment_id}", type="primary", width="stretch"):
                    run_action(service.end_service, a, f"Service ended for {patient}.")
            else:
                if st.button(
                    "Start Service",
                    key=f"dash_start_{appointment_id}",
                    type="primary",
                    width="stretch",
                    disabled=not can_start,
                ):
                    run_action(service.start_service, a, f"Service started for {patient}.")

    expandable_row(
        str(appointment_id),
        title=f"{patient} · {a.get('department_name') or 'Department not set'}",
        meta=" · ".join(details),
        pill=status,
        id_text=f"Appointment #{appointment_id}",
        actions=actions,
    )


def run_action(action, a: dict, success_text: str) -> None:
    """Run a staff lifecycle action and standardize the feedback."""
    with loading("Saving your change"):
        result = action(a.get("appointment_id"))
    if result.success:
        st.session_state[FLASH_KEY] = {"message": success_text}
        st.rerun()
    else:
        display_api_error(result)




if __name__ == "__main__":
    render()
