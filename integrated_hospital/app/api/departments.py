"""
Departments API routes.
CRUD operations for hospital departments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, get_current_profile, require_admin
from app.schema.admin import CreateDepartmentRequest, UpdateDepartmentRequest
from app.services.department_service import (
    create_department,
    get_department,
    list_departments,
    update_department,
)

router = APIRouter(
    prefix="/departments",
    tags=["Departments"],
)


@router.get("", status_code=status.HTTP_200_OK, summary="List departments")
def list_departments_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_profile),
):
    """List departments. Readable by all authenticated users."""
    result = list_departments(status=status_filter, limit=limit, offset=offset)
    return {"success": True, "data": result["departments"], "total": result["total"]}


@router.get("/{department_id}", status_code=status.HTTP_200_OK, summary="Get department")
def get_department_endpoint(
    department_id: str,
    auth: AuthContext = Depends(get_current_profile),
):
    """Get a single department by ID."""
    department = get_department(department_id)
    return {"success": True, "data": department}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create department")
def create_department_endpoint(
    payload: CreateDepartmentRequest,
    auth: AuthContext = Depends(require_admin),
):
    """Create a new department (admin only)."""
    department = create_department(
        name=payload.name,
        description=payload.description,
        information=payload.information,
        status=payload.status,
        actor_id=auth.user.id,
        actor_role="admin",
    )
    return {"success": True, "message": "Department created.", "data": department}


@router.patch("/{department_id}", status_code=status.HTTP_200_OK, summary="Update department")
def update_department_endpoint(
    department_id: str,
    payload: UpdateDepartmentRequest,
    auth: AuthContext = Depends(require_admin),
):
    """Update a department (admin only)."""
    department = update_department(
        department_id=department_id,
        name=payload.name,
        description=payload.description,
        information=payload.information,
        status=payload.status,
        actor_id=auth.user.id,
        actor_role="admin",
    )
    return {"success": True, "message": "Department updated.", "data": department}
