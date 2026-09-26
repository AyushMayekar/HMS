"""
Business-value recommendation service.

Turns the numbers the analytics/forecasting code already computes into short,
plain-English operational recommendations using the configured LLM.

Design rules (PROJECT CONTEXT - graceful degradation):
- The LLM is optional. When ``llm_api_key`` is not configured (the current
  deployment) the service answers immediately with ``source="unavailable"``
  WITHOUT touching the database or the network, so the endpoint stays fast
  and always returns HTTP 200.
- Every other failure mode (unreachable base URL, denied credential, timeout,
  empty model reply, analytics outage) collapses into the same neutral
  "unavailable" payload. No exception escapes to the HTTP layer, no stack
  trace is returned, and the API key is never logged or echoed back.
- The whole model round-trip is bounded by ``LLM_TIMEOUT_SECONDS``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import httpx
from langchain_openai import ChatOpenAI

from app.config.settings import get_settings
from app.services.analytics_service import (
    get_appointment_analytics,
    get_billing_analytics,
    get_no_show_analytics,
    get_waiting_time_analytics,
)
from app.services.prediction_service import predict_bed_demand, predict_patient_flow
from app.utils.logger import log_info, log_warning

# Single bounded budget for the model round-trip (connect + read).
LLM_TIMEOUT_SECONDS = 25.0

# Output contract for the model.
MAX_BULLETS = 6

# Neutral copy used for every unavailable path - no numbers, no advice.
UNAVAILABLE_MESSAGE = (
    "Recommendations are not available right now. "
    "Every figure shown above comes directly from live hospital data."
)

# Values shipped by .env templates (``your_llm_api_key_here``) are treated as
# "not configured": the endpoint must degrade instantly instead of spending the
# whole LLM budget on a credential that was never filled in.
_PLACEHOLDER_KEY_MARKERS = (
    "your_", "your-", "your ", "changeme", "change_me", "change-me",
    "placeholder", "example", "dummy", "xxxx", "<your", "insert_",
    "replace_", "fixme", "todo_",
)


def _is_configured_key(key: Optional[str]) -> bool:
    """True only for a value that looks like a real credential."""
    value = (key or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("your"):
        return False
    return not any(marker in lowered for marker in _PLACEHOLDER_KEY_MARKERS)


SYSTEM_PROMPT = (
    "You are an operations analyst for a hospital. You receive a JSON snapshot "
    "of live analytics (the analysis window is given) plus next-day forecasts. "
    "Write short, plain-English business recommendations for hospital managers.\n"
    "\n"
    "Rules:\n"
    "- Output exactly 3 to 6 bullet lines and nothing else: no title, no "
    "preamble, no closing sentence.\n"
    "- Every line starts with '- '.\n"
    "- Each bullet is one or two sentences, specific and actionable. Cover only "
    "the angles the data supports: capacity, staffing, no-shows, bed demand, "
    "patient flow, waiting times, and billing/receivables.\n"
    "- Use ONLY numbers that appear in the snapshot. Never invent, estimate or "
    "extrapolate a number, date or department name. If the snapshot has no data "
    "for an angle, skip that angle.\n"
    "- Plain English only: no markdown headings, bold, tables or code fences.\n"
    "- No medical, clinical or patient-specific advice of any kind - this is "
    "operational guidance for managers, not care guidance.\n"
    "- Keep the whole answer under 120 words."
)

_BULLET_MARKER = re.compile(r"^(?:[-*•–—]|\d+[.)])\s+")


# ---------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------
def unavailable_recommendation(reason: str) -> dict[str, Any]:
    """Neutral 200-shaped result used for every degraded path.

    ``reason`` is only ever written to the server log (never returned to the
    caller) and must never contain credentials.
    """
    log_warning("recommendation unavailable", reason=reason)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "message": UNAVAILABLE_MESSAGE,
        "data": {
            "recommendation": UNAVAILABLE_MESSAGE,
            "bullets": [],
            "source": "unavailable",
            "generated_at": generated_at,
        },
    }


# ---------------------------------------------------------------------
# Snapshot compaction (keeps the prompt small and the numbers verbatim)
# ---------------------------------------------------------------------
def _top_counts(mapping: Any, limit: int) -> dict[str, float]:
    """Largest ``count: value`` entries of a flat mapping."""
    if not isinstance(mapping, dict):
        return {}
    items = []
    for key, value in mapping.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            items.append((str(key), float(value)))
    items.sort(key=lambda pair: pair[1], reverse=True)
    return dict(items[:limit])


def _compact_appointments(data: dict) -> dict:
    return {
        "period_days": data.get("period_days"),
        "summary": data.get("summary") or {},
        "payment_summary": data.get("payment_summary") or {},
        "channel_breakdown": data.get("channel_breakdown") or {},
        "department_breakdown": _top_counts(data.get("department_breakdown"), 12),
    }


def _compact_no_show(data: dict) -> dict:
    return {
        "period_days": data.get("period_days"),
        "by_reminder": data.get("by_reminder") or [],
        "by_lead_time": data.get("by_lead_time") or [],
        "by_department": (data.get("by_department") or [])[:8],
    }


def _compact_waiting_time(data: dict) -> dict:
    return {
        "period_days": data.get("period_days"),
        "average_wait_minutes": data.get("average_wait_minutes"),
        "by_department": (data.get("by_department") or [])[:8],
        "by_hour": (data.get("by_hour") or [])[:24],
    }


def _compact_billing(data: dict) -> dict:
    monthly = data.get("monthly_revenue") or []
    return {
        "period_days": data.get("period_days"),
        "receivables_by_status": data.get("receivables_by_status") or [],
        "pending_by_category": data.get("pending_by_category") or [],
        "delay_by_insurance_claim": data.get("delay_by_insurance_claim") or [],
        "monthly_revenue_recent": monthly[-6:],
    }


def _compact_forecast(result: dict, value_key: str) -> dict:
    """Condense a department forecast to a status, a total and the hot spots.

    Returns ``{}`` when the forecast produced no numbers, so the section is
    dropped instead of feeding an empty block to the model.
    """
    predictions = result.get("predictions") or []
    by_department: dict[str, float] = {}
    total = 0.0
    for row in predictions:
        if not isinstance(row, dict):
            continue
        name = str(row.get("department_name") or "unknown")
        try:
            value = float(row.get(value_key) or 0)
        except (TypeError, ValueError):
            continue
        by_department[name] = value
        total += value

    if not by_department:
        return {}

    return {
        "target_date": result.get("target_date"),
        "prediction_status": result.get("prediction_status"),
        "used_stored_average": result.get("prediction_status") == "fallback",
        "total_predicted": round(total, 2),
        "highest_departments": _top_counts(by_department, 8),
        "departments_without_data": len(result.get("insufficient") or []),
    }


# ---------------------------------------------------------------------
# Snapshot gathering - bounded, one call per source, failures skipped
# ---------------------------------------------------------------------
def _gather_snapshot(days: int) -> dict[str, Any]:
    """Collect the analytics/forecast numbers the recommendation is based on.

    Each source is fetched exactly once and guarded on its own: one failing
    source only removes that section, it never fails the request.
    """
    snapshot: dict[str, Any] = {}

    def _add(name: str, builder: Callable[[], Any], compact: Callable[[Any], dict]) -> None:
        try:
            raw = builder()
        except Exception as exc:  # noqa: BLE001 - degrade, never bubble
            log_warning(
                "recommendation: analytics section failed",
                section=name,
                exception_type=type(exc).__name__,
            )
            return
        try:
            value = compact(raw)
        except Exception as exc:  # noqa: BLE001 - degrade, never bubble
            log_warning(
                "recommendation: analytics section compaction failed",
                section=name,
                exception_type=type(exc).__name__,
            )
            return
        if value:
            snapshot[name] = value

    _add("appointments", lambda: get_appointment_analytics(days=days), _compact_appointments)
    _add("no_show", lambda: get_no_show_analytics(days=days), _compact_no_show)
    _add("waiting_time", lambda: get_waiting_time_analytics(days=days), _compact_waiting_time)
    _add("billing", lambda: get_billing_analytics(days=days), _compact_billing)

    try:
        tz = ZoneInfo(get_settings().hospital_timezone)
        target = datetime.now(tz).date() + timedelta(days=1)
    except Exception:  # noqa: BLE001 - timezone config must never break the route
        target = datetime.now(timezone.utc).date() + timedelta(days=1)

    _add(
        "bed_demand_forecast",
        lambda: predict_bed_demand(target),
        lambda result: _compact_forecast(result, "predicted_bed_demand"),
    )
    _add(
        "patient_flow_forecast",
        lambda: predict_patient_flow(target),
        lambda result: _compact_forecast(result, "predicted_patient_flow"),
    )
    return snapshot


# ---------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------
def _extract_text(response: Any) -> str:
    """Flatten a chat completion response into plain text."""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        content = " ".join(parts)
    return str(content or "")


def _parse_bullets(text: str) -> list[str]:
    """Pull up to ``MAX_BULLETS`` bullet lines out of a free-form reply."""
    lines: list[tuple[bool, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        marked = bool(_BULLET_MARKER.match(line))
        cleaned = _BULLET_MARKER.sub("", line).strip() or line
        lines.append((marked, cleaned))

    if not lines:
        return []

    # Prefer the marked lines; if the model ignored the marker convention,
    # fall back to every usable line rather than returning nothing.
    selected = [text for marked, text in lines if marked] or [text for _, text in lines]
    return [text for text in selected if text][:MAX_BULLETS]


def _call_llm(snapshot: dict[str, Any]) -> str:
    """One bounded, non-streaming model round-trip. Raises on any failure."""
    settings = get_settings()
    http_client = httpx.Client(
        verify=False,
        timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=10.0),
    )
    # Same proven construction as app/agent/nodes.py, plus a hard timeout and
    # no automatic retries so one attempt cannot quietly become several.
    llm = ChatOpenAI(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        http_client=http_client,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        prompt = (
            "Analytics snapshot (JSON):\n"
            + json.dumps(snapshot, default=str, separators=(",", ":"))
        )
        response = llm.invoke([("system", SYSTEM_PROMPT), ("human", prompt)])
        return _extract_text(response)
    finally:
        try:
            http_client.close()
        except Exception:  # noqa: BLE001 - closing must never mask the result
            pass


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def generate_business_recommendations(*, days: int = 30) -> dict[str, Any]:
    """Business-value recommendations for the current analytics window.

    Always returns ``{"message": str, "data": {recommendation, bullets,
    source, generated_at}}``. ``data["source"]`` is ``"llm"`` only when the
    model produced usable bullets; otherwise it is ``"unavailable"`` and the
    payload carries neutral copy instead of advice.
    """
    settings = get_settings()

    # Fast path: no usable credential -> neutral 200, no DB, no network.
    # (The shipped .env carries a template placeholder, which counts as
    # "not configured" - see _is_configured_key.)
    if not _is_configured_key(settings.llm_api_key):
        return unavailable_recommendation("llm_api_key_not_configured")

    snapshot = _gather_snapshot(days)
    if not snapshot:
        return unavailable_recommendation("no_analytics_available")

    try:
        raw_reply = _call_llm(snapshot)
    except Exception as exc:  # noqa: BLE001 - unreachable host, denied key, timeout...
        # Only the exception class is logged: provider messages can echo
        # request details and the key must never reach the logs or the client.
        return unavailable_recommendation(f"llm_call_failed:{type(exc).__name__}")

    bullets = _parse_bullets(raw_reply)
    if not bullets:
        return unavailable_recommendation("llm_reply_empty")

    generated_at = datetime.now(timezone.utc).isoformat()
    log_info(
        "recommendations generated",
        days=days,
        bullets=len(bullets),
        model=settings.llm_model,
        reply_chars=len(raw_reply),
    )
    return {
        "message": "Recommendations generated from the latest analytics.",
        "data": {
            "recommendation": "\n".join(f"- {bullet}" for bullet in bullets),
            "bullets": bullets,
            "source": "llm",
            "generated_at": generated_at,
        },
    }
