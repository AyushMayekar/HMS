"""
Catalog API routes.
Departments and doctors are public reference data (no auth required);
availability stays authenticated because it exposes live booking state.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from datetime import date, timedelta
from app.dependencies.auth import AuthContext, get_current_profile
from app.services.department_service import list_departments
from app.services.doctor_service import list_doctors
from app.services.availability_service import list_availability

router = APIRouter(
    prefix="/catalog",
    tags=["Catalog"],
)


@router.get("/departments", status_code=status.HTTP_200_OK)
def list_catalog_departments():
    """List active departments (public — non-sensitive reference data)."""
    result = list_departments(status="active")
    return {"success": True, "data": result["departments"]}


@router.get("/doctors", status_code=status.HTTP_200_OK)
def list_catalog_doctors(
    department_id: str | None = Query(default=None),
):
    """List active doctors (public — non-sensitive reference data)."""
    result = list_doctors(department_id=department_id, status="active")
    return {"success": True, "data": result["doctors"]}


from datetime import date, timedelta

@router.get("/availability")
def list_catalog_availability(
    department_id: str | None = Query(default=None),
    doctor_id: str | None = Query(default=None),
    slot_date: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_profile),
):
    today = date.today()
    window_end = today + timedelta(days=29)

    result = list_availability(
        department_id=department_id,
        doctor_id=doctor_id,
        slot_date=slot_date,
        status="available",
        start_date=today.isoformat(),
        end_date=window_end.isoformat(),
        limit=50,
        offset=0,
    )

    return {
        "success": True,
        "data": result["availability"],
    }