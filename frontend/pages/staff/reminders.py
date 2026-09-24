"""
Staff Reminders page — fixed 24-hour reminder model.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.analytics import RISK_BAND_LEGEND, format_percent, resolve_risk_level, risk_pill
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime
from frontend.api.staff_admin_services import StaffReminderService

REMINDER_TYPES = {
    "in_app": "In-app notification",
    "email": "Email",
}

REMINDER_HOURS_BEFORE = 24.0  # fixed 24-hour reminder model
DEFAULT_MESSAGE = "This is a friendly reminder about your upcoming appointment at Meridian Care."
MAX_MESSAGE_CHARS = 500

FLAG_THRESHOLD = 0.30  # a visit is a "predicted no-show" above this likelihood

FLASH_KEY = "staff_reminder_flash"


def render():
    page_head(
        "Reminders",
        "Send 24-hour appointment reminders — prioritising visits the model predicts to be no-shows.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Reminders"])

    service = StaffReminderService()

    # ---------- Feedback from the previous send ----------
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)

    section_title(
        "Upcoming visits and their no-show likelihood",
        "Every upcoming appointment returned by the backend, with the model's predicted no-show percentage. "
        "Visits predicted to be no-shows are flagged and listed first. "
        "Reminders are sent 24 hours before the appointment.",
    )
    st.caption(
        "Predicted no-show: the model gives the visit a no-show likelihood above 30%. "
        + RISK_BAND_LEGEND
    )

    # ---------- Reminder controls ----------
    c1, c2 = st.columns([1, 2])
    with c1:
        channel = st.selectbox(
            "Reminder channel",
            list(REMINDER_TYPES.keys()),
            format_func=lambda t: REMINDER_TYPES[t],
            key="rem_channel",
        )
    with c2:
        message = st.text_input(
            "Message",
            value=DEFAULT_MESSAGE,
            max_chars=MAX_MESSAGE_CHARS,
            key="rem_message",
            help=f"Sent to the patient with the reminder (maximum {MAX_MESSAGE_CHARS} characters).",
        )
    message = (message or "").strip()
    if not message:
        st.error("Enter a reminder message before sending.")
    st.caption("Timing: reminders go out 24 hours before the scheduled appointment (fixed 24-hour model).")

    # ---------- Appointment list ----------
    res = service.list(limit=200)
    if not res.success:
        display_api_error(res)
        st.stop()

    appointment_items, legacy_log = split_reminder_items(res.data)

    if not appointment_items:
        empty_state(
            "No upcoming appointments to remind right now.",
            "New bookings appear here as soon as they are scheduled.",
            icon="",
        )
    else:
        appointment_items.sort(key=lambda a: (
            not is_predicted_no_show(a),
            str(a.get("scheduled_start") or ""),
        ))
        for appt in appointment_items:
            render_reminder_row(
                appt,
                service=service,
                channel=channel,
                message=message,
                can_send=bool(message),
            )

    # ---------- Reminder history (legacy log shape) ----------
    if legacy_log:
        st.divider()
        section_title(
            "Reminder History",
            "Reminders already sent to patients — all recorded against the 24-hour reminder model.",
        )
        for rem in legacy_log:
            render_log_row(rem)


def split_reminder_items(data):
    """
    Normalize the GET /staff/reminders payload.

    The backend returns upcoming appointments (with no_show_probability), and
    older/simple shapes may still be plain reminder records — split them safely.
    """
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


def is_predicted_no_show(appt: dict) -> bool:
    """Whether the backend no-show likelihood is above the flag threshold."""
    if appt.get("predicted_no_show") is True or appt.get("no_show_class") == 1:
        return True
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


def reminder_state_caption(appt: dict) -> str | None:
    """Describe whether a reminder already exists for this appointment, if known."""
    sent_at = appt.get("sent_at") or appt.get("reminded_at")
    created_at = appt.get("reminder_created_at")
    when = sent_at or created_at
    reminder_type = appt.get("reminder_type")
    if appt.get("reminder_id") or when:
        parts = ["Reminder already sent"]
        if reminder_type:
            parts.append(REMINDER_TYPES.get(reminder_type, reminder_type))
        if when:
            parts.append(f"at {format_datetime(when)}")
        return " · ".join(parts)
    if appt.get("reminder_sent"):
        return "Reminder already sent for this visit."
    return None


def render_reminder_row(appt: dict, *, service, channel: str, message: str, can_send: bool) -> None:
    """One upcoming appointment: identity, predicted no-show %, and send action."""
    appointment_id = appt.get("appointment_id")
    patient = appt.get("patient_name") or "Patient name not available"
    probability = appt.get("no_show_probability")
    flagged = is_predicted_no_show(appt)
    level = resolve_risk_level(appt)

    with st.container(border=True):
        col1, col2, col3 = st.columns([3.2, 1.3, 1.5])
        with col1:
            st.write(
                f"**{patient}** · {appt.get('department_name') or 'Department not set'} · "
                f"Dr. {appt.get('doctor_name') or 'Doctor'}"
            )
            details = [format_datetime(appt.get("scheduled_start"))]
            if appt.get("patient_email"):
                details.append(str(appt.get("patient_email")))
            details.append(f"Appointment `#{str(appointment_id or '')[:8]}`")
            if appt.get("appointment_status"):
                details.append(str(appt.get("appointment_status")).replace("_", " ").title())
            st.caption(" · ".join(details))
            state = reminder_state_caption(appt)
            if state:
                st.caption(state)
        with col2:
            st.metric(
                "Predicted no-show",
                format_percent(probability) if probability is not None else "—",
                help="Likelihood, from the ML model, that this patient will not attend.",
            )
            st.markdown(risk_pill(level), unsafe_allow_html=True)
        with col3:
            if probability is None:
                st.caption("The model has not scored this visit yet.")
            elif flagged:
                st.caption("**Predicted no-show** — likelihood above 30%.")
            else:
                st.caption("Low no-show likelihood (30% or below).")
            if st.button(
                "Send Reminder",
                key=f"rem_send_{appointment_id}",
                type="primary",
                width="stretch",
                disabled=not can_send,
            ):
                if not can_send:
                    st.error("Enter a reminder message before sending.")
                    st.stop()
                result = service.create(
                    appointment_id=appointment_id,
                    reminder_type=channel,
                    hours_before_appointment=REMINDER_HOURS_BEFORE,
                    message=message,
                )
                if result.success:
                    st.session_state[FLASH_KEY] = (
                        f"Reminder sent to {patient} for the visit on "
                        f"{format_datetime(appt.get('scheduled_start'))} "
                        f"({REMINDER_HOURS_BEFORE:.0f}-hour reminder, {REMINDER_TYPES[channel].lower()})."
                    )
                    st.rerun()
                else:
                    display_api_error(result)


def render_log_row(rem: dict) -> None:
    """Render a single historical reminder record."""
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            body = rem.get("message") or "Appointment reminder"
            st.write(body)
            st.caption(
                f"Appointment `#{str(rem.get('appointment_id') or '')[:8]}` · "
                f"{REMINDER_TYPES.get(rem.get('reminder_type'), rem.get('reminder_type', 'In-app notification'))} · "
                f"{rem.get('hours_before_appointment', REMINDER_HOURS_BEFORE)} hours before"
            )
        with col2:
            st.caption(f"Sent {format_datetime(rem.get('sent_at') or rem.get('created_at'))}")


if __name__ == "__main__":
    render()
