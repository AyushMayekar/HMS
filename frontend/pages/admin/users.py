"""
Admin User Management page (§22, §26, §27).

Staff/admin account provisioning — no password field: the backend creates the
auth user and the new user signs in with an 8-digit code emailed to them —
plus searchable account governance with confirmed role/status updates.
"""
from __future__ import annotations

import re

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import pagination
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, status_pill, format_datetime
from frontend.api.staff_admin_services import AdminUserService
from frontend.config import ROLE_PATIENT, ROLE_STAFF, ROLE_ADMIN, ROLE_DOCTOR

ROLE_OPTIONS = {
    ROLE_PATIENT: "Patient",
    ROLE_STAFF: "Staff",
    ROLE_DOCTOR: "Doctor",
    ROLE_ADMIN: "Admin",
}
STATUS_OPTIONS = {
    "active": "Active",
    "inactive": "Inactive",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
PHONE_CHARS_RE = re.compile(r"^[0-9+\-\s]+$")

CREATE_FLASH_KEY = "admin_create_staff_flash"
LIST_FLASH_KEY = "admin_users_flash"
ATTEMPT_KEY = "admin_create_staff_attempted"


# ---------------------------------------------------------------------------
# Inline validation helpers
# ---------------------------------------------------------------------------

def _name_error(value: str, required: bool) -> str | None:
    name = (value or "").strip()
    if not name:
        return "Full name is required." if required else None
    if len(name) < 2:
        return "Full name must be at least 2 characters."
    return None


def _email_error(value: str, required: bool) -> str | None:
    email = (value or "").strip()
    if not email:
        return "Work email is required." if required else None
    if not EMAIL_RE.match(email):
        return "Enter a valid email address, e.g. name@meridiancare.health."
    return None


def _phone_error(value: str) -> str | None:
    phone = (value or "").strip()
    if not phone:
        return None
    if not PHONE_CHARS_RE.match(phone):
        return "Phone may only contain digits, +, - and spaces."
    digits = sum(ch.isdigit() for ch in phone)
    if not 7 <= digits <= 15:
        return "Phone must contain between 7 and 15 digits."
    return None


def _has_create_errors(name: str, email: str, phone: str) -> bool:
    return any(
        (
            _name_error(name, required=True),
            _email_error(email, required=True),
            _phone_error(phone),
        )
    )


def _show_flash(key: str) -> None:
    """Persistent success message with an explicit dismiss action."""
    message = st.session_state.get(key)
    if not message:
        return
    st.success(message)
    if st.button("Dismiss", key=f"{key}_dismiss"):
        st.session_state.pop(key, None)
        st.rerun()


def _change_summary(changes: dict) -> str:
    parts = []
    if "role" in changes:
        parts.append(f"role → {ROLE_OPTIONS.get(changes['role'], changes['role'])}")
    if "status" in changes:
        parts.append(f"status → {STATUS_OPTIONS.get(changes['status'], changes['status'])}")
    return " and ".join(parts)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render():
    page_head(
        "User Management",
        "Govern accounts across the hospital — roles, status, and staff provisioning.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Users"])
    render_content()


def render_content() -> None:
    """Account tabs — also used by the merged Administration › Management page."""
    service = AdminUserService()

    tab_list, tab_create = st.tabs(["All Users", "Create Staff Account"])

    with tab_create:
        _render_create(service)

    with tab_list:
        _render_list(service)


# ---------------------------------------------------------------------------
# Create staff account
# ---------------------------------------------------------------------------

def _render_create(service: AdminUserService) -> None:
    
    section_title(
    "Provision a Hospital Account",
    "Create staff, doctor, or administrator accounts. The new user signs in "
    "with an 8-digit code sent to their email — no password is set here.",
    )

    # Success state (persists until dismissed) with the real returned profile.
    flash = st.session_state.get(CREATE_FLASH_KEY)
    if flash:
        st.success(flash.get("message"))
        profile = flash.get("profile") or {}
        role = profile.get("role")
        status = profile.get("status")
        with st.container(border=True):
            st.write(f"**{profile.get('full_name') or '—'}**")
            st.caption(
                f"{profile.get('email') or '—'} · "
                f"{ROLE_OPTIONS.get(role, str(role).title() if role else '—')} · "
                f"{STATUS_OPTIONS.get(status, str(status).title() if status else '—')}"
            )
            meta = [f"User ID: {profile.get('user_id') or profile.get('id') or '—'}"]
            if profile.get("phone"):
                meta.append(f"Phone: {profile.get('phone')}")
            st.caption(" · ".join(meta))
        if st.button("Dismiss", key="cu_flash_dismiss"):
            st.session_state.pop(CREATE_FLASH_KEY, None)
            st.rerun()

    # One-shot field reset, applied before the widgets are instantiated.
    if st.session_state.pop("_cu_clear_fields", False):
        for widget_key in ("cu_name", "cu_email", "cu_phone"):
            st.session_state.pop(widget_key, None)

    attempted = bool(st.session_state.get(ATTEMPT_KEY, False))

    full_name = st.text_input(
        "Full name",
        key="cu_name",
        placeholder="e.g. S. Raman",
        help="At least 2 characters.",
    )
    err = _name_error(full_name, attempted)
    if err:
        st.error(err)

    email = st.text_input(
        "Work email",
        key="cu_email",
        placeholder="staff@meridiancare.health",
    )
    err = _email_error(email, attempted)
    if err:
        st.error(err)

    phone = st.text_input(
        "Phone (optional)",
        key="cu_phone",
        placeholder="+91 98xxxxxxx0",
        help="7–15 digits; only digits, +, - and spaces.",
    )
    err = _phone_error(phone)
    if err:
        st.error(err)

    role = st.selectbox(
        "Account role",
        [
        ROLE_STAFF,
        ROLE_DOCTOR,
        ROLE_ADMIN,
        ],
        format_func=lambda r: ROLE_OPTIONS[r],
        key="cu_role",
        help=(
        "Staff manage operational workflows such as appointments, reminders, "
        "and analytics. Doctors manage doctor-specific workflows. "
        "Admins additionally govern users, catalog, knowledge, and audit logs."
    ),
    )

    if st.button("Create Account", type="primary", width="stretch"):
        st.session_state[ATTEMPT_KEY] = True
        if _has_create_errors(full_name, email, phone):
            # Rerun so the inline messages next to each field appear immediately.
            st.rerun()

        with st.spinner("Creating account…"):
            kwargs = {
                "full_name": full_name.strip(),
                "email": email.strip().lower(),
                "role": role,
            }
            if phone.strip():
                kwargs["phone"] = phone.strip()
            result = service.create_staff(**kwargs)

        if result.success:
            data = result.data if isinstance(result.data, dict) else {}
            profile = data.get("user") if isinstance(data.get("user"), dict) else data
            display_name = profile.get("full_name") or full_name.strip()
            display_email = profile.get("email") or email.strip().lower()
            st.session_state[CREATE_FLASH_KEY] = {
                "message": (
                    f"Account created for {display_name} ({display_email}). "
                    "They can now sign in with the 8-digit code sent to their email "
                    "— no password is required."
                ),
                "profile": profile,
            }
            st.session_state[ATTEMPT_KEY] = False
            st.session_state["_cu_clear_fields"] = True
            st.rerun()
        else:
            display_api_error(result)


# ---------------------------------------------------------------------------
# Account list
# ---------------------------------------------------------------------------

def _render_list(service: AdminUserService) -> None:
    section_title(
        "Accounts",
        "Search, filter, and manage every registered account — change roles and "
        "status with a confirmation step.",
    )

    _show_flash(LIST_FLASH_KEY)

    f1, f2, f3 = st.columns([1, 1, 2])
    with f1:
        role_filter = st.selectbox(
    "Role",
    [
        "All",
        ROLE_PATIENT,
        ROLE_STAFF,
        ROLE_DOCTOR,
        ROLE_ADMIN,
    ],
            format_func=lambda r: "All roles" if r == "All" else ROLE_OPTIONS.get(r, r),
            key="admin_users_role",
        )
    with f2:
        status_filter = st.selectbox(
            "Status",
            ["All", "active", "inactive"],
            format_func=lambda s: "All statuses" if s == "All" else STATUS_OPTIONS[s],
            key="admin_users_status",
        )
    with f3:
        search = st.text_input(
            "Search accounts",
            key="um_search",
            placeholder="Name, email, phone or user ID",
        )

    params = {}
    if role_filter != "All":
        params["role"] = role_filter
    if status_filter != "All":
        params["status"] = status_filter

    res = service.list(limit=200, **params)
    if not res.success:
        display_api_error(res)
        st.stop()

    raw = res.data
    if isinstance(raw, list):
        users = [u for u in raw if isinstance(u, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("users"), list):
        users = [u for u in raw["users"] if isinstance(u, dict)]
    else:
        users = []
    total = len(users)

    query = (search or "").strip().lower()
    if query:
        users = [
            u for u in users
            if any(
                query in str(u.get(field) or "").lower()
                for field in ("full_name", "email", "phone", "user_id")
            )
        ]

    if not users:
        if query or role_filter != "All" or status_filter != "All":
            empty_state(
                "No accounts match the current search or filters.",
                "Clear the search box or choose different filters."
            )
        else:
            empty_state(
                "No accounts registered yet.",
                "Provision the first account in the Create Staff Account tab."
            )
        return

    st.caption(f"Showing {len(users)} of {total} account(s).")
    offset, page_limit = pagination(len(users), 8, "admin_users_page")
    for u in users[offset:offset + page_limit]:
        _render_user_row(u, service)


def _render_user_row(u: dict, service: AdminUserService) -> None:
    """Render a single user with role/status pills and confirmed governance controls."""
    user_id = u.get("user_id") or u.get("id")
    name = u.get("full_name") or "Unnamed account"
    role = u.get("role")
    status = u.get("status")

    with st.container(border=True):
        col1, col2, col3 = st.columns([3.4, 1, 1])
        with col1:
            st.write(f"**{name}**")
            st.caption(u.get("email") or "—")
            st.caption(
                f"Phone: {u.get('phone') or '—'} · "
                f"Registered {format_datetime(u.get('registered_at') or u.get('created_at'))} · "
                f"ID: {user_id or '—'}"
            )
        with col2:
            status_pill(role, custom_label=ROLE_OPTIONS.get(role, str(role).title() if role else "—"))
        with col3:
            status_pill(status, custom_label=STATUS_OPTIONS.get(status, str(status).title() if status else "—"))

        if not user_id:
            return

        pending_key = f"um_pending_{user_id}"
        with st.expander("Change role / status"):
            r1, r2 = st.columns(2)
            with r1:
                new_role = st.selectbox(
                    "Role",
                    list(ROLE_OPTIONS.keys()),
                    index=list(ROLE_OPTIONS.keys()).index(role) if role in ROLE_OPTIONS else 0,
                    format_func=lambda r: ROLE_OPTIONS[r],
                    key=f"um_role_{user_id}",
                )
            with r2:
                new_status = st.selectbox(
                    "Status",
                    list(STATUS_OPTIONS.keys()),
                    index=list(STATUS_OPTIONS.keys()).index(status) if status in STATUS_OPTIONS else 0,
                    format_func=lambda s: STATUS_OPTIONS[s],
                    key=f"um_status_{user_id}",
                )

            changes = {}
            if new_role != role:
                changes["role"] = new_role
            if new_status != status:
                changes["status"] = new_status

            pending = st.session_state.get(pending_key)
            if pending:
                st.warning(f"Confirm change for {name}: {_change_summary(pending)}.")
                y1, y2 = st.columns([1.6, 1])
                with y1:
                    if st.button(
                        "Confirm change",
                        key=f"{pending_key}_yes",
                        type="primary",
                        width="stretch",
                    ):
                        result = service.update(user_id, **pending)
                        if result.success:
                            st.session_state[LIST_FLASH_KEY] = (
                                f"Updated {name} — {_change_summary(pending)}."
                            )
                            st.session_state.pop(pending_key, None)
                            st.rerun()
                        else:
                            display_api_error(result)
                with y2:
                    if st.button("Cancel", key=f"{pending_key}_no", width="stretch"):
                        st.session_state.pop(pending_key, None)
                        st.rerun()
            elif changes:
                if st.button(
                    "Review change",
                    key=f"{pending_key}_review",
                    width="stretch",
                ):
                    st.session_state[pending_key] = changes
                    st.rerun()
            else:
                st.caption("No changes selected.")


if __name__ == "__main__":
    render()
