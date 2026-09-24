"""
Doctors API routes.
CRUD operations for doctor records.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, get_current_profile, require_admin
from app.schema.admin import CreateDoctorRequest, UpdateDoctorRequest
from app.services.doctor_service import (
    create_doctor,
    get_doctor,
    list_doctors,
    update_doctor,
)

router = APIRouter(
    prefix="/doctors",
    tags=["Doctors"],
)


@router.get("", status_code=status.HTTP_200_OK, summary="List doctors")
def list_doctors_endpoint(
    department_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_profile),
):
    """List doctors with optional filters. Readable by all authenticated users."""
    result = list_doctors(department_id=department_id, status=status_filter, limit=limit, offset=offset)
    return {"success": True, "data": result["doctors"], "total": result["total"]}


@router.get("/{doctor_id}", status_code=status.HTTP_200_OK, summary="Get doctor")
def get_doctor_endpoint(
    doctor_id: str,
    auth: AuthContext = Depends(get_current_profile),
):
    """Get a single doctor by ID."""
    doctor = get_doctor(doctor_id)
    return {"success": True, "data": doctor}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create doctor")
def create_doctor_endpoint(
    payload: CreateDoctorRequest,
    auth: AuthContext = Depends(require_admin),
):
    """Create a new doctor record (admin only)."""
    doctor = create_doctor(
        department_id=payload.department_id,
        full_name=payload.full_name,
        specialization=payload.specialization,
        experience_years=payload.experience_years,
        status=payload.status,
        actor_id=auth.user.id,
        actor_role="admin",
    )
    return {"success": True, "message": "Doctor created.", "data": doctor}


@router.patch("/{doctor_id}", status_code=status.HTTP_200_OK, summary="Update doctor")
def update_doctor_endpoint(
    doctor_id: str,
    payload: UpdateDoctorRequest,
    auth: AuthContext = Depends(require_admin),
):
    """Update a doctor record (admin only)."""
    doctor = update_doctor(
        doctor_id=doctor_id,
        department_id=payload.department_id,
        full_name=payload.full_name,
        specialization=payload.specialization,
        experience_years=payload.experience_years,
        status=payload.status,
        actor_id=auth.user.id,
        actor_role="admin",
    )
    return {"success": True, "message": "Doctor updated.", "data": doctor}
