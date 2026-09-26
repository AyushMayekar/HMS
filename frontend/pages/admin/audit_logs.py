"""
Admin Audit Logs page (§25.3).

Read-only viewer for the hospital audit trail exposed by
``GET /admin/audit-logs`` via ``AuditLogService().list(limit, offset)``.
Entries are loaded newest-first in batches; filters are applied client-side to
the loaded entries and the filtered result is then paginated, so every row is
a collapsible bar with a details drawer. No record is ever invented — an empty
backend shows an honest empty state.
"""
from __future__ import annotations

import html
import json

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import expandable_row, loading, page_slice
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime
from frontend.api.staff_admin_services import AuditLogService

PAGE_SIZE = 25          # batch fetched from the API per Load more
AUDIT_PAGE_SIZE = 12    # rows shown per page in the viewer

BUFFER_KEY = "admin_audit_buffer"
TOTAL_KEY = "admin_audit_total"
ERROR_KEY = "admin_audit_error"


# ---------------------------------------------------------------------------
# Data loading (offset-based "load more")
# ---------------------------------------------------------------------------

def _load(service: AuditLogService, offset: int, replace: bool) -> None:
    res = service.list(limit=PAGE_SIZE, offset=offset)
    if not res.success:
        st.session_state[ERROR_KEY] = res
        if replace:
            st.session_state[BUFFER_KEY] = []
            st.session_state[TOTAL_KEY] = None
        return

    st.session_state.pop(ERROR_KEY, None)

    if isinstance(res.data, list):
        logs = [x for x in res.data if isinstance(x, dict)]
        total = None
    else:
        data = res.data if isinstance(res.data, dict) else {}
        raw_logs = data.get("logs")
        logs = [x for x in raw_logs if isinstance(x, dict)] if isinstance(raw_logs, list) else []
        total = data.get("total") if isinstance(data.get("total"), int) else None

    if replace:
        st.session_state[BUFFER_KEY] = logs
    else:
        existing = st.session_state.get(BUFFER_KEY) or []
        if not logs:
            total = len(existing)  # reached the end of the trail
        st.session_state[BUFFER_KEY] = existing + logs

    st.session_state[TOTAL_KEY] = total


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _actor_label(log: dict) -> str:
    """Email if present, else actor id, else an honest dash."""
    return str(log.get("actor_email") or log.get("actor_id") or "—")


def _details_text(details) -> str:
    if details is None or details == "":
        return "—"
    if isinstance(details, str):
        return details
    try:
        return json.dumps(details, ensure_ascii=False, default=str, indent=2)
    except Exception:
        return str(details)


_STATUS_BADGES = {
    "success": ("mc-pill-success", "Success"),
    "failure": ("mc-pill-danger", "Failed"),
    "failed": ("mc-pill-danger", "Failed"),
    "error": ("mc-pill-danger", "Error"),
}


def _status_badge(status) -> str | None:
    """Outcome badge for the collapsed bar (never raw technical text)."""
    if not status:
        return None
    key = str(status).strip().lower()
    css_class, label = _STATUS_BADGES.get(
        key, ("mc-pill-neutral", str(status).replace("_", " ").strip().title())
    )
    return f'<span class="mc-pill {css_class}">{html.escape(label)}</span>'


def _log_row_id(log: dict, index: int) -> str:
    """Stable, unique id for a row's expand state (audit_id is a UUID)."""
    return str(log.get("audit_id") or f"audit-entry-{index}")


def _render_details(log: dict) -> None:
    """Detail drawer shown inside the expanded row."""
    details = log.get("details")
    if details in (None, "", {}):
        st.caption("No extra details were recorded with this entry.")
        return
    with st.expander("Details"):
        if isinstance(details, dict):
            st.json(details)
        else:
            st.text(_details_text(details))


def _render_log_row(row_id: str, log: dict) -> None:
    action = str(log.get("action") or "—")
    entity_type = str(log.get("entity_type") or "—")
    entity_id = log.get("entity_id")
    created_at = log.get("created_at") or log.get("timestamp")

    # Collapsed bar: action + time, actor and entity on consistent meta lines,
    # outcome badge on the right — identical structure for every row.
    expandable_row(
        row_id,
        title=action,
        meta=format_datetime(created_at),
        meta_lines=[
            f"Actor: {_actor_label(log)}",
            f"Entity: {entity_type} · {str(entity_id) if entity_id else '—'}",
        ],
        badge_html=_status_badge(log.get("status")),
        actions=lambda: _render_details(log),
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render():
    page_head(
        "Audit Logs",
        "Every privileged action recorded by the hospital platform: who did what, and when.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Audit Logs"])

    service = AuditLogService()

    # First load (subsequent loads happen via Refresh / Load more).
    if BUFFER_KEY not in st.session_state:
        with loading("Loading the audit trail"):
            _load(service, offset=0, replace=True)

    load_error = st.session_state.get(ERROR_KEY)
    if load_error is not None:
        display_api_error(load_error)

    section_title(
        "Audit Trail",
        f"Entries arrive newest-first in batches of {PAGE_SIZE}; use Load more for "
        "older ones. The action and entity filters, and the paging below, apply to "
        "the entries already loaded.",
    )

    logs = st.session_state.get(BUFFER_KEY) or []
    total = st.session_state.get(TOTAL_KEY)

    # ---------- Controls ----------
    if isinstance(total, int):
        has_more = bool(logs) and len(logs) < total
    else:
        # Total unknown: assume more entries while full pages keep arriving.
        has_more = bool(logs) and len(logs) % PAGE_SIZE == 0

    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("Refresh", width="stretch", help="Discard the loaded entries and fetch the latest ones."):
            for key in (BUFFER_KEY, TOTAL_KEY, ERROR_KEY):
                st.session_state.pop(key, None)
            st.rerun()
    with b2:
        if st.button(
            "Load more",
            width="stretch",
            disabled=not has_more or load_error is not None,
            help=f"Load the next {PAGE_SIZE} entries.",
        ):
            with loading("Loading older entries"):
                _load(service, offset=len(logs), replace=False)
            st.rerun()
    with b3:
        if isinstance(total, int):
            st.caption(f"Loaded {len(logs)} of {total} audit entries.")
        else:
            st.caption(f"Loaded {len(logs)} audit entries.")

    # ---------- Client-side filters ----------
    actions = sorted({str(entry.get("action") or "—") for entry in logs})
    entities = sorted({str(entry.get("entity_type") or "—") for entry in logs})
    f1, f2, f3 = st.columns([1.2, 1.2, 2])
    with f1:
        action_filter = st.selectbox("Action", ["All"] + actions, key="al_action_filter")
    with f2:
        entity_filter = st.selectbox("Entity type", ["All"] + entities, key="al_entity_filter")

    filtered = logs
    if action_filter != "All":
        filtered = [e for e in filtered if str(e.get("action") or "—") == action_filter]
    if entity_filter != "All":
        filtered = [e for e in filtered if str(e.get("entity_type") or "—") == entity_filter]

    with f3:
        if action_filter != "All" or entity_filter != "All":
            st.caption(f"Showing {len(filtered)} of {len(logs)} loaded entries after filters.")

    # ---------- Paged list / empty states ----------
    if not logs:
        if load_error is None:
            empty_state(
                "No audit logs recorded yet.",
                "Privileged actions (account changes, catalog edits, knowledge updates)"
                " will appear here as they happen."
            )
        return

    if not filtered:
        empty_state(
            "No entries match the current filters.",
            "Choose a different action or entity type."
        )
        return

    # Paginate AFTER filtering so counts and page maths match what is shown;
    # the page key includes the active filters so a filter change never lands
    # on a stale page of the previous result set.
    entries = [(_log_row_id(log, i), log) for i, log in enumerate(filtered)]
    page_key = f"al_page::{action_filter}::{entity_filter}"
    page_rows, _offset, _limit = page_slice(
        entries, len(entries), AUDIT_PAGE_SIZE, page_key
    )
    for row_id, log in page_rows:
        _render_log_row(row_id, log)


if __name__ == "__main__":
    render()
