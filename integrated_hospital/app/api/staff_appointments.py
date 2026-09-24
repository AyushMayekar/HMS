"""
Staff appointments API routes.
Operational appointment management for staff/admin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_staff_or_admin
from app.services.staff_appointment_service import (
    check_in_appointment,
    end_service,
    get_appointment,
    list_all_appointments,
    mark_no_show,
    start_service,
)

router = APIRouter(
    prefix="/staff/appointments",
    tags=["Staff Appointments"],
)


@router.get("", status_code=status.HTTP_200_OK, summary="List all appointments")
def list_appointments_endpoint(
    appointment_status: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """List all appointments (staff/admin operational scope)."""
    result = list_all_appointments(
        appointment_status=appointment_status,
        department_id=department_id,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": result["appointments"], "total": result["total"]}


@router.get("/{appointment_id}", status_code=status.HTTP_200_OK, summary="Get appointment")
def get_appointment_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get a single appointment (staff/admin scope)."""
    appointment = get_appointment(appointment_id)
    return {"success": True, "data": appointment}


@router.post("/{appointment_id}/check-in", status_code=status.HTTP_200_OK, summary="Check in patient")
def check_in_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Check in a patient. Records check-in time and calculates queue state."""
    result = check_in_appointment(
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "staff"),
    )
    return {"success": True, "message": "Patient checked in.", "data": result}


@router.post("/{appointment_id}/service-start", status_code=status.HTTP_200_OK, summary="Start service")
def start_service_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Record service start time."""
    result = start_service(
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "staff"),
    )
    return {"success": True, "message": "Service started.", "data": result}


@router.post("/{appointment_id}/service-end", status_code=status.HTTP_200_OK, summary="End service")
def end_service_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Record service end time and calculate actual wait."""
    result = end_service(
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "staff"),
    )
    return {"success": True, "message": "Service ended.", "data": result}


@router.post("/{appointment_id}/no-show", status_code=status.HTTP_200_OK, summary="Mark no-show")
def mark_no_show_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Mark an appointment as no-show."""
    result = mark_no_show(
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "staff"),
    )
    return {"success": True, "message": "Appointment marked as no-show.", "data": result}
