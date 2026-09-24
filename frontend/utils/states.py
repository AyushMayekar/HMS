"""
Error handling and UI state utilities for the Streamlit frontend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import streamlit as st

from frontend.api.client import APIResponse, APIError
from frontend.config import COLORS


@dataclass
class UIState:
    """Represents a UI state with message and type."""
    message: str
    state_type: str  # success, error, warning, info, loading
    details: Optional[str] = None

    def render(self) -> None:
        """Render the UI state using Streamlit components."""
        if self.state_type == "success":
            st.success(self.message)
        elif self.state_type == "error":
            st.error(self.message)
        elif self.state_type == "warning":
            st.warning(self.message)
        elif self.state_type == "info":
            st.info(self.message)
        elif self.state_type == "loading":
            st.info(self.message)


def handle_api_response(response: APIResponse, success_message: Optional[str] = None) -> bool:
    """
    Handle an API response and display appropriate UI feedback.

    Returns:
        True if response was successful, False otherwise.
    """
    if response.success:
        if success_message:
            st.success(success_message)
        return True
    else:
        display_api_error(response)
        return False


def display_api_error(response: APIResponse) -> None:
    """Display a user-friendly error message from an API response.

    The plain-language message is shown first (standard feedback pattern);
    technical details stay available behind a collapsed expander and raw
    backend exceptions are never surfaced directly.
    """
    error_code = response.error_code or "UNKNOWN_ERROR"
    error_message = response.error_message or "An unknown error occurred."
    request_id = response.request_id

    # Map error codes to user-friendly messages
    friendly_messages = {
        "VALIDATION_ERROR": "Please check your input and try again.",
        "UNAUTHORIZED": "Your session has expired. Please sign in again.",
        "FORBIDDEN": "You don't have permission to perform this action.",
        "NOT_FOUND": "The requested resource was not found.",
        "CONFLICT": "This action conflicts with the current state. Please refresh and try again.",
        "RATE_LIMITED": "Too many requests. Please wait a moment and try again.",
        "INTERNAL_SERVER_ERROR": "Something went wrong on our side. Please try again later.",
        "SERVICE_UNAVAILABLE": "The service is temporarily unavailable. Please try again later.",
        "TIMEOUT": "The request timed out. Please try again.",
        "CONNECTION_ERROR": "Unable to connect to the server. Please check your connection.",
        "REQUEST_ERROR": "The request failed. Please try again.",
        "INVALID_EMAIL": "Please enter a valid email address.",
        "OTP_INVALID": "The OTP you entered is incorrect.",
        "OTP_EXPIRED": "The OTP has expired. Please request a new one.",
        "OTP_LOCKED": "Too many incorrect attempts. Please request a new OTP.",
        "OTP_NOT_FOUND": "No OTP found. Please request a new one.",
        "ACCOUNT_EXISTS": "An account with this email already exists. Please sign in.",
        "ACCOUNT_INACTIVE": "This account is inactive. Please contact an administrator.",
        "SLOT_UNAVAILABLE": "The selected slot is no longer available.",
        "SLOT_EXPIRED": "The selected slot has expired. Please choose a future slot.",
        "HOLD_EXPIRED": "Your payment window has expired. Please select a slot again.",
        "FORBIDDEN": "You don't have permission to perform this action.",
        "INVALID_OPERATION": "This operation cannot be performed at this time.",
        "APPOINTMENT_NOT_FOUND": "Appointment not found.",
        "AVAILABILITY_NOT_FOUND": "The selected availability slot was not found.",
        "DOCTOR_NOT_FOUND": "The selected doctor was not found.",
        "MEDICINE_NOT_FOUND": "The selected medicine was not found in the catalog.",
        "DIAGNOSTIC_TEST_NOT_FOUND": "The selected diagnostic test was not found in the catalog.",
        "DOCUMENT_NOT_FOUND": "Document not found.",
        "KNOWLEDGE_INDEXING_ERROR": "Failed to index the knowledge document.",
    }

    friendly = friendly_messages.get(error_code, error_message)

    # Standard feedback: the understandable message first…
    st.error(friendly)

    # …with technical detail kept one click away (never shown raw inline).
    with st.expander("Error Details", expanded=False):
        st.code(f"Error Code: {error_code}")
        st.code(f"Message: {error_message}")
        if request_id:
            st.code(f"Request ID: {request_id}")


def display_exception_error(exc: Exception, context: str = "") -> None:
    """Display a user-friendly error for an unexpected exception."""
    with st.expander("Error Details", expanded=False):
        st.code(f"Exception: {type(exc).__name__}")
        st.code(f"Message: {str(exc)}")
        if context:
            st.code(f"Context: {context}")

    st.error("Something went wrong. Please try again or contact support if the problem persists.")


def show_loading(message: str = "Loading...") -> None:
    """Show a loading indicator."""
    st.info(message)


def show_empty_state(
    message: str,
    hint: Optional[str] = None,
    icon: str = "",
) -> None:
    """Display a friendly empty state (no OS-emoji icon: platform-safe)."""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 2rem;
            background: var(--mc-surface, #FFFFFF);
            border: 1px dashed var(--mc-border, #E2E8F0);
            border-radius: 12px;
            margin: 1rem 0;
        ">
            <p style="margin: 0; font-weight: 600; color: var(--mc-text, #1E293B);">{message}</p>
            {f'<p style="margin: 0.5rem 0 0 0; color: var(--mc-muted, #64748B);">{hint}</p>' if hint else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_access_denied(message: str = "Access denied. You don't have permission to view this page.") -> None:
    """Display an access denied page."""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 3rem;
            background: var(--mc-surface, #FFFFFF);
            border: 1px solid var(--mc-border, #E2E8F0);
            border-radius: 12px;
            margin: 2rem auto;
            max-width: 500px;
        ">
            <h2 style="color: var(--mc-navy, #0B3C5D); margin-bottom: 1rem;">Access Denied</h2>
            <p style="color: var(--mc-text, #1E293B);">{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


def show_not_found(message: str = "Page not found.") -> None:
    """Display a 404 page."""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 3rem;
            background: var(--mc-surface, #FFFFFF);
            border: 1px solid var(--mc-border, #E2E8F0);
            border-radius: 12px;
            margin: 2rem auto;
            max-width: 500px;
        ">
            <h2 style="color: var(--mc-navy, #0B3C5D); margin-bottom: 1rem;">Page Not Found</h2>
            <p style="color: var(--mc-text, #1E293B);">{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


def show_error_page(
    title: str = "Error",
    message: str = "An unexpected error occurred.",
    details: Optional[str] = None,
) -> None:
    """Display a generic error page."""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 3rem;
            background: var(--mc-surface, #FFFFFF);
            border: 1px solid var(--mc-border, #E2E8F0);
            border-radius: 12px;
            margin: 2rem auto;
            max-width: 600px;
        ">
            <h2 style="color: var(--mc-navy, #0B3C5D); margin-bottom: 1rem;">{title}</h2>
            <p style="color: var(--mc-text, #1E293B);">{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if details:
        with st.expander("Technical Details"):
            st.code(details)
    st.stop()


def status_pill(status: str, custom_label: Optional[str] = None) -> None:
    """Render a status pill for appointment/payment/request status."""
    from frontend.config import STATUS_PILL_CLASSES, APPOINTMENT_STATUSES, PAYMENT_STATUSES, REQUEST_STATUSES

    # Get display label
    label = custom_label or APPOINTMENT_STATUSES.get(status, PAYMENT_STATUSES.get(status, REQUEST_STATUSES.get(status, status)))
    pill_class = STATUS_PILL_CLASSES.get(status, "mc-pill-neutral")

    st.markdown(
        f'<span class="mc-pill {pill_class}">{label}</span>',
        unsafe_allow_html=True,
    )


def _to_display_tz(dt: "datetime") -> "datetime":
    """Convert an aware datetime to the configured hospital timezone.

    Backend timestamps are stored/returned as UTC. Displaying them raw is
    what made request times look "wrong". Naive values are returned
    unchanged (treated as already-local).
    """
    if dt.tzinfo is None:
        return dt
    try:
        from zoneinfo import ZoneInfo

        from frontend.config import CONFIG

        return dt.astimezone(ZoneInfo(CONFIG.hospital_timezone))
    except Exception:  # noqa: BLE001 — zoneinfo/tzdata may be unavailable
        return dt.astimezone()


def format_datetime(dt_str: Optional[str], format_str: str = "%d %b %Y, %I:%M %p") -> str:
    """Format a datetime string for display in hospital-local time."""
    if not dt_str:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _to_display_tz(dt).strftime(format_str)
    except (ValueError, TypeError, AttributeError):
        return dt_str


def format_date(dt_str: Optional[str], format_str: str = "%d %b %Y") -> str:
    """Format a date string for display in hospital-local time."""
    if not dt_str:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _to_display_tz(dt).strftime(format_str)
    except (ValueError, TypeError, AttributeError):
        return dt_str


def format_time(dt_str: Optional[str], format_str: str = "%I:%M %p") -> str:
    """Format a time string for display in hospital-local time."""
    if not dt_str:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return _to_display_tz(dt).strftime(format_str)
    except (ValueError, TypeError, AttributeError):
        return dt_str


def is_in_past(dt_str: Optional[str]) -> bool:
    """True when an ISO datetime is in the past (hospital-local now)."""
    if not dt_str:
        return False
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        dt = _to_display_tz(dt)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return dt < now
    except (ValueError, TypeError, AttributeError):
        return False