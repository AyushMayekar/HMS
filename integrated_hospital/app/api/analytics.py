"""
Analytics API routes.
Dashboard analytics for staff/admin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_staff_or_admin
from app.services.analytics_service import (
    get_appointment_analytics,
    get_no_show_risk_queue,
    get_bed_demand_analytics,
    get_department_bed_demand_analytics,
    get_patient_flow_analytics,
    get_department_patient_flow_analytics,
    get_billing_analytics,
    get_satisfaction_analytics,
    get_booking_channel_analytics,
    get_no_show_analytics,
    get_waiting_time_analytics,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/appointments", status_code=status.HTTP_200_OK, summary="Appointment analytics")
def appointment_analytics_endpoint(
    department_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get appointment analytics from current DB data."""
    analytics = get_appointment_analytics(department_id=department_id, days=days)
    return {"success": True, "data": analytics}


@router.get("/no-show-risk", status_code=status.HTTP_200_OK, summary="No-show risk queue")
def no_show_risk_endpoint(
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get upcoming appointments with no-show risk indicators."""
    risk_queue = get_no_show_risk_queue()
    return {"success": True, "data": risk_queue}


# Bed Demand Analytics
@router.get("/bed-demand", status_code=status.HTTP_200_OK, summary="Bed demand analytics")
def bed_demand_endpoint(
    department_id: str | None = Query(default=None),
    view_by: str = Query(default="Month", pattern="^(Day|Week|Month|Year)$"),
    range_index: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get hospital-wide bed demand forecast analytics."""
    analytics = get_bed_demand_analytics(department_id=department_id, view_by=view_by, range_index=range_index)
    return {"success": True, "data": analytics}


@router.get("/bed-demand/department/{department_name}", status_code=status.HTTP_200_OK, summary="Department bed demand")
def department_bed_demand_endpoint(
    department_name: str,
    view_by: str = Query(default="Month", pattern="^(Day|Week|Month|Year)$"),
    range_index: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get bed demand analytics for a specific department."""
    analytics = get_department_bed_demand_analytics(department_name=department_name, view_by=view_by, range_index=range_index)
    return {"success": True, "data": analytics}


# Patient Flow Analytics
@router.get("/patient-flow", status_code=status.HTTP_200_OK, summary="Patient flow analytics")
def patient_flow_endpoint(
    department_id: str | None = Query(default=None),
    view_by: str = Query(default="Month", pattern="^(Day|Week|Month|Year)$"),
    range_index: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get hospital-wide patient flow forecast analytics."""
    analytics = get_patient_flow_analytics(department_id=department_id, view_by=view_by, range_index=range_index)
    return {"success": True, "data": analytics}


@router.get("/patient-flow/department/{department_name}", status_code=status.HTTP_200_OK, summary="Department patient flow")
def department_patient_flow_endpoint(
    department_name: str,
    view_by: str = Query(default="Month", pattern="^(Day|Week|Month|Year)$"),
    range_index: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get patient flow analytics for a specific department."""
    analytics = get_department_patient_flow_analytics(department_name=department_name, view_by=view_by, range_index=range_index)
    return {"success": True, "data": analytics}


# Billing Analytics
@router.get("/billing", status_code=status.HTTP_200_OK, summary="Billing analytics")
def billing_analytics_endpoint(
    department_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get billing/payment analytics."""
    analytics = get_billing_analytics(department_id=department_id, days=days)
    return {"success": True, "data": analytics}


# Satisfaction Analytics
@router.get("/satisfaction", status_code=status.HTTP_200_OK, summary="Patient satisfaction analytics")
def satisfaction_analytics_endpoint(
    department_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get patient satisfaction analytics."""
    analytics = get_satisfaction_analytics(department_id=department_id, days=days)
    return {"success": True, "data": analytics}


# Booking Channel Analytics
@router.get("/booking-channel", status_code=status.HTTP_200_OK, summary="Booking channel analytics")
def booking_channel_endpoint(
    department_id: str | None = Query(default=None),
    view_by: str = Query(default="Month", pattern="^(Day|Week|Month|Year)$"),
    range_index: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get booking channel distribution and trend analytics."""
    analytics = get_booking_channel_analytics(department_id=department_id, view_by=view_by, range_index=range_index)
    return {"success": True, "data": analytics}


# No-Show Analytics (historical analysis)
@router.get("/no-show", status_code=status.HTTP_200_OK, summary="No-show historical analytics")
def no_show_analytics_endpoint(
    department_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get historical no-show analytics (lead time, reminder impact, department comparison)."""
    analytics = get_no_show_analytics(department_id=department_id, days=days)
    return {"success": True, "data": analytics}


# Waiting Time Analytics (historical analysis)
@router.get("/waiting-time", status_code=status.HTTP_200_OK, summary="Waiting time analytics")
def waiting_time_analytics_endpoint(
    department_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Get historical waiting time analytics (by department, hour, distribution)."""
    analytics = get_waiting_time_analytics(department_id=department_id, days=days)
    return {"success": True, "data": analytics}
