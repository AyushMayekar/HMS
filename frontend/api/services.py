"""
API service modules for the Meridian Care frontend.
Each service encapsulates API calls for a specific domain.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend.api.client import APIResponse, get_api_client
from frontend.api.endpoints import (
    PATIENT_APPOINTMENTS_BOOK,
    PATIENT_APPOINTMENTS_CANCEL,
    PATIENT_APPOINTMENTS_GET,
    PATIENT_APPOINTMENTS_LIST,
    PATIENT_APPOINTMENTS_RESCHEDULE,
)


class AppointmentService:
    """Service for patient appointment operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def book(
        self,
        doctor_id: str,
        availability_id: str,
        reason: Optional[str] = None,
    ) -> APIResponse:
        """Book a new appointment."""
        payload = {
            "doctor_id": doctor_id,
            "availability_id": availability_id,
        }
        if reason:
            payload["reason"] = reason
        return self.client.post(PATIENT_APPOINTMENTS_BOOK, json_data=payload)

    def list(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> APIResponse:
        """List patient's appointments."""
        params = {"limit": limit, "offset": offset}
        if status:
            params["appointment_status"] = status
        return self.client.get(PATIENT_APPOINTMENTS_LIST, params=params)

    def get(self, appointment_id: str) -> APIResponse:
        """Get a single appointment by ID."""
        endpoint = PATIENT_APPOINTMENTS_GET.format(appointment_id=appointment_id)
        return self.client.get(endpoint)

    def reschedule(self, appointment_id: str, new_availability_id: str) -> APIResponse:
        """Reschedule an appointment."""
        endpoint = PATIENT_APPOINTMENTS_RESCHEDULE.format(appointment_id=appointment_id)
        payload = {"new_availability_id": new_availability_id}
        return self.client.patch(endpoint, json_data=payload)

    def cancel(self, appointment_id: str, reason: Optional[str] = None) -> APIResponse:
        """Cancel an appointment."""
        endpoint = PATIENT_APPOINTMENTS_CANCEL.format(appointment_id=appointment_id)
        payload = {"reason": reason} if reason else None
        return self.client.post(endpoint, json_data=payload)


class PaymentService:
    """Service for patient payment operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def create(
        self,
        appointment_id: str,
        amount: float,
        currency: str = "INR",
        payment_method: str = "upi",
        insurance_used: bool = False,
        claim_required: bool = False,
        payment_method_reference: Optional[str] = None,
    ) -> APIResponse:
        """Create a payment for an appointment.

        ``payment_method_reference`` carries the method-specific input
        (card number or UPI id); the backend validates it.
        """
        from frontend.api.endpoints import PATIENT_PAYMENTS_CREATE
        payload = {
            "appointment_id": appointment_id,
            "amount": amount,
            "currency": currency,
            "payment_method": payment_method,
            "insurance_used": insurance_used,
            "claim_required": claim_required,
        }
        if payment_method_reference:
            payload["payment_method_reference"] = payment_method_reference
        return self.client.post(PATIENT_PAYMENTS_CREATE, json_data=payload)

    def list(self, limit: int = 50, offset: int = 0) -> APIResponse:
        """List patient's payments."""
        from frontend.api.endpoints import PATIENT_PAYMENTS_LIST
        return self.client.get(PATIENT_PAYMENTS_LIST, params={"limit": limit, "offset": offset})

    def get(self, payment_id: str) -> APIResponse:
        """Get a single payment by ID."""
        from frontend.api.endpoints import PATIENT_PAYMENTS_GET
        endpoint = PATIENT_PAYMENTS_GET.format(payment_id=payment_id)
        return self.client.get(endpoint)


class FeedbackService:
    """Service for patient feedback operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def submit(
        self,
        appointment_id: str,
        rating: int,
        comment: Optional[str] = None,
        feedback_channel: str = "form",
    ) -> APIResponse:
        """Submit feedback for an appointment."""
        from frontend.api.endpoints import PATIENT_FEEDBACK_SUBMIT
        payload = {
            "appointment_id": appointment_id,
            "rating": rating,
            "feedback_channel": feedback_channel,
        }
        if comment:
            payload["comment"] = comment
        return self.client.post(PATIENT_FEEDBACK_SUBMIT, json_data=payload)

    def list(self, limit: int = 50, offset: int = 0) -> APIResponse:
        """List patient's feedback submissions."""
        from frontend.api.endpoints import PATIENT_FEEDBACK_LIST
        return self.client.get(PATIENT_FEEDBACK_LIST, params={"limit": limit, "offset": offset})

    def get(self, feedback_id: str) -> APIResponse:
        """Get a single feedback by ID."""
        from frontend.api.endpoints import PATIENT_FEEDBACK_GET
        endpoint = PATIENT_FEEDBACK_GET.format(feedback_id=feedback_id)
        return self.client.get(endpoint)


class AdminRequestService:
    """Service for patient admin request operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def create(
        self,
        category: str,
        description: str,
        appointment_id: Optional[str] = None,
        payment_id: Optional[str] = None,
    ) -> APIResponse:
        """Create an administrative support request."""
        from frontend.api.endpoints import PATIENT_ADMIN_REQUESTS_CREATE
        params = {
            "category": category,
            "description": description,
        }
        if appointment_id:
            params["appointment_id"] = appointment_id
        if payment_id:
            params["payment_id"] = payment_id
        return self.client.post(PATIENT_ADMIN_REQUESTS_CREATE, params=params)

    def list(
        self,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> APIResponse:
        """List patient's admin requests."""
        from frontend.api.endpoints import PATIENT_ADMIN_REQUESTS_LIST
        params = {"limit": limit, "offset": offset}
        if status_filter:
            params["status_filter"] = status_filter
        return self.client.get(PATIENT_ADMIN_REQUESTS_LIST, params=params)

    def get(self, request_id: str) -> APIResponse:
        """Get a single admin request by ID."""
        from frontend.api.endpoints import PATIENT_ADMIN_REQUESTS_GET
        endpoint = PATIENT_ADMIN_REQUESTS_GET.format(request_id=request_id)
        return self.client.get(endpoint)


class ReminderService:
    """Service for patient reminder operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(self, limit: int = 50, offset: int = 0) -> APIResponse:
        """List patient's reminders."""
        from frontend.api.endpoints import PATIENT_REMINDERS_LIST
        return self.client.get(PATIENT_REMINDERS_LIST, params={"limit": limit, "offset": offset})


class PredictionService:
    """Service for prediction/forecasting endpoints used by pages."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def predict_booking_waiting_time(
        self,
        doctor_id: str,
        scheduled_start: str,
        availability_id: Optional[str] = None,
    ) -> APIResponse:
        """Expected waiting time for a slot, fetched from the backend
        BEFORE the appointment exists (booking-time preview).

        Returns APIResponse whose data is
        ``{"predicted_waiting_min": float, "label": str, "basis": str}``.
        """
        from frontend.api.endpoints import PREDICTIONS_BOOKING_WAITING_TIME_PREVIEW
        payload: dict[str, Any] = {
            "doctor_id": doctor_id,
            "scheduled_start": scheduled_start,
        }
        if availability_id:
            payload["availability_id"] = availability_id
        return self.client.post(PREDICTIONS_BOOKING_WAITING_TIME_PREVIEW, json_data=payload)

    def forecast_bed_demand(self, target_date: str) -> APIResponse:
        from frontend.api.endpoints import PREDICTIONS_BED_DEMAND
        return self.client.post(PREDICTIONS_BED_DEMAND, json_data={"target_date": target_date})

    def forecast_patient_flow(self, target_date: str) -> APIResponse:
        from frontend.api.endpoints import PREDICTIONS_PATIENT_FLOW
        return self.client.post(PREDICTIONS_PATIENT_FLOW, json_data={"target_date": target_date})


# ---------------------------------------------------------------------------
# Convenience re-exports.
#
# Catalog/auth services live in their own modules (catalog_services.py and
# auth_services.py) but were historically imported from here; keep those
# import sites working.
# ---------------------------------------------------------------------------
from frontend.api.auth_services import AuthService  # noqa: E402,F401
from frontend.api.catalog_services import (  # noqa: E402,F401
    AgentService,
    CatalogService,
    RAGService,
)
# Convenience aliases so pages can import PredictionService from either
# module path.
__all__ = [
    "AppointmentService",
    "PaymentService",
    "FeedbackService",
    "AdminRequestService",
    "ReminderService",
    "PredictionService",
    "AuthService",
    "AgentService",
    "CatalogService",
    "RAGService",
]