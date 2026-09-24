"""
Agent discovery and execution adapters.

The agent never talks to Supabase directly. Read/discovery helpers call the
existing service layer to resolve human-friendly input into real records, and
execution helpers call the existing mutation services after confirmation.
"""
from __future__ import annotations

from typing import Any


def discover_departments() -> list[dict[str, Any]]:
    """Return active departments from the existing department service."""
    from app.services.department_service import list_departments

    return list_departments(status="active", limit=200)["departments"]


def discover_doctors(department_id: str) -> list[dict[str, Any]]:
    """Return active doctors for a real department ID."""
    from app.services.doctor_service import list_doctors

    return list_doctors(
        department_id=department_id,
        status="active",
        limit=200,
    )["doctors"]


def discover_availability(
    *,
    doctor_id: str,
    slot_date: str,
) -> list[dict[str, Any]]:
    """Return live available slots for a real doctor/date pair."""
    from app.services.availability_service import list_availability

    return list_availability(
        doctor_id=doctor_id,
        slot_date=slot_date,
        status="available",
        limit=200,
    )["availability"]


def discover_patient_appointments(patient_id: str) -> list[dict[str, Any]]:
    """Return the authenticated patient's live appointments."""
    from app.services.patient_appointment_service import list_patient_appointments

    return list_patient_appointments(patient_id=patient_id, limit=200)["appointments"]


def execute_book_appointment(
    *,
    patient_id: str,
    doctor_id: str,
    availability_id: str,
) -> dict[str, Any]:
    """Execute the real booking service after confirmation."""
    from app.services.patient_appointment_service import book_appointment

    return book_appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        availability_id=availability_id,
        booking_channel="ai_agent",
    )


def execute_reschedule_appointment(
    *,
    patient_id: str,
    appointment_id: str,
    availability_id: str,
) -> dict[str, Any]:
    """Execute the real reschedule service after confirmation."""
    from app.services.patient_appointment_service import reschedule_patient_appointment

    return reschedule_patient_appointment(
        patient_id=patient_id,
        appointment_id=appointment_id,
        new_availability_id=availability_id,
    )


def execute_cancel_appointment(
    *,
    patient_id: str,
    appointment_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Execute the real cancellation service after confirmation."""
    from app.services.patient_appointment_service import cancel_patient_appointment

    return cancel_patient_appointment(
        patient_id=patient_id,
        appointment_id=appointment_id,
        reason=reason,
    )


def execute_admin_request(
    *,
    patient_id: str,
    category: str,
    description: str,
) -> dict[str, Any]:
    """Execute the real admin-request service after confirmation."""
    from app.services.admin_request_service import create_admin_request

    return create_admin_request(
        patient_id=patient_id,
        category=category,
        description=description,
        created_via="ai_agent",
    )


def discover_doctor(doctor_id: str) -> dict[str, Any]:
    """Return one doctor using the existing doctor service."""
    from app.services.doctor_service import get_doctor

    return get_doctor(doctor_id)


def discover_department(department_id: str) -> dict[str, Any]:
    """Return one department using the existing department service."""
    from app.services.department_service import get_department

    return get_department(department_id)


def resolve_option(
    answer: Any,
    options: list[dict[str, Any]],
    *,
    id_key: str,
    label_fn,
) -> dict[str, Any] | None:
    """Resolve a user's selection only against records returned by discovery."""
    if not options:
        return None

    value: Any = answer
    if isinstance(answer, dict):
        for key in ("selected", "selection", "index", "value", "name", "label", id_key):
            if key in answer:
                value = answer[key]
                break

    if value is None:
        return None

    token = str(value).strip()
    if not token:
        return None

    # Numbered menu answers like "3. Dr. Ramesh" or "5) ENT": use the number
    # when it is in range, then fall back to matching the remaining text.
    import re
    remainder = token
    numbered = re.match(r"^(\d+)\s*[.)\-]?\s*(.*)$", token)
    if numbered:
        index = int(numbered.group(1)) - 1
        if 0 <= index < len(options):
            return options[index]
        remainder = numbered.group(2).strip() or token
        token = remainder

    if token.isdigit():
        index = int(token) - 1
        if 0 <= index < len(options):
            return options[index]

    normalized = " ".join(token.lower().split())

    exact_id = [
        option for option in options
        if str(option.get(id_key, "")).strip().lower() == normalized
    ]
    if len(exact_id) == 1:
        return exact_id[0]

    exact_label = [
        option for option in options
        if " ".join(str(label_fn(option)).lower().split()) == normalized
    ]
    if len(exact_label) == 1:
        return exact_label[0]

    contains = [
        option for option in options
        if normalized in " ".join(str(label_fn(option)).lower().split())
        or " ".join(str(label_fn(option)).lower().split()) in normalized
    ]
    return contains[0] if len(contains) == 1 else None
