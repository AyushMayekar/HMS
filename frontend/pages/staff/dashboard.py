"""
Staff Dashboard page — one unified operations view.

Combines today's appointment operations, department grouping and reminder
actions on a single screen. Reminder data is only fetched once the user
opens the reminder panel, so opening the dashboard never triggers the
reminder or ML endpoints.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import expandable_row, doctor_label, loading
from frontend.components.analytics import (
    extract_predicted_wait,
    get_predicted_wait,
    hospital_today,
    parse_timestamp,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.staff_admin_services import StaffAppointmentService, StaffReminderService
from frontend.api.analytics_services import AnalyticsService

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")

REMINDER_TYPES = {
    "in_app": "In-app notification",
    "email": "Email",
}
REMINDER_HOURS_BEFORE = 24.0
DEFAULT_MESSAGE = "This is a friendly reminder about your upcoming appointment at Meridian Care."
MAX_MESSAGE_CHARS = 500
FLAG_THRESHOLD = 0.30
REMINDER_OPEN_KEY = "staff_dash_reminders_open"
FLASH_KEY = "staff_action_flash"
REMINDER_FLASH_KEY = "staff_reminder_flash"


def render():
    page_head(
        "Operations Dashboard",
        "Today's visits, waiting queue and reminders across the hospital floor.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Dashboard"])

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash.get("message", "Action completed.") if isinstance(flash, dict) else str(flash))
    reminder_flash = st.session_state.pop(REMINDER_FLASH_KEY, None)
    if reminder_flash:
        st.success(str(reminder_flash))

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

    # Links to the fuller views that support this screen.
    l1, l2 = st.columns(2, gap="small")
    with l1:
        st.page_link(
            "pages/staff/appointments.py",
            label="View all appointments",
            icon=":material/checklist:",
            width="stretch",
            help="Search and filter the complete appointment list.",
        )
    with l2:
        st.page_link(
            "pages/staff/reminders.py",
            label="Reminder history",
            icon=":material/history:",
            width="stretch",
            help="Audit of every reminder the hospital has sent.",
        )

    # ---------- Reminders (fetched only when the panel is opened) ----------
    render_reminder_panel()


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


def _is_flagged(appt: dict) -> bool:
    probability = appt.get("no_show_probability")
    if probability is None:
        return False
    try:
        value = float(probability)
    except (TypeError, ValueError):
        return False
    if value > 1.0:
        value = value / 100.0
    return value > FLAG_THRESHOLD


def render_reminder_panel() -> None:
    """Reminder actions, loaded only after the user opens the panel."""
    section_title(
        "Reminders",
        "Send the standard 24-hour appointment reminder. Reminders are only "
        "loaded after you open this panel.",
    )

    if REMINDER_OPEN_KEY not in st.session_state:
        st.session_state[REMINDER_OPEN_KEY] = False

    if not st.session_state[REMINDER_OPEN_KEY]:
        if st.button(
            "Open reminder actions",
            key="dash_open_reminders",
            icon=":material/notifications:",
            type="primary",
        ):
            st.session_state[REMINDER_OPEN_KEY] = True
            st.rerun()
        return

    if st.button("Close reminder actions", key="dash_close_reminders", icon=":material/close:"):
        st.session_state[REMINDER_OPEN_KEY] = False
        st.rerun()

    service = StaffReminderService()
    with loading("Loading upcoming visits"):
        res = service.list(limit=200)
    if not res.success:
        display_api_error(res)
        return

    appointment_items, _legacy_log = _split(res.data)
    if not appointment_items:
        empty_state(
            "No upcoming appointments to remind right now.",
            "New bookings appear here as soon as they are scheduled.",
            icon="",
        )
        return

    appointment_items.sort(key=lambda a: (not _is_flagged(a), str(a.get("scheduled_start") or "")))

    c1, c2 = st.columns([1, 2])
    with c1:
        channel = st.selectbox(
            "Reminder channel",
            list(REMINDER_TYPES.keys()),
            format_func=lambda t: REMINDER_TYPES[t],
            key="dash_rem_channel",
        )
    with c2:
        message = st.text_input(
            "Message",
            value=DEFAULT_MESSAGE,
            max_chars=MAX_MESSAGE_CHARS,
            key="dash_rem_message",
            help=f"Sent to the patient with the reminder (maximum {MAX_MESSAGE_CHARS} characters).",
        )
    message = (message or "").strip()

    flagged = [a for a in appointment_items if _is_flagged(a)]
    if flagged and st.button(
        f"Send reminder to all {len(flagged)} flagged visit(s)",
        key="dash_rem_bulk",
        icon=":material/notifications_active:",
        width="stretch",
        disabled=not message,
    ):
        send_bulk(flagged, service, channel, message)
        return
    if not message:
        st.caption("Enter a reminder message before sending.")

    for appt in appointment_items[:20]:
        render_reminder_row(appt, service=service, channel=channel, message=message)


def _split(data):
    """Split the GET /staff/reminders payload into appointments and history."""
    raw = data or []
    appointments, logs = [], []
    if isinstance(raw, dict):
        appointments = list(raw.get("appointments") or [])
        logs = list(raw.get("reminders") or [])
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("scheduled_start"):
                appointments.append(item)
            else:
                logs.append(item)
    return appointments, logs


def send_bulk(items: list[dict], service, channel: str, message: str) -> None:
    """Send the standard reminder to several visits using the existing API."""
    sent, failed = 0, 0
    with loading(f"Sending {len(items)} reminder(s)"):
        for appt in items:
            result = service.create(
                appointment_id=appt.get("appointment_id"),
                reminder_type=channel,
                hours_before_appointment=REMINDER_HOURS_BEFORE,
                message=message,
            )
            if result.success:
                sent += 1
            else:
                failed += 1
    st.session_state[REMINDER_FLASH_KEY] = (
        f"{sent} reminder(s) sent"
        + (f", {failed} could not be sent." if failed else ".")
    )
    st.rerun()


def render_reminder_row(appt: dict, *, service, channel: str, message: str) -> None:
    """One upcoming appointment with its reminder action."""
    appointment_id = appt.get("appointment_id")
    patient = appt.get("patient_name") or "Patient name not available"
    flagged = _is_flagged(appt)
    probability = appt.get("no_show_probability")
    pct = ""
    if probability is not None:
        try:
            value = float(probability)
            pct = f" · Predicted no-show {value:.0%}" if value <= 1 else f" · Predicted no-show {value:.0f}%"
        except (TypeError, ValueError):
            pct = ""

    def actions():
        if st.button(
            "Send Reminder",
            key=f"dash_rem_send_{appointment_id}",
            type="primary",
            width="stretch",
            disabled=not message,
        ):
            with loading("Sending reminder"):
                result = service.create(
                    appointment_id=appointment_id,
                    reminder_type=channel,
                    hours_before_appointment=REMINDER_HOURS_BEFORE,
                    message=message,
                )
            if result.success:
                st.session_state[REMINDER_FLASH_KEY] = (
                    f"Reminder sent to {patient} for the visit on "
                    f"{format_datetime(appt.get('scheduled_start'))} "
                    f"({REMINDER_HOURS_BEFORE:.0f}-hour reminder, {REMINDER_TYPES[channel].lower()})."
                )
                st.rerun()
            else:
                display_api_error(result)

    expandable_row(
        f"rem_{appointment_id}",
        title=f"{patient} · {appt.get('department_name') or 'Department not set'} · "
              f"{doctor_label(appt.get('doctor_name'))}",
        meta=f"{format_datetime(appt.get('scheduled_start'))}"
             + (f" · {appt.get('patient_email')}" if appt.get("patient_email") else "")
             + pct,
        pill="pending" if flagged else "confirmed",
        id_text=f"Appointment #{appointment_id}",
        actions=actions,
    )


if __name__ == "__main__":
    render()
