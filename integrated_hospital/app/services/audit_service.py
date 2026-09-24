"""
Audit logging service.
Records privileged/mutational operations to audit_logs table.
Audit records are append-only and should not be modifiable by patients.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.utils.logger import log_error, log_info


def log_audit_event(
    *,
    user_id: str,
    user_role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    status: str = "success",
) -> None:
    """Record an administrative or privileged event in the audit_logs table."""
    admin_supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    audit_data = {
        "audit_id": str(uuid4()),
        "user_id": user_id,
        "user_role": user_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "old_value": old_value,
        "new_value": new_value,
        "status": status,
        "timestamp": now.isoformat(),
    }

    try:
        admin_supabase.table("audit_logs").insert(audit_data).execute()
        log_info(
            "Audit log recorded",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
        )
    except Exception as exc:
        log_error(
            "Failed to write audit log",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            exception_type=type(exc).__name__,
        )


def list_audit_logs(
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    List audit-log entries, newest first (spec §25.3, admin only).

    Returns the REAL audit_logs rows, mapped to the display field names the
    admin viewer expects (entity_type/entity_id/created_at/actor_email); no
    record is ever invented — an empty table yields an empty list.
    """
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("audit_logs")
        .select("*", count="exact")
        .order("timestamp", desc=True)
        .order("audit_id", desc=True)  # tiebreaker -> stable, disjoint pages
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = response.data or []

    # Resolve actor ids to profile email/name in one query (best-effort).
    actor_ids = {r.get("user_id") for r in rows if r.get("user_id")}
    actors_by_id: dict[str, dict[str, Any]] = {}
    if actor_ids:
        try:
            res = (
                admin_supabase
                .table("profiles")
                .select("user_id, email, full_name")
                .in_("user_id", list(actor_ids))
                .execute()
            )
            actors_by_id = {p.get("user_id"): p for p in (res.data or [])}
        except Exception as exc:
            log_error("Failed to resolve audit actors", exception_type=type(exc).__name__)

    logs: list[dict[str, Any]] = []
    for row in rows:
        actor = actors_by_id.get(row.get("user_id")) or {}
        old_value = row.get("old_value")
        new_value = row.get("new_value")
        details: dict[str, Any] = {}
        if old_value is not None:
            details["old_value"] = old_value
        if new_value is not None:
            details["new_value"] = new_value

        logs.append({
            "audit_id": row.get("audit_id"),
            "created_at": row.get("timestamp"),
            "timestamp": row.get("timestamp"),
            "action": row.get("action"),
            "entity_type": row.get("resource_type"),
            "entity_id": row.get("resource_id"),
            "actor_id": row.get("user_id"),
            "actor_email": actor.get("email"),
            "actor_name": actor.get("full_name"),
            "actor_role": row.get("user_role"),
            "status": row.get("status"),
            "details": details or None,
        })

    return {
        "logs": logs,
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }
