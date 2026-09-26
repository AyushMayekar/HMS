"""
Reusable card components for the Meridian Care frontend.
"""
from __future__ import annotations

import streamlit as st

from frontend.config import COLORS
from frontend.utils.states import is_in_past, status_pill


def kpi_row(kpis: list[tuple]) -> None:
    """
    Render a row of KPI metric cards.

    Args:
        kpis: List of tuples (label, value, delta, delta_color)
              label: str - metric label
              value: str|int|float - metric value
              delta: Optional[str] - delta text (e.g., "+5%")
              delta_color: Optional[str] - "normal", "inverse", "off"
    """
    cols = st.columns(len(kpis), gap="medium")
    for col, (label, value, delta, delta_color) in zip(cols, kpis):
        with col:
            st.metric(
                label=label,
                value=value,
                delta=delta,
                delta_color=delta_color or "normal",
            )


def info_card(
    title: str,
    content: str,
    icon: str = ":material/info:",
    border_color: str = None,
) -> None:
    """
    Render an informational card.

    Args:
        title: Card title
        content: Card content (markdown supported)
        icon: Material Symbols shortcode (platform-independent)
        border_color: Custom border color (CSS variable or hex)
    """
    border = border_color or COLORS["border"]
    st.markdown(
        f"""
        <div style="
            background: var(--mc-surface);
            border: 1px solid {border};
            border-left: 4px solid var(--mc-teal);
            border-radius: var(--mc-radius);
            padding: 1rem 1.25rem;
            margin: 0.5rem 0;
            box-shadow: var(--mc-shadow);
        ">
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                <strong style="color: var(--mc-navy);">{title}</strong>
            </div>
            <div style="color: var(--mc-text);">{content}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if icon.startswith(":material/"):
        st.markdown(icon)  # resolved by Streamlit's markdown renderer


def action_card(
    title: str,
    description: str,
    button_label: str,
    button_key: str,
    button_type: str = "primary",
    icon: str = ":material/touch_app:",
    on_click=None,
    args=None,
    kwargs=None,
) -> bool:
    """
    Render a card with an action button.

    Args:
        title: Card title
        description: Card description
        button_label: Button text
        button_key: Unique key for the button
        button_type: "primary" or "secondary"
        icon: Material Symbols shortcode prefix for the title
        on_click: Callback function
        args: Positional args for callback
        kwargs: Keyword args for callback

    Returns:
        True if button was clicked
    """
    with st.container(border=True):
        if icon.startswith(":material/"):
            st.markdown(f"{icon} **{title}**")
        else:
            st.markdown(f"### {title}")
        st.write(description)
        return st.button(
            button_label,
            key=button_key,
            type=button_type,
            width="stretch",
            on_click=on_click,
            args=args,
            kwargs=kwargs,
        )


def appointment_card(
    appointment: dict,
    show_actions: bool = False,
    patient_view: bool = True,
    key_prefix: str = "appt",
) -> None:
    """
    Render an appointment card.

    Args:
        appointment: Appointment data dict
        show_actions: Whether to show action buttons
        patient_view: Whether this is patient view (vs staff)
        key_prefix: Prefix for button keys
    """
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])

        with col1:
            dept = appointment.get("department_name") or appointment.get("department", "Unknown")
            doctor = appointment.get("doctor_name") or appointment.get("doctor", "Unknown Doctor")
            patient = appointment.get("patient_name")
            start_time = appointment.get("scheduled_start") or appointment.get("start_time")

            title = f"**{dept}** · {doctor}"
            if patient and not patient_view:
                title += f" · {patient}"
            st.write(title)
            if start_time:
                st.caption(format_datetime(start_time))

        with col2:
            status = appointment.get("appointment_status") or appointment.get("status", "unknown")
            status_pill(status)

        # Waiting time: only while the patient is checked in and the visit
        # is still open — never after completion (spec §20).
        wait_min = appointment.get("predicted_waiting_min")
        checked_in = bool(appointment.get("actual_checkin_time"))
        if wait_min is not None and checked_in and status not in (
            "completed", "cancelled", "no_show", "in_consultation"
        ):
            st.caption(f"Estimated wait: {wait_min:.0f} min")

        # No-show predictions are owned by the Staff Reminders page (the single
        # prediction + reminder workflow) — never duplicated on a card.

        if show_actions:
            appt_id = appointment.get("appointment_id")
            # Past appointments must not offer Check-In / No-Show (§15.4).
            past = is_in_past(start_time)
            if patient_view:
                if status in ("booked", "confirmed"):
                    if st.button(
                        "Reschedule",
                        key=f"{key_prefix}_reschedule_{appt_id}",
                        width="stretch",
                    ):
                        st.session_state[f"{key_prefix}_reschedule_target"] = appt_id
                        st.rerun()
                    if st.button(
                        "Cancel",
                        key=f"{key_prefix}_cancel_{appt_id}",
                        type="secondary",
                        width="stretch",
                    ):
                        st.session_state[f"{key_prefix}_cancel_target"] = appt_id
                        st.rerun()
            else:
                # Staff actions. Check-in is the front desk's card duty, and
                # it stops the moment the visit is checked in — no buttons
                # after that. Start / End Service belongs to the clinician, so
                # it lives only on the doctor's Consultations page and is
                # never duplicated here.
                if status in ("booked", "confirmed") and not past and not checked_in:
                    if st.button(
                        "Check In",
                        key=f"{key_prefix}_checkin_{appt_id}",
                        type="primary",
                        width="stretch",
                    ):
                        st.session_state[f"{key_prefix}_checkin_target"] = appt_id
                        st.rerun()
                elif checked_in:
                    st.caption(
                        "This visit is with the clinical team. "
                        "Lifecycle actions continue on Consultations."
                    )


def payment_card(payment: dict, key_prefix: str = "pay") -> None:
    """Render a payment card."""
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])

        with col1:
            amount = payment.get("amount", 0)
            currency = payment.get("currency", "INR")
            method = payment.get("payment_method") or payment.get("method", "")
            method_text = f" · via {method}" if method else ""
            st.write(f"**{currency} {amount:,.2f}**{method_text}")
            status = payment.get("status", "unknown")
            status_pill(status)

        with col2:
            if payment.get("created_at"):
                st.caption(format_datetime(payment["created_at"]))

        if status == "pending":
            if st.button(
                "Pay Now",
                key=f"{key_prefix}_pay_{payment.get('payment_id')}",
                type="primary",
                width="stretch",
            ):
                st.session_state[f"{key_prefix}_pay_target"] = payment.get("payment_id")
                st.rerun()


def request_card(request: dict, key_prefix: str = "req") -> None:
    """Render an admin request card."""
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])

        with col1:
            category = request.get("category", "Unknown")
            req_id = request.get("request_id", "")[:8]
            st.write(f"**{category.replace('_', ' ').title()}** · `{req_id}`")
            desc = request.get("description", "")
            if desc:
                st.caption(desc[:160] + ("..." if len(desc) > 160 else ""))

        with col2:
            status = request.get("status", "unknown")
            status_pill(status)

def doctor_card(doctor: dict) -> None:
    """Descriptive doctor card: real specialization, experience,
    department and status from the catalog payload (never invented)."""
    name = doctor.get("full_name") or "Unknown"
    spec = doctor.get("specialization") or "General consultation"
    exp = doctor.get("experience_years")
    dept = doctor.get("department_name") or ""
    status = doctor.get("status") or "active"

    with st.container(border=True):
        head_left, head_right = st.columns([3, 1.3], vertical_alignment="top")
        with head_left:
            st.markdown(f"**{name}**")
            st.caption(spec)
        with head_right:
            status_pill(status)

        facts = []
        if exp is not None:
            facts.append(f"{exp} years of experience")
        if dept:
            facts.append(f"Department: {dept}")
        if facts:
            st.caption("  ·  ".join(facts))

        qual = doctor.get("qualifications") or doctor.get("bio")
        if qual:
            st.write(qual)

def department_card(dept: dict, view_details_page: Optional[str] = None) -> None:
    """Descriptive department card: name, description, extra information
    and status — all from real backend data."""
    import html as _html

    name = dept.get("name") or "Unknown department"
    desc = dept.get("description") or ""
    info = dept.get("information") or ""
    status = dept.get("status") or "active"

    with st.container(
        border=True,
        key=f"mc_dept_card_{dept.get('department_id') or name}",
    ):
        head_left, head_right = st.columns(
            [3, 1.3],
            vertical_alignment="top",
        )

        with head_left:
            st.markdown(f"**{name}**")

        with head_right:
            status_pill(status)

        if desc:
            st.markdown(
                f'<p class="mc-clamp-3">{_html.escape(desc)}</p>',
                unsafe_allow_html=True,
            )

        if info:
            clean_info = _html.unescape(info) if "&" in info else info
            st.caption(clean_info)

        if view_details_page:
            st.page_link(
                view_details_page,
                label="View details",
                icon=":material/arrow_forward:",
            )
def slot_card(
    slot: dict,
    doctor: dict = None,
    selected: bool = False,
    on_select=None,
    key_prefix: str = "slot",
) -> bool:
    """
    Render a time slot card.

    Args:
        slot: Slot data dict
        doctor: Doctor data dict (optional)
        selected: Whether this slot is selected
        on_click: Callback when selected
        key_prefix: Key prefix for button

    Returns:
        True if slot was selected
    """
    start_time = slot.get("start_time") or slot.get("scheduled_start")
    slot_id = slot.get("availability_id") or slot.get("slot_id")

    doctor_name = slot.get("doctor_name") or "Doctor"
    specialization = slot.get("specialization") or "General consultation"
    department = slot.get("department_name") or ""
    if doctor:
        doctor_name = doctor.get("full_name", doctor_name)
        specialization = doctor.get("specialization", specialization)

    button_type = "primary" if selected else "secondary"
    label = "Selected" if selected else "Select"

    with st.container(border=True):
        time_str = format_datetime(start_time, "%a %d %b · %I:%M %p") if start_time else "—"
        st.markdown(f"**{time_str}**")
        st.caption(f"{doctor_name} · {specialization}" + (f" · {department}" if department else ""))

        if st.button(
            label,
            key=f"{key_prefix}_{slot_id}",
            type=button_type,
            width="stretch",
        ):
            if on_select:
                on_select(slot_id)
            return True

    return False


def feedback_card(feedback: dict) -> None:
    """Render a feedback card."""
    with st.container(border=True):
        col1, col2 = st.columns([1, 4])

        with col1:
            rating = feedback.get("rating", 0)
            st.markdown(f"<h1 style='text-align: center; color: var(--mc-teal);'>{rating}/5</h1>", unsafe_allow_html=True)

        with col2:
            comment = feedback.get("comment")
            if comment:
                st.write(comment)
            channel = feedback.get("feedback_channel", "form")
            st.caption(f"Submitted via {channel}")

        if feedback.get("created_at"):
            st.caption(f"Submitted: {format_datetime(feedback['created_at'])}")


def render_kpi_cards(kpis: list[dict]) -> None:
    """
    Render multiple KPI cards in a row.

    Args:
        kpis: List of dicts with keys: label, value, delta, delta_color, help
    """
    cols = st.columns(len(kpis), gap="medium")
    for col, kpi in zip(cols, kpis):
        with col:
            st.metric(
                label=kpi.get("label", ""),
                value=kpi.get("value", "—"),
                delta=kpi.get("delta"),
                delta_color=kpi.get("delta_color", "normal"),
                help=kpi.get("help"),
            )


# Import format_datetime from states
from frontend.utils.states import format_datetime