"""
Doctor Consultations page.

Assigned visits only: start the service, prescribe medicines, order
diagnostic tests and end the service. Check-in and no-show stay with the
front desk; every charge shown here is calculated by the backend.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.billing import (
    render_billing_summary,
    render_diagnostic_orders_table,
    render_prescriptions_table,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.services import DoctorService
from frontend.config import APPOINTMENT_STATUSES

FLASH_KEY = "doctor_visit_flash"
TARGET_KEY = "doctor_visit_target"

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")
PRIORITIES = ["routine", "urgent", "stat"]


def render():
    page_head(
        "Consultations",
        "Your assigned patients: start the visit, prescribe, order tests, and close the encounter.",
        noindex=True,
    )
    require_role(["doctor"])
    current_user()

    breadcrumb(["Doctor", "Consultations"])

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash.get("message", "Action completed."))
        if flash.get("billing"):
            render_billing_summary(flash["billing"])

    service = DoctorService()
    target = st.session_state.get(TARGET_KEY)
    if target:
        if not render_visit_detail(service, target):
            st.session_state.pop(TARGET_KEY, None)
        st.divider()

    render_visit_list(service)


def render_visit_list(service: DoctorService) -> None:
    """Status-filtered list of the appointments assigned to this doctor."""
    section_title(
        "Assigned Appointments",
        "Only visits assigned to you. The front desk checks patients in; you start and end the service.",
    )

    status_filter = st.selectbox(
        "Appointment status",
        ["All"] + list(APPOINTMENT_STATUSES.keys()),
        format_func=lambda s: APPOINTMENT_STATUSES.get(s, "All statuses"),
        key="doctor_appt_status",
    )

    res = service.appointments(
        status=status_filter if status_filter != "All" else None,
        limit=200,
    )
    if not res.success:
        display_api_error(res)
        return

    appointments = res.data or []
    appointments.sort(key=lambda a: str(a.get("scheduled_start") or ""))

    if not appointments:
        empty_state(
            "No assigned appointments with this status.",
            "Adjust the status filter above — new bookings assigned to you appear here.",
            icon="",
        )
        return

    section_title(f"{len(appointments)} appointment(s)", "Soonest first.")

    for a in appointments:
        render_visit_row(a)


def render_visit_row(a: dict) -> None:
    """One assigned visit with its lifecycle state and an Open action."""
    appointment_id = a.get("appointment_id")
    status = a.get("appointment_status") or "unknown"
    patient = a.get("patient_name") or "Patient name not available"

    with st.container(border=True):
        col1, col2, col3 = st.columns([3.4, 1.6, 1])
        with col1:
            st.write(
                f"**{patient}** · {a.get('department_name') or 'Department not set'}"
            )
            details = [format_datetime(a.get("scheduled_start"))]
            if a.get("patient_email"):
                details.append(str(a.get("patient_email")))
            details.append(f"Appointment `#{str(appointment_id or '')[:8]}`")
            if a.get("reason"):
                details.append(str(a.get("reason")))
            st.caption(" · ".join(details))
        with col2:
            if a.get("actual_checkin_time"):
                st.caption(f"Checked in {format_datetime(a.get('actual_checkin_time'))}")
            elif status == "booked":
                st.caption("Waiting for front-desk check-in")
            if a.get("actual_service_start"):
                st.caption(f"Service started {format_datetime(a.get('actual_service_start'))}")
        with col3:
            status_pill(status)

        if st.button(
            "Open visit",
            key=f"doc_list_open_{appointment_id}",
            width="stretch",
            icon=":material/clinical_notes:",
        ):
            st.session_state[TARGET_KEY] = appointment_id
            st.rerun()


def render_visit_detail(service: DoctorService, appointment_id: str) -> bool:
    """Full encounter view: state, orders, bill and the available actions."""
    res = service.get(appointment_id)
    if not res.success:
        display_api_error(res)
        if st.button("Back to list", key="doc_detail_back_error"):
            st.session_state.pop(TARGET_KEY, None)
            st.rerun()
        return False

    a = res.data or {}
    status = a.get("appointment_status") or "unknown"
    patient = (a.get("patient") or {}).get("full_name") or a.get("patient_name") or "Patient"
    checked_in = bool(a.get("actual_checkin_time"))
    service_started = bool(a.get("actual_service_start"))
    service_ended = bool(a.get("actual_service_end"))
    resolved = status in RESOLVED_STATUSES

    with st.container(border=True):
        head1, head2, head3 = st.columns([4, 2, 1])
        with head1:
            st.write(
                f"**{patient}** · {a.get('department_name') or 'Department not set'}"
            )
            details = [format_datetime(a.get("scheduled_start"))]
            if (a.get("patient") or {}).get("email"):
                details.append(str(a["patient"]["email"]))
            details.append(f"Appointment `#{str(appointment_id)[:8]}`")
            if a.get("reason"):
                details.append(str(a.get("reason")))
            st.caption(" · ".join(details))
        with head2:
            if checked_in:
                st.caption(f"Checked in {format_datetime(a.get('actual_checkin_time'))}")
            else:
                st.caption("Not checked in yet")
            if service_started:
                st.caption(f"Service started {format_datetime(a.get('actual_service_start'))}")
            if service_ended:
                st.caption(f"Service ended {format_datetime(a.get('actual_service_end'))}")
        with head3:
            status_pill(status)
            if st.button("Back", key="doc_detail_back", width="stretch"):
                st.session_state.pop(TARGET_KEY, None)
                st.rerun()

    # ---------- Current bill ----------
    section_title(
        "Current Bill",
        "Consultation charge plus everything prescribed or ordered for this visit — recalculated by the server.",
    )
    render_billing_summary(a.get("billing_summary"))

    st.divider()

    # ---------- Clinical record ----------
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Prescriptions**")
        render_prescriptions_table(a.get("prescriptions"))
    with c2:
        st.markdown("**Diagnostic orders**")
        render_diagnostic_orders_table(a.get("diagnostic_test_orders"))

    st.divider()

    # ---------- Lifecycle actions ----------
    section_title("Visit Actions", "Check-in is handled by the front desk; service start and end are yours.")

    can_start = status not in RESOLVED_STATUSES and checked_in and not service_started
    in_service = status not in RESOLVED_STATUSES and service_started and not service_ended

    if resolved:
        st.info(
            f"This visit is '{status}' — no further clinical actions are available."
        )
    elif not checked_in:
        st.info("The patient has not been checked in by the front desk yet.")
    elif can_start:
        if st.button(
            "Start Service",
            type="primary",
            icon=":material/play_arrow:",
            key=f"doc_start_{appointment_id}",
        ):
            _run(service.start_service, appointment_id, "Consultation started.")
    elif in_service:
        render_clinical_actions(service, appointment_id)
        if st.button(
            "End Service",
            type="primary",
            icon=":material/stop:",
            key=f"doc_end_{appointment_id}",
        ):
            _run(service.end_service, appointment_id, "Consultation ended and the visit is complete.")

    return True


def render_clinical_actions(service: DoctorService, appointment_id: str) -> None:
    """Prescription and diagnostic-order forms for an in-service visit."""
    med_res = service.medicines()
    if not med_res.success:
        display_api_error(med_res)
        return
    medicines = med_res.data or []
    medicine_ids = [m.get("medicine_id") for m in medicines if m.get("medicine_id")]
    medicine_map = {m.get("medicine_id"): m for m in medicines}

    test_res = service.diagnostic_tests()
    if not test_res.success:
        display_api_error(test_res)
        return
    tests = test_res.data or []
    test_ids = [t.get("test_id") for t in tests if t.get("test_id")]
    test_map = {t.get("test_id"): t for t in tests}

    p1, p2 = st.columns(2, gap="large")

    with p1:
        st.markdown("**Prescribe a medicine**")
        if not medicine_ids:
            st.caption("No active medicines in the catalog.")
        else:
            with st.form(key=f"rx_form_{appointment_id}", clear_on_submit=True):
                medicine_id = st.selectbox(
                    "Medicine",
                    medicine_ids,
                    format_func=lambda mid: _medicine_label(medicine_map.get(mid) or {}),
                    key=f"rx_medicine_{appointment_id}",
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    quantity = st.number_input(
                        "Quantity", min_value=1, value=1, step=1,
                        key=f"rx_qty_{appointment_id}",
                    )
                    duration_days = st.number_input(
                        "Duration (days)", min_value=1, value=5, step=1,
                        key=f"rx_days_{appointment_id}",
                    )
                with col_b:
                    dosage = st.text_input(
                        "Dosage", value="1 tablet",
                        key=f"rx_dosage_{appointment_id}",
                        help="e.g. 1 tablet, 5 ml",
                    )
                    frequency = st.text_input(
                        "Frequency", value="Twice daily",
                        key=f"rx_freq_{appointment_id}",
                        help="e.g. Twice daily, After food",
                    )
                instructions = st.text_input(
                    "Instructions (optional)",
                    key=f"rx_instructions_{appointment_id}",
                    placeholder="e.g. Take after food",
                )
                submitted = st.form_submit_button(
                    "Add Prescription", type="primary", width="stretch"
                )
            if submitted:
                result = service.create_prescription(
                    appointment_id=appointment_id,
                    medicine_id=medicine_id,
                    quantity=int(quantity),
                    dosage=dosage.strip() or "1 tablet",
                    frequency=frequency.strip() or "As directed",
                    duration_days=int(duration_days),
                    instructions=instructions.strip() or None,
                )
                _handle_order_result(
                    result,
                    f"{_medicine_label(medicine_map.get(medicine_id) or {})} prescribed.",
                )

    with p2:
        st.markdown("**Order a diagnostic test**")
        if not test_ids:
            st.caption("No active diagnostic tests in the catalog.")
        else:
            with st.form(key=f"dx_form_{appointment_id}", clear_on_submit=True):
                test_id = st.selectbox(
                    "Test",
                    test_ids,
                    format_func=lambda tid: _test_label(test_map.get(tid) or {}),
                    key=f"dx_test_{appointment_id}",
                )
                col_c, col_d = st.columns(2)
                with col_c:
                    quantity = st.number_input(
                        "Quantity", min_value=1, value=1, step=1,
                        key=f"dx_qty_{appointment_id}",
                    )
                with col_d:
                    priority = st.selectbox(
                        "Priority", PRIORITIES,
                        format_func=lambda p: p.title(),
                        key=f"dx_priority_{appointment_id}",
                    )
                notes = st.text_input(
                    "Notes (optional)",
                    key=f"dx_notes_{appointment_id}",
                    placeholder="e.g. Fasting sample",
                )
                submitted = st.form_submit_button(
                    "Add Diagnostic Order", type="primary", width="stretch"
                )
            if submitted:
                result = service.create_diagnostic_order(
                    appointment_id=appointment_id,
                    test_id=test_id,
                    quantity=int(quantity),
                    priority=priority,
                    notes=notes.strip() or None,
                )
                _handle_order_result(
                    result,
                    f"{_test_label(test_map.get(test_id) or {})} ordered.",
                )


def _run(action, appointment_id: str, success_text: str) -> None:
    """Run a lifecycle action and standardize the feedback."""
    result = action(appointment_id)
    if result.success:
        st.session_state[FLASH_KEY] = {"message": success_text}
        st.rerun()
    else:
        display_api_error(result)


def _handle_order_result(result, success_text: str) -> None:
    """Show the refreshed billing after a prescription / order is recorded."""
    if not result.success:
        display_api_error(result)
        return
    billing = (result.raw or {}).get("billing")
    st.session_state[FLASH_KEY] = {
        "message": f"{success_text} The invoice has been recalculated.",
        "billing": billing,
    }
    st.rerun()


def _medicine_label(medicine: dict) -> str:
    name = medicine.get("name") or "Medicine"
    charge = medicine.get("charge")
    if charge is not None:
        return f"{name} · INR {float(charge):,.2f}"
    return name


def _test_label(test: dict) -> str:
    name = test.get("name") or "Diagnostic test"
    charge = test.get("charge")
    if charge is not None:
        return f"{name} · INR {float(charge):,.2f}"
    return name


if __name__ == "__main__":
    render()
