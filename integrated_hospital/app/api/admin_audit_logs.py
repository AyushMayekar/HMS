"""
Admin audit-log API routes (spec §25.3).
Read-only viewer for the hospital audit trail — admin only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_admin
from app.services.audit_service import list_audit_logs

router = APIRouter(
    prefix="/admin",
    tags=["Admin Audit Logs"],
)


@router.get("/audit-logs", status_code=status.HTTP_200_OK, summary="List audit logs")
def list_audit_logs_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_admin),
):
    """
    List real audit-log entries, newest first (admin only).

    Data: {"logs": [...], "total": int} — built strictly from the
    audit_logs table; no record is invented.
    """
    result = list_audit_logs(limit=limit, offset=offset)
    return {
        "success": True,
        "data": {"logs": result["logs"], "total": result["total"]},
        "total": result["total"],
    }
