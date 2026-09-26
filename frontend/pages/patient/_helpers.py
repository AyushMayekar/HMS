"""
Shared helpers for the patient portal pages.

Small, page-local utilities shared by dashboard / appointments / payments /
feedback / requests: availability-slot parsing, descriptive labels, the
booking waiting-time preview, checked-in detection, and success/error flash
handling. Everything here renders only real backend data.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

import streamlit as st

from frontend.utils.states import display_api_error, format_datetime
from frontend.api.services import PredictionService


# Appointment statuses that end the visit lifecycle.
TERMINAL_APPOINTMENT_STATUSES = ("completed", "cancelled", "no_show")


# ---------------------------------------------------------------------------
# IDs and labels
# ---------------------------------------------------------------------------
def short_id(value: Optional[Any], length: int = 8) -> str:
    """Short, copy-friendly view of a real backend ID."""
    if not value:
        return "—"
    return str(value)[:length]


def build_doctor_map(doctors: Optional[list]) -> dict:
    """Map doctor_id -> doctor record from /catalog/doctors data."""
    if not doctors:
        return {}
    return {d.get("doctor_id"): d for d in doctors if d.get("doctor_id")}


def doctor_display(doctor_map: dict, doctor_id: Optional[str], specialization: bool = False) -> str:
    """Human label for a doctor ID using real catalog data."""
    doc = doctor_map.get(doctor_id) or {}
    name = doc.get("full_name")
    if not name:
        return "Doctor"
    label = f"{name}"
    if specialization and doc.get("specialization"):
        label += f" · {doc['specialization']}"
    return label


def appointment_context(appt: dict, doctor_map: dict, show_id: bool = True) -> str:
    """Descriptive one-line label: department · doctor · date/time · short ID."""
    dept = appt.get("department_name") or "Department"
    doc = doctor_display(doctor_map, appt.get("doctor_id"))
    when = format_datetime(appt.get("scheduled_start"))
    parts = [dept, doc, when]
    if show_id:
        parts.append(f"ID {short_id(appt.get('appointment_id'))}")
    return " · ".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Availability slots
# ---------------------------------------------------------------------------
def slot_datetime(slot: dict) -> Optional[datetime]:
    """Real start datetime of an availability row (slot_date + start_time)."""
    date_part = slot.get("slot_date")
    time_part = slot.get("start_time")
    if date_part and time_part:
        try:
            return datetime.fromisoformat(f"{date_part}T{time_part}")
        except ValueError:
            pass
    if time_part:
        try:
            return datetime.fromisoformat(str(time_part).replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def slot_time_label(slot: dict) -> str:
    """Clock label for a slot, e.g. '09:30 AM'."""
    dt = slot_datetime(slot)
    return dt.strftime("%I:%M %p") if dt else "—"


def slot_scheduled_start(slot: dict) -> Optional[str]:
    """Slot start in the backend's '<date>T<time>' booking format."""
    date_part = slot.get("slot_date")
    time_part = slot.get("start_time")
    if date_part and time_part:
        return f"{date_part}T{time_part}"
    dt = slot_datetime(slot)
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# Booking waiting-time preview (backend forecast, never computed here)
# ---------------------------------------------------------------------------
def show_booking_wait_preview(
    doctor_id: Optional[str],
    scheduled_start: Optional[str],
    cache_key: str,
    availability_id: Optional[str] = None,
) -> None:
    """
    Show the backend's expected waiting time for a slot the patient selected.

    Calls PredictionService().predict_booking_waiting_time(doctor_id,
    scheduled_start) once per slot and renders the returned
    {"predicted_waiting_min", "label", "basis"}. When the model has too little
    history the label/basis text is shown instead — no number is invented.
    """
    if not doctor_id or not scheduled_start:
        return

    state_key = f"_booking_wait::{cache_key}"
    preview = st.session_state.get(state_key)

    if preview is None:
        try:
            response = PredictionService().predict_booking_waiting_time(
                doctor_id, scheduled_start, availability_id=availability_id,
            )
        except Exception:
            st.caption("A waiting-time estimate is not available for this slot right now.")
            return
        if not response.success:
            # Surface the API failure once, then fall back quietly on reruns.
            st.session_state[state_key] = {"state": "error"}
            display_api_error(response)
            return

        data = response.data or {}
        minutes = data.get("predicted_waiting_min")
        preview = {
            "state": "ok",
            "minutes": float(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else None,
            "label": data.get("label"),
            "basis": data.get("basis"),
        }
        st.session_state[state_key] = preview

    if preview.get("state") == "error":
        st.caption("A waiting-time estimate is not available for this slot right now.")
        return

    minutes = preview.get("minutes")
    label = preview.get("label") or ""
    basis = preview.get("basis") or ""

    # The backend signals "not enough history" with an explicit label/basis
    # (and a 0.0 placeholder) — show that text instead of a fake number.
    insufficient = "insufficient history" in basis.lower() or label.lower() == "not enough data yet"

    if minutes is not None and not insufficient:
        st.markdown(f"**Expected waiting time: ~{round(minutes)} min**")
        if basis:
            st.caption(basis)
        elif label:
            st.caption(label)
    elif insufficient:
        st.info(f"{label or 'Not enough data yet'}: {basis}".rstrip(" :"))
    elif label:
        st.info(label)
    elif basis:
        st.info(basis)
    else:
        st.info("Not enough visit history yet to estimate a waiting time for this slot.")


# ---------------------------------------------------------------------------
# Checked-in waiting-time placement (post check-in, pre completion)
# ---------------------------------------------------------------------------
def is_checked_in(appt: dict) -> bool:
    """
    True when the patient is currently checked in for this appointment.

    Matches the backend lifecycle: a terminal status (completed / cancelled /
    no-show) is never "checked in"; otherwise an explicit arrived/present
    status or a recorded actual check-in timestamp counts.
    """
    status = appt.get("appointment_status")
    if status in TERMINAL_APPOINTMENT_STATUSES:
        return False
    if status in ("arrived", "present"):
        return True
    return bool(appt.get("actual_checkin_time"))


def predicted_wait_minutes(appt: dict) -> Optional[int]:
    """Predicted waiting time carried on the appointment row, if present."""
    for key in ("predicted_waiting_min", "predicted_wait_minutes", "predicted_wait_min"):
        value = appt.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value))
    return None


# ---------------------------------------------------------------------------
# Success / error flash (messages that survive a st.rerun)
# ---------------------------------------------------------------------------
def set_flash(page: str, kind: str, message: str, code: Optional[str] = None) -> None:
    """Queue a success/error/warning/info message to render after a rerun."""
    st.session_state[f"_flash::{page}"] = {"kind": kind, "message": message, "code": code}


def render_flash(page: str) -> None:
    """Render and clear any queued flash for this page."""
    flash = st.session_state.pop(f"_flash::{page}", None)
    if not flash:
        return
    kind = flash.get("kind", "info")
    renderer = getattr(st, kind, st.info)
    renderer(flash.get("message", ""))
    if flash.get("code"):
        st.code(str(flash["code"]), language=None)


# ---------------------------------------------------------------------------
# Inline validation helpers
# ---------------------------------------------------------------------------
_CARD_RE = re.compile(r"^\d{12,19}$")
_UPI_RE = re.compile(r"^[A-Za-z0-9._-]{2,}@[A-Za-z0-9._-]{2,}$")


def card_number_error(value: Optional[str]) -> Optional[str]:
    """Inline validation for a card number (12-19 digits, spaces allowed)."""
    digits = re.sub(r"\s+", "", value or "")
    if not digits:
        return "Enter the card number to continue."
    if not digits.isdigit():
        return "A card number can only contain digits (spaces are allowed)."
    if not _CARD_RE.match(digits):
        return "A card number must be between 12 and 19 digits."
    return None


def upi_id_error(value: Optional[str]) -> Optional[str]:
    """Inline validation for a UPI ID (name@bank format)."""
    candidate = (value or "").strip()
    if not candidate:
        return "Enter the UPI ID to continue."
    if not _UPI_RE.match(candidate):
        return "Enter a valid UPI ID in the format name@bank, e.g. riya@okhdfcbank."
    return None
