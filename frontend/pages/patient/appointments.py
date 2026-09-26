"""
Patient Appointments page — the consolidated patient hub.

One page now hosts the four patient experiences that used to be separate
``st.Page`` entries: booking / management (this module) plus History, Payments
and Feedback. A horizontal section radio — the same pattern as Administration
› Management — renders either this module's own ``render_content()`` or the
section module's ``render_content()``, so every action, API call and
``require_role`` guard stays exactly where it was.

Section changes requested from *below* the radio (the appointment-row buttons
"Give feedback" / "Pay invoice", or a dashboard deep link) are queued in
``PENDING_SECTION_KEY`` and applied before the radio widget is created,
because a widget key may not be mutated after instantiation.
"""
import streamlit as st
from datetime import datetime, timedelta

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner, empty_state
from frontend.components.billing import (
    render_billing_summary,
    render_diagnostic_orders_table,
    render_prescriptions_table,
)
from frontend.components.ui import date_chips, expandable_row, loading, page_slice
from frontend.utils.session import require_role, current_user
from frontend.utils.states import status_pill, format_datetime, display_api_error
from frontend.api.services import AppointmentService, CatalogService
from frontend.config import APPOINTMENT_STATUSES
from frontend.pages.patient import feedback as feedback_module
from frontend.pages.patient import history as history_module
from frontend.pages.patient import payments as payments_module
from frontend.pages.patient._helpers import (
    build_doctor_map,
    doctor_display,
    render_flash,
    set_flash,
    show_booking_wait_preview,
    short_id,
    slot_datetime,
    slot_scheduled_start,
    slot_time_label,
)

BOOKING_WINDOW_DAYS = 20      # only the next 20 days are offered
REASON_MAX = 500        # backend BookAppointmentRequest.reason limit
CANCEL_REASON_MAX = 255  # backend PatientCancelRequest.reason limit
PENDING_PAYMENT_STATES = (None, "pending", "unpaid")

UPCOMING_PAGE_SIZE = 5   # expandable appointment rows per page
PAST_PAGE_SIZE = 10      # past rows per page inside the Past Appointments expander

# Section switcher: widget key + the queue used to change it from code that
# runs after the radio has already been instantiated in the current run.
SECTION_KEY = "patient_hub_section"
PENDING_SECTION_KEY = "_patient_hub_section_pending"

# ``module is None`` means the hub renders its own booking/management content.
SECTIONS = {
    "Appointments": (
        None,
        "Book a visit, manage upcoming appointments, and reschedule or cancel when plans change.",
    ),
    "History": (
        history_module,
        "A complete record of your visits, cancellations, and consultations.",
    ),
    "Payments": (
        payments_module,
        "View your invoices and make secure payments for consultations.",
    ),
    "Feedback": (
        feedback_module,
        "Share how your visit went, your input helps us improve care.",
    ),
}


# =====================================================================
# Section switching
# =====================================================================
def request_section(section: str) -> None:
    """Select another section of THIS page on the next run.

    Used by widgets rendered below the radio (appointment-row buttons): the
    radio's key cannot be written once the widget exists, so the request is
    queued and applied at the top of the next run.
    """
    if section in SECTIONS:
        st.session_state[PENDING_SECTION_KEY] = section
    st.rerun()


def open_section(section: str) -> None:
    """Jump into this hub from another page (e.g. the dashboard) on a section."""
    if section in SECTIONS:
        st.session_state[PENDING_SECTION_KEY] = section
    st.switch_page("pages/patient/appointments.py")


def _apply_pending_section() -> None:
    """Consume a queued section request before the radio widget is created."""
    pending = st.session_state.pop(PENDING_SECTION_KEY, None)
    if pending in SECTIONS:
        st.session_state[SECTION_KEY] = pending


# =====================================================================
# Page
# =====================================================================
def render():
    _apply_pending_section()

    page_head(
        "Appointments",
        "Book a visit, manage upcoming appointments, and review your history, "
        "payments and feedback without leaving the page.",
        noindex=True,
    )
    require_role(["patient"])
    current_user()

    breadcrumb(["Patient", "Appointments"])
    privacy_banner()
    render_flash("appointments")

    choice = st.radio(
        "Section",
        list(SECTIONS.keys()),
        key=SECTION_KEY,
        horizontal=True,
        help="Switch between appointments, history, payments and feedback in one page.",
    )

    module, blurb = SECTIONS[choice]
    section_title(choice, blurb)
    if module is None:
        render_content()
    else:
        module.render_content()


def render_content() -> None:
    """Booking + management content for the hub's own Appointments section."""
    appt_service = AppointmentService()
    catalog = CatalogService()

    # ---------- State ----------
    _init_booking_state()

    # =================================================================
    # BOOK NEW APPOINTMENT
    # =================================================================
    with st.expander("Book New Appointment", expanded=True):
        dept_res = catalog.departments()
        if not dept_res.success:
            display_api_error(dept_res)
        elif not dept_res.data:
            empty_state("No departments are available for booking right now.", "Please check back soon.", icon="")
        else:
            departments = dept_res.data
            _render_booking_flow(departments, appt_service, catalog)

    st.divider()

    # =================================================================
    # MY APPOINTMENTS (History / Payments / Feedback are the other sections
    # selected with the control at the top of this page)
    # =================================================================
    section_title("My Appointments", "Reschedule or cancel only if you are sure, the original slot may be released.")

    appts_res = appt_service.list(limit=100)
    if not appts_res.success:
        display_api_error(appts_res)
    appts = appts_res.data if appts_res.success else []

    doctors_res = catalog.doctors()
    if not doctors_res.success:
        display_api_error(doctors_res)
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    upcoming = [a for a in appts if a.get("appointment_status") not in ("completed", "cancelled", "no_show")]
    upcoming.sort(key=lambda a: a.get("scheduled_start") or "")
    past = [a for a in appts if a.get("appointment_status") in ("completed", "cancelled", "no_show")]

    if not upcoming:
        empty_state("No upcoming appointments.", "Use Book New Appointment above to reserve a slot.", icon="")
    else:
        page_rows, _, _ = page_slice(upcoming, len(upcoming), UPCOMING_PAGE_SIZE, "hub_upcoming_page")
        for a in page_rows:
            render_appointment_row(a, doctor_map, key_prefix="up")

    reschedule_target = st.session_state.get("reschedule_target")
    if reschedule_target:
        render_reschedule_flow(reschedule_target, appt_service, catalog, doctor_map)

    cancel_target = st.session_state.get("cancel_target")
    if cancel_target:
        render_cancel_flow(cancel_target, appt_service, doctor_map)

    # Past appointments
    if past:
        with st.expander(f"Past Appointments ({len(past)})"):
            past_rows, _, _ = page_slice(past, len(past), PAST_PAGE_SIZE, "hub_past_page")
            for a in past_rows:
                render_appointment_row(a, doctor_map, key_prefix="past", actions=False)


def _init_booking_state() -> None:
    """Ensure booking workflow keys exist."""
    st.session_state.setdefault("booking_dept", None)
    st.session_state.setdefault("booking_doctor_id", None)
    st.session_state.setdefault("booking_date", None)
    st.session_state.setdefault("booking_slot_id", None)
    st.session_state.setdefault("booking_reason", "")


def _reset_selection(include_doctor: bool = False) -> None:
    """Clear date/slot (and optionally doctor) after an upstream change."""
    st.session_state["booking_date"] = None
    st.session_state["booking_slot_id"] = None
    if include_doctor:
        st.session_state["booking_doctor_id"] = None


# =====================================================================
# Booking flow
# =====================================================================
def _render_booking_flow(departments: list, appt_service, catalog) -> None:
    """Department -> doctor -> date -> slot, then review + confirm."""
    _init_booking_state()

    dept_names = [d.get("name") for d in departments if d.get("name")]
    dept = st.selectbox(
        "1. Choose a Department",
        dept_names,
        key="booking_dept_select",
        help="Select the clinical specialty for your visit.",
    )
    if dept != st.session_state["booking_dept"]:
        st.session_state["booking_dept"] = dept
        _reset_selection(include_doctor=True)

    selected_dept = next((d for d in departments if d.get("name") == dept), None)
    if not selected_dept:
        return

    # ---------------- Step 2: doctor ----------------
    doctors_res = catalog.doctors(department_id=selected_dept.get("department_id"))
    if not doctors_res.success:
        display_api_error(doctors_res)
        return
    if not doctors_res.data:
        empty_state(
            "No doctors are listed in this department yet.",
            "Choose another department or check back soon.",
            icon="",
        )
        return

    doctors = doctors_res.data
    doctor_map = build_doctor_map(doctors)
    doctor_ids = [d.get("doctor_id") for d in doctors if d.get("doctor_id")]

    def _doctor_label(doctor_id: str) -> str:
        return doctor_display(doctor_map, doctor_id, specialization=True)

    doctor_id = st.selectbox(
        "2. Choose a Doctor",
        doctor_ids,
        format_func=_doctor_label,
        key="booking_doctor_select",
        help="Every slot below belongs to the selected doctor.",
    )
    if doctor_id != st.session_state["booking_doctor_id"]:
        st.session_state["booking_doctor_id"] = doctor_id
        _reset_selection()

    selected_doctor = doctor_map.get(doctor_id) or {}
    doctor_name = selected_doctor.get("full_name") or "this doctor"

    # ---------------- Step 3: date ----------------
    avail_res = catalog.availability(doctor_id=doctor_id)
    if not avail_res.success:
        display_api_error(avail_res)
        return
    if not avail_res.data:
        empty_state(
            f"{doctor_name} has no open slots right now.",
            "Choose a different doctor or department.",
            icon="",
        )
        return

    today = datetime.now().date()
    window_end = today + timedelta(days=BOOKING_WINDOW_DAYS - 1)
    slots_by_date = {}

    # Only future dates inside the booking window are offered.
    for slot in avail_res.data:
        slot_dt = slot_datetime(slot)
        if slot_dt is None:
            continue
        if today <= slot_dt.date() <= window_end:
            slots_by_date.setdefault(slot_dt.date(), []).append(slot)

    calendar_days = sorted(slots_by_date.keys())
    if not calendar_days:
        empty_state(
            f"{doctor_name} has no open slots in the next {BOOKING_WINDOW_DAYS} days.",
            "Choose a different doctor or check back soon.",
            icon="",
        )
        return

    date_chips(
        calendar_days,
        session_key="booking_date",
        key_prefix="appt_date",
        label="3. Choose a Date",
        hint=f"Only future dates with open slots in the next {BOOKING_WINDOW_DAYS} days are shown.",
        clear_keys_on_change=["booking_slot_id"],
    )

    selected_date = st.session_state.get("booking_date")
    if not selected_date:
        return

    # ---------------- Step 4: slot ----------------
    _render_slot_selection(
        selected_date,
        doctor_id=doctor_id,
        doctor_map=doctor_map,
        department_name=dept,
        slots=sorted(slots_by_date.get(selected_date, []), key=lambda s: str(s.get("start_time") or "")),
        appt_service=appt_service,
    )


def _render_slot_selection(
    selected_date,
    doctor_id: str,
    doctor_map: dict,
    department_name: str,
    slots: list,
    appt_service,
) -> None:
    """Descriptive slot cards, waiting-time preview, summary, and confirm."""
    st.markdown(f"**4. Choose a Time Slot: {selected_date.strftime('%A, %d %B %Y')}**")

    if not slots:
        st.info("All slots for this date are taken, please choose another date.")
        return

    slot_cols = st.columns(min(2, len(slots)), gap="medium")
    for idx, slot in enumerate(slots):
        slot_id = slot.get("availability_id")
        is_selected = st.session_state["booking_slot_id"] == slot_id
        with slot_cols[idx % len(slot_cols)]:
            with st.container(border=True):
                st.markdown(f"**{slot_time_label(slot)}**")
                st.caption(selected_date.strftime("%A, %d %B %Y"))
                st.caption(
                    f"{doctor_display(doctor_map, doctor_id)} · {department_name}"
                )
                if st.button(
                    "Selected" if is_selected else "Select",
                    key=f"slot_{slot_id}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                    icon=":material/schedule:",
                ):
                    st.session_state["booking_slot_id"] = slot_id
                    st.rerun()

    # ---------------- Step 5: review + confirm ----------------
    chosen_slot_id = st.session_state["booking_slot_id"]
    chosen_slot = next((s for s in slots if s.get("availability_id") == chosen_slot_id), None)
    if not chosen_slot:
        return

    st.divider()
    st.markdown("**5. Review & Confirm**")

    # Backend waiting-time forecast for the selected slot.
    show_booking_wait_preview(
        doctor_id,
        slot_scheduled_start(chosen_slot),
        cache_key=str(chosen_slot_id),
        availability_id=chosen_slot_id,
    )

    slot_dt = slot_datetime(chosen_slot)
    with st.container(border=True):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.write(f"**Department:** {department_name}")
            st.write(f"**Doctor:** {doctor_display(doctor_map, doctor_id, specialization=True)}")
        with c2:
            if slot_dt:
                st.write(f"**Date:** {slot_dt.strftime('%A, %d %B %Y')}")
                st.write(f"**Time:** {slot_dt.strftime('%I:%M %p')}")
            else:
                st.write(f"**Date & Time:** {format_datetime(slot_scheduled_start(chosen_slot))}")
            st.write(f"**Slot ID:** `{short_id(chosen_slot_id)}`")

    reason = st.text_input(
        "Visit reason (optional)",
        value=st.session_state.get("booking_reason", ""),
        key="booking_reason_input",
        placeholder="e.g. Follow-up for hypertension review",
        max_chars=REASON_MAX,
        help=f"Up to {REASON_MAX} characters.",
    )
    st.session_state["booking_reason"] = reason
    reason_value = (reason or "").strip()
    if len(reason_value) > REASON_MAX:
        st.error(f"The visit reason must be at most {REASON_MAX} characters.")
        return

    if st.button(
        "Confirm Booking",
        type="primary",
        icon=":material/verified:",
        key="confirm_booking_final",
    ):
        with loading("Booking your appointment"):
            result = appt_service.book(
                doctor_id=doctor_id,
                availability_id=chosen_slot_id,
                reason=reason_value or None,
            )
        if result.success:
            appointment_id = (result.data or {}).get("appointment_id")
            message = "Your appointment has been booked successfully."
            if appointment_id:
                message = f"Your appointment has been booked successfully. Appointment ID: {appointment_id}"
            set_flash("appointments", "success", message, code=appointment_id)
            _reset_selection(include_doctor=False)
            st.session_state["booking_reason"] = ""
            st.rerun()
        else:
            display_api_error(result)


# =====================================================================
# Existing appointments
# =====================================================================
def render_appointment_row(a: dict, doctor_map: dict, key_prefix: str = "appt", actions: bool = True) -> None:
    """Compact expandable bar: essentials collapsed, actions + visit record open.

    The visit record (prescriptions, tests, bill) is only fetched once the row
    is opened, so a long list never triggers one request per appointment.
    """
    status = a.get("appointment_status")
    appointment_id = a.get("appointment_id")
    is_completed = status == "completed"
    unpaid = is_completed and a.get("payment_status_at_booking") in PENDING_PAYMENT_STATES

    meta = f"{format_datetime(a.get('scheduled_start'))} · {doctor_display(doctor_map, a.get('doctor_id'))}"

    def actions_body() -> None:
        # Completed visit: feedback and payment entry points. Both now live in
        # another section of this same page, so they select it instead of
        # navigating to a separate page.
        if is_completed:
            c1, c2 = st.columns(2, gap="small")
            with c1:
                if st.button(
                    "Give feedback",
                    key=f"{key_prefix}_fb_{appointment_id}",
                    icon=":material/star:",
                    type="primary" if not unpaid else "secondary",
                    width="stretch",
                ):
                    request_section("Feedback")
            with c2:
                if st.button(
                    "Pay invoice" if unpaid else "View payments",
                    key=f"{key_prefix}_pay_{appointment_id}",
                    icon=":material/credit_card:",
                    type="primary" if unpaid else "secondary",
                    width="stretch",
                ):
                    request_section("Payments")
            if unpaid:
                st.caption(
                    "This visit has an outstanding invoice, the Payments section "
                    "has it listed below."
                )
        elif status in ("booked", "confirmed"):
            c1, c2 = st.columns(2, gap="small")
            with c1:
                if st.button(
                    "Reschedule",
                    key=f"{key_prefix}_resch_{appointment_id}",
                    icon=":material/event:",
                    width="stretch",
                ):
                    st.session_state["reschedule_target"] = appointment_id
                    st.rerun()
            with c2:
                if st.button(
                    "Cancel Appointment",
                    key=f"{key_prefix}_cancel_{appointment_id}",
                    width="stretch",
                ):
                    st.session_state["cancel_target"] = appointment_id
                    st.rerun()

        st.markdown("**Visit details**")
        render_visit_detail(appointment_id)

    expandable_row(
        str(appointment_id),
        title=f"{a.get('department_name') or 'Department'} · {doctor_display(doctor_map, a.get('doctor_id'))}",
        meta=meta,
        pill=status or "unknown",
        id_text=f"Appointment {appointment_id}",
        actions=actions_body,
    )


def render_visit_detail(appointment_id) -> None:
    """Full visit record: appointment, prescriptions, orders and the bill."""
    if not appointment_id:
        st.caption("No appointment details are available.")
        return

    with loading("Loading visit details"):
        res = AppointmentService().get(appointment_id)
    if not res.success:
        display_api_error(res)
        return

    data = res.data or {}
    doctor = data.get("doctor") or {}
    department = data.get("department") or {}

    i1, i2 = st.columns(2)
    with i1:
        st.write(f"**Doctor:** {doctor.get('full_name') or 'Doctor not set'}")
        if doctor.get("specialization"):
            st.caption(str(doctor["specialization"]))
        st.write(f"**Scheduled:** {format_datetime(data.get('scheduled_start'))}")
        st.write(f"**Status:** {APPOINTMENT_STATUSES.get(data.get('appointment_status'), data.get('appointment_status') or '—')}")
    with i2:
        st.write(f"**Department:** {department.get('name') or data.get('department_name') or 'Department not set'}")
        st.write(f"**Appointment ID:** `{short_id(data.get('appointment_id'))}`")
        if data.get("actual_checkin_time"):
            st.caption(f"Checked in {format_datetime(data.get('actual_checkin_time'))}")
        if data.get("actual_service_end"):
            st.caption(f"Visit completed {format_datetime(data.get('actual_service_end'))}")

    st.markdown("**Prescriptions**")
    render_prescriptions_table(data.get("prescriptions"))

    st.markdown("**Diagnostic tests**")
    render_diagnostic_orders_table(data.get("diagnostic_test_orders"))

    st.markdown("**Bill**")
    render_billing_summary(data.get("billing_summary"))


def render_reschedule_flow(appointment_id: str, appt_service, catalog, doctor_map: dict) -> None:
    """Pick a new slot for the SAME doctor (backend contract) and reschedule."""
    st.divider()
    st.subheader("Reschedule Appointment")
    st.caption("Select a new date and time slot with the same doctor. The reschedule takes effect immediately after confirmation.")

    appt_res = appt_service.get(appointment_id)
    if not appt_res.success:
        display_api_error(appt_res)
        if st.button("Close", key="resch_close_error"):
            st.session_state.pop("reschedule_target", None)
            st.rerun()
        return
    appt = appt_res.data or {}

    doctor_id = appt.get("doctor_id") or (appt.get("doctor") or {}).get("doctor_id")
    with st.container(border=True):
        st.write(f"**{appt.get('department_name') or 'Department'}** · "
                 f"{doctor_display(doctor_map, doctor_id, specialization=True)}")
        st.caption(f"Current appointment: {format_datetime(appt.get('scheduled_start'))} "
                   f"· ID {short_id(appointment_id)}")

    avail_res = catalog.availability(doctor_id=doctor_id)
    if not avail_res.success:
        display_api_error(avail_res)
        return
    if not avail_res.data:
        st.info("No alternative slots available with this doctor at the moment.")
        return

    today = datetime.now().date()
    slots_by_date = {}
    for slot in avail_res.data:
        slot_dt = slot_datetime(slot)
        if not slot_dt:
            continue
        if today <= slot_dt.date() <= today + timedelta(days=BOOKING_WINDOW_DAYS - 1):
            slots_by_date.setdefault(slot_dt.date(), []).append(slot)

    calendar_days = sorted(slots_by_date.keys())
    if not calendar_days:
        st.info("No alternative slots available in the booking window.")
        return

    date_chips(
        calendar_days,
        session_key="reschedule_date",
        key_prefix="resch_date",
        label="New Date",
        hint="Only future dates with open slots are shown.",
        clear_keys_on_change=["reschedule_slot_id"],
    )
    new_date = st.session_state.get("reschedule_date")
    if not new_date:
        return

    day_slots = sorted(slots_by_date.get(new_date, []), key=lambda s: str(s.get("start_time") or ""))
    if not day_slots:
        st.info("No slots available on this date.")
        return

    slot_cols = st.columns(min(3, len(day_slots)), gap="small")
    for idx, slot in enumerate(day_slots):
        slot_id = slot.get("availability_id")
        is_selected = st.session_state.get("reschedule_slot_id") == slot_id
        with slot_cols[idx % len(slot_cols)]:
            with st.container(border=True):
                st.markdown(f"**{slot_time_label(slot)}**")
                st.caption(new_date.strftime("%A, %d %B %Y"))
                if st.button(
                    "Selected" if is_selected else "Select",
                    key=f"resch_slot_{slot_id}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                ):
                    st.session_state["reschedule_slot_id"] = slot_id
                    st.rerun()

    new_slot_id = st.session_state.get("reschedule_slot_id")
    if not new_slot_id:
        return

    new_slot = next((s for s in day_slots if s.get("availability_id") == new_slot_id), None)
    if new_slot:
        show_booking_wait_preview(
            doctor_id,
            slot_scheduled_start(new_slot),
            cache_key=f"resch_{new_slot_id}",
            availability_id=new_slot_id,
        )

    with st.container(border=True):
        new_dt = slot_datetime(new_slot) if new_slot else None
        if new_dt:
            st.write(f"**New slot:** {new_dt.strftime('%A, %d %B %Y')} at {new_dt.strftime('%I:%M %p')}")
        else:
            st.write(f"**New slot:** {new_date.strftime('%A, %d %B %Y')} · {slot_time_label(new_slot or {})}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Confirm Reschedule", type="primary", icon=":material/event:", width="stretch",
                     key="confirm_reschedule"):
            with loading("Rescheduling your appointment"):
                result = appt_service.reschedule(appointment_id, new_slot_id)
            if result.success:
                set_flash(
                    "appointments",
                    "success",
                    f"Appointment rescheduled to {format_datetime((result.data or {}).get('scheduled_start'))} "
                    f"· ID {short_id(appointment_id)}",
                )
                st.session_state.pop("reschedule_target", None)
                st.session_state.pop("reschedule_date", None)
                st.session_state.pop("reschedule_slot_id", None)
                st.rerun()
            else:
                display_api_error(result)
    with c2:
        if st.button("Cancel Reschedule", width="stretch", key="cancel_reschedule"):
            st.session_state.pop("reschedule_target", None)
            st.session_state.pop("reschedule_date", None)
            st.session_state.pop("reschedule_slot_id", None)
            st.rerun()


def render_cancel_flow(appointment_id: str, appt_service, doctor_map: dict) -> None:
    """Inline confirmation for cancelling an appointment."""
    st.divider()
    st.subheader("Cancel Appointment")

    appt_res = appt_service.get(appointment_id)
    if appt_res.success:
        appt = appt_res.data or {}
        with st.container(border=True):
            st.write(f"**{appt.get('department_name') or 'Department'}** · "
                     f"{doctor_display(doctor_map, appt.get('doctor_id'), specialization=True)}")
            st.caption(f"{format_datetime(appt.get('scheduled_start'))} · ID {short_id(appointment_id)}")
    else:
        display_api_error(appt_res)

    st.warning("**Cancel this appointment?**")
    st.write("This will release the slot for other patients. This action cannot be undone.")

    reason = st.text_input(
        "Reason for cancellation (optional)",
        key="cancel_reason",
        placeholder="e.g. Scheduling conflict",
        max_chars=CANCEL_REASON_MAX,
        help=f"Up to {CANCEL_REASON_MAX} characters.",
    )
    reason_value = (reason or "").strip()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Yes, Cancel Appointment", type="primary", width="stretch",
                     key="confirm_cancel_appointment"):
            if len(reason_value) > CANCEL_REASON_MAX:
                st.error(f"The cancellation reason must be at most {CANCEL_REASON_MAX} characters.")
            else:
                with loading("Cancelling your appointment"):
                    result = appt_service.cancel(appointment_id, reason=reason_value or None)
                if result.success:
                    set_flash("appointments", "success",
                              f"Appointment {short_id(appointment_id)} has been cancelled.")
                    st.session_state.pop("cancel_target", None)
                    st.session_state.pop("cancel_reason", None)
                    st.rerun()
                else:
                    display_api_error(result)
    with c2:
        if st.button("Keep Appointment", width="stretch", key="keep_appointment"):
            st.session_state.pop("cancel_target", None)
            st.session_state.pop("cancel_reason", None)
            st.rerun()


if __name__ == "__main__":
    render()
