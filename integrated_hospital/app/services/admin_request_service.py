"""
Admin request service.
Handles administrative support requests (refund, appointment_issue, etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import (
    AdminRequestNotFoundError,
    AppointmentNotFoundError,
    ForbiddenError,
    InvalidOperationError,
    PaymentNotFoundError,
)
from app.utils.logger import log_info
from app.utils.validators import ADMIN_REQUEST_CATEGORIES, normalize_admin_category


def _normalize_timestamp(value: Any) -> Any:
    """
    Normalize a stored timestamp to ISO-8601 UTC ("+00:00") for API responses
    (spec §13: displayed and stored request time must be correct/consistent).

    The backend always writes UTC, so naive values are treated as UTC;
    offset-aware values are converted to UTC. Anything unparseable passes
    through unchanged rather than being invented.
    """
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def _normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a request row with normalized created_at/updated_at."""
    normalized = dict(request)
    for field in ("created_at", "updated_at"):
        if field in normalized:
            normalized[field] = _normalize_timestamp(normalized[field])
    return normalized


def create_admin_request(
    *,
    patient_id: str,
    category: str,
    description: str,
    appointment_id: str | None = None,
    payment_id: str | None = None,
    created_via: str = "patient_ui",
) -> dict[str, Any]:
    """
    Create an administrative request.
    Patient-created requests automatically use authenticated identity.
    """
    # Canonical category contract, enforced at the service boundary so that no
    # caller (AI agent, patient REST endpoint, or future code) can persist an
    # unknown category. Known aliases resolve to their canonical value.
    normalized_category = normalize_admin_category(category)
    if normalized_category is None:
        raise InvalidOperationError(
            "Invalid request category. Must be one of: "
            f"{', '.join(ADMIN_REQUEST_CATEGORIES)}."
        )
    category = normalized_category

    admin_supabase = get_supabase_admin_client()

    # Validate appointment if provided
    if appointment_id:
        appt_res = (
            admin_supabase
            .table("appointments")
            .select("appointment_id, patient_id")
            .eq("appointment_id", appointment_id)
            .execute()
        )
        if not appt_res.data:
            raise AppointmentNotFoundError(appointment_id)
        if appt_res.data[0].get("patient_id") != patient_id:
            raise ForbiddenError("The appointment does not belong to you.")

    # Validate payment if provided
    if payment_id:
        pay_res = (
            admin_supabase
            .table("payments")
            .select("payment_id, patient_id")
            .eq("payment_id", payment_id)
            .execute()
        )
        if not pay_res.data:
            raise PaymentNotFoundError(payment_id)
        if pay_res.data[0].get("patient_id") != patient_id:
            raise ForbiddenError("The payment does not belong to you.")

    now = datetime.now(timezone.utc)
    request_id = str(uuid4())

    payload = {
        "request_id": request_id,
        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "payment_id": payment_id,
        "category": category,
        "description": description,
        "priority": "medium",
        "status": "pending",
        "assigned_to": None,
        "resolution": None,
        "created_via": created_via,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("admin_requests").insert(payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to create admin request.")

    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="create_admin_request",
        resource_type="admin_requests",
        resource_id=request_id,
        old_value=None,
        new_value={"category": category, "description": description[:100]},
        status="success",
    )

    log_info("Admin request created", patient_id=patient_id, request_id=request_id, category=category)
    return _normalize_request(insert_res.data[0])


def list_patient_admin_requests(
    *,
    patient_id: str,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List admin requests scoped to the authenticated patient."""
    admin_supabase = get_supabase_admin_client()

    query = (
        admin_supabase
        .table("admin_requests")
        .select("*", count="exact")
        .eq("patient_id", patient_id)
    )

    if status_filter:
        query = query.eq("status", status_filter)

    response = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    return {
        "requests": [_normalize_request(r) for r in (response.data or [])],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_admin_request(
    *,
    patient_id: str,
    request_id: str,
) -> dict[str, Any]:
    """Retrieve a single admin request, enforcing patient ownership."""
    admin_supabase = get_supabase_admin_client()

    res = (
        admin_supabase
        .table("admin_requests")
        .select("*")
        .eq("request_id", request_id)
        .execute()
    )
    if not res.data:
        raise AdminRequestNotFoundError(request_id)

    request = res.data[0]
    if request.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this request.")

    return _normalize_request(request)


def resolve_admin_request(
    *,
    request_id: str,
    status: str,
    resolution: str,
    assigned_to: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Resolve an admin request (staff/admin only)."""
    admin_supabase = get_supabase_admin_client()

    existing = (
        admin_supabase
        .table("admin_requests")
        .select("*")
        .eq("request_id", request_id)
        .execute()
    )
    if not existing.data:
        raise AdminRequestNotFoundError(request_id)

    old_request = existing.data[0]
    now = datetime.now(timezone.utc)

    update_fields = {
        "status": status,
        "resolution": resolution,
        "updated_at": now.isoformat(),
    }
    if assigned_to:
        update_fields["assigned_to"] = assigned_to

    update_res = (
        admin_supabase
        .table("admin_requests")
        .update(update_fields)
        .eq("request_id", request_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="resolve_admin_request",
        resource_type="admin_requests",
        resource_id=request_id,
        old_value={"status": old_request.get("status")},
        new_value={"status": status, "resolution": resolution[:100]},
        status="success",
    )

    log_info("Admin request resolved", request_id=request_id, status=status, actor_id=actor_id)
    return _normalize_request(update_res.data[0] if update_res.data else old_request)


def list_all_admin_requests(
    *,
    status_filter: str | None = None,
    category_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List all admin requests (admin only)."""
    admin_supabase = get_supabase_admin_client()

    query = admin_supabase.table("admin_requests").select("*", count="exact")

    if status_filter:
        query = query.eq("status", status_filter)
    if category_filter:
        query = query.eq("category", category_filter)

    response = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    return {
        "requests": [_normalize_request(r) for r in (response.data or [])],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }
