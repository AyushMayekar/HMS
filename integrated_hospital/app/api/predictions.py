"""
Predictions API routes.
ML prediction endpoints for no-show, waiting-time (check-in and booking),
and the department-level bed-demand / patient-flow forecasts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator

from app.config.settings import get_settings
from app.dependencies.auth import AuthContext, get_current_profile, require_staff_or_admin
from app.services.prediction_service import (
    list_no_show_eligible,
    predict_bed_demand,
    predict_booking_waiting_preview,
    predict_booking_waiting_time,
    predict_no_show,
    predict_patient_flow,
    predict_waiting_time,
    run_no_show_for_ids,
)

router = APIRouter(
    prefix="/predictions",
    tags=["ML Predictions"],
)


class ForecastRequest(BaseModel):
    """Forecast request body. target_date defaults to tomorrow in the
    configured hospital timezone (Param_v4 contract: explicit target_date)."""
    target_date: Optional[date] = None


class BookingWaitingPreviewRequest(BaseModel):
    """Booking-time waiting preview for a slot BEFORE the appointment exists."""
    doctor_id: str
    scheduled_start: str
    availability_id: Optional[str] = None

    @field_validator("scheduled_start")
    @classmethod
    def validate_scheduled_start(cls, value: str) -> str:
        from datetime import datetime as _datetime
        try:
            _datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("scheduled_start must be an ISO-8601 datetime") from exc
        return value


def _resolve_target_date(target_date: Optional[date]) -> date:
    if target_date is not None:
        return target_date
    tz = ZoneInfo(get_settings().hospital_timezone)
    return datetime.now(tz).date() + timedelta(days=1)


class NoShowBatchRequest(BaseModel):
    """Explicit selection for the 'Predict Selected' action (max = settings.noshow_max_batch)."""
    appointment_ids: list[str]

    @field_validator("appointment_ids")
    @classmethod
    def clean_ids(cls, value: list[str]) -> list[str]:
        cleaned = [str(v).strip() for v in (value or []) if str(v).strip()]
        if not cleaned:
            raise ValueError("appointment_ids must contain at least one appointment id")
        return cleaned


# NOTE: these two static routes MUST be declared before
# POST /no-show/{appointment_id} — otherwise FastAPI would match
# "no-show-eligible" / "no-show-batch" as an appointment_id path parameter.
@router.get("/no-show-eligible", status_code=status.HTTP_200_OK,
            summary="List appointments eligible for 24h no-show prediction")
def no_show_eligible_endpoint(
    tolerance_minutes: Optional[int] = Query(default=None, ge=0, le=1440),
    limit: int = Query(default=100, ge=1, le=200),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """
    Appointments scheduled at ``now + 24h`` within the configured tolerance
    (default ±12 hours), still ``booked``.

    Read-only: opening the prediction page never runs inference.
    """
    return {"success": True, "data": list_no_show_eligible(tolerance_minutes, limit=limit)}


@router.post("/no-show-batch", status_code=status.HTTP_200_OK,
             summary="Run no-show prediction for a selected batch (max 10)")
def predict_no_show_batch_endpoint(
    body: NoShowBatchRequest,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """
    Run the EXISTING no-show inference for the explicitly selected
    appointments only. Enforces the maximum batch size server-side
    (422 ``INVALID_OPERATION`` when more are selected) and re-checks that
    every id is still eligible. There is deliberately no "predict all".
    """
    return {"success": True, "data": run_no_show_for_ids(body.appointment_ids)}


# NOTE: this static route MUST be declared before
# POST /waiting-time/{appointment_id}, otherwise FastAPI would match
# "booking-preview" as an appointment_id path parameter.
@router.post("/waiting-time/booking-preview", status_code=status.HTTP_200_OK,
             summary="Predict waiting time for a booking slot")
def booking_waiting_time_preview_endpoint(
    body: BookingWaitingPreviewRequest,
    auth: AuthContext = Depends(get_current_profile),
):
    """
    Approximate waiting time for a slot during booking (pre-check-in, no
    appointment row yet). Any authenticated user (patient/staff/admin).

    Data: {"predicted_waiting_min": float, "label": str, "basis": str} —
    computed from real historical waiting-time data; when there is no
    history yet the value is 0.0 and the basis says "insufficient history".
    """
    result = predict_booking_waiting_preview(
        doctor_id=body.doctor_id,
        scheduled_start=body.scheduled_start,
        availability_id=body.availability_id,
    )
    return {"success": True, "data": result}


@router.post("/no-show/{appointment_id}", status_code=status.HTTP_200_OK, summary="Predict no-show")
def predict_no_show_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Run no-show prediction for an eligible appointment."""
    result = predict_no_show(appointment_id)
    return {"success": True, "data": result}


@router.post("/waiting-time/{appointment_id}", status_code=status.HTTP_200_OK, summary="Predict waiting time")
def predict_waiting_time_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Run waiting-time prediction at check-in."""
    result = predict_waiting_time(appointment_id)
    return {"success": True, "data": result}


@router.post("/waiting-time/booking/{appointment_id}", status_code=status.HTTP_200_OK,
             summary="Predict waiting time at booking")
def predict_booking_waiting_time_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """
    Booking-time waiting-time prediction (pre-check-in).

    Uses the booking_waiting_model artifact: check-in queue features are NOT
    required; trailing operational features come from row snapshot or real DB
    history.
    """
    result = predict_booking_waiting_time(appointment_id)
    return {"success": True, "data": result}


@router.post("/bed-demand", status_code=status.HTTP_200_OK, summary="Forecast bed demand")
def predict_bed_demand_endpoint(
    body: Optional[ForecastRequest] = None,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Department-level next-day bed-demand forecast (Param_v4 contract)."""
    target = _resolve_target_date(body.target_date if body else None)
    result = predict_bed_demand(target)
    return {"success": True, "data": result}


@router.post("/patient-flow", status_code=status.HTTP_200_OK, summary="Forecast patient flow")
def predict_patient_flow_endpoint(
    body: Optional[ForecastRequest] = None,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Department-level next-day patient-flow forecast (Param_v4 contract)."""
    target = _resolve_target_date(body.target_date if body else None)
    result = predict_patient_flow(target)
    return {"success": True, "data": result}
