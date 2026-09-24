"""
Patient admin requests API routes.
Create and view administrative support requests.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_patient
from app.services.admin_request_service import (
    create_admin_request,
    get_admin_request,
    list_patient_admin_requests,
)

router = APIRouter(
    prefix="/patient/admin-requests",
    tags=["Patient Admin Requests"],
)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create admin request")
def create_request_endpoint(
    category: str,
    description: str,
    appointment_id: str | None = None,
    payment_id: str | None = None,
    patient: AuthContext = Depends(require_patient),
):
    """Create an administrative support request."""
    request = create_admin_request(
        patient_id=patient.user.id,
        category=category,
        description=description,
        appointment_id=appointment_id,
        payment_id=payment_id,
        created_via="patient_ui",
    )
    return {"success": True, "message": "Request created successfully.", "data": request}


@router.get("", status_code=status.HTTP_200_OK, summary="List own requests")
def list_requests_endpoint(
    status_filter: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient: AuthContext = Depends(require_patient),
):
    """List all admin requests belonging to the authenticated patient."""
    result = list_patient_admin_requests(
        patient_id=patient.user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": result["requests"], "total": result["total"]}


@router.get("/{request_id}", status_code=status.HTTP_200_OK, summary="View request details")
def get_request_endpoint(
    request_id: str,
    patient: AuthContext = Depends(require_patient),
):
    """Retrieve a single admin request."""
    request = get_admin_request(patient_id=patient.user.id, request_id=request_id)
    return {"success": True, "data": request}
