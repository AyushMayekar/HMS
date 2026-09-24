"""
Admin Departments page.

Light consistency pass: descriptive CRUD tables/forms with inline validation,
standardized success/error feedback, and Material markdown icons — no emoji.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, status_pill, format_datetime
from frontend.api.staff_admin_services import DepartmentAdminService

STATUS_OPTIONS = {"active": "Active", "inactive": "Inactive"}

CREATE_FLASH_KEY = "dept_create_flash"
EDIT_FLASH_KEY = "dept_edit_flash"
ATTEMPT_KEY = "dept_create_attempted"


def _required_error(value: str, required: bool, label: str, min_len: int = 1) -> str | None:
    v = (value or "").strip()
    if not v:
        return f"{label} is required." if required else None
    if len(v) < min_len:
        return f"{label} must be at least {min_len} characters."
    return None


def _show_flash(key: str) -> None:
    """Persistent success message with an explicit dismiss action."""
    message = st.session_state.get(key)
    if not message:
        return
    st.success(message)
    if st.button("Dismiss", key=f"{key}_dismiss"):
        st.session_state.pop(key, None)
        st.rerun()


def render():
    page_head(
        "Departments",
        "Maintain the clinical departments shown across the patient portal and agent knowledge.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Departments"])

    service = DepartmentAdminService()

    tab_list, tab_create = st.tabs(["Departments", "New Department"])

    # ---------- Create ----------
    with tab_create:
        section_title(
            "Add a Department",
            "New departments appear in the public directory and the booking flow.",
        )

        _show_flash(CREATE_FLASH_KEY)

        # One-shot field reset, applied before the widgets are instantiated.
        if st.session_state.pop("_dept_clear_fields", False):
            for widget_key in ("dept_new_name", "dept_new_desc", "dept_new_info"):
                st.session_state.pop(widget_key, None)

        attempted = bool(st.session_state.get(ATTEMPT_KEY, False))

        name = st.text_input(
            "Department name",
            key="dept_new_name",
            placeholder="e.g. Cardiology",
            help="At least 2 characters.",
        )
        err = _required_error(name, attempted, "Department name", min_len=2)
        if err:
            st.error(err)

        description = st.text_input(
            "Short description",
            key="dept_new_desc",
            placeholder="e.g. Heart and vascular care",
            help="At least 3 characters.",
        )
        err = _required_error(description, attempted, "Short description", min_len=3)
        if err:
            st.error(err)

        information = st.text_area(
            "Information for patients",
            key="dept_new_info",
            placeholder="What patients should know about this department — services, procedures, preparation…",
            height=140,
            help="Used on the public department page and by the AI assistant. At least 10 characters.",
        )
        err = _required_error(information, attempted, "Patient information", min_len=10)
        if err:
            st.error(err)

        status = st.selectbox(
            "Status",
            ["active", "inactive"],
            format_func=lambda s: STATUS_OPTIONS[s],
            key="dept_new_status",
        )

        if st.button("Create Department", type="primary", width="stretch"):
            st.session_state[ATTEMPT_KEY] = True
            if any(
                (
                    _required_error(name, True, "Department name", min_len=2),
                    _required_error(description, True, "Short description", min_len=3),
                    _required_error(information, True, "Patient information", min_len=10),
                )
            ):
                # Rerun so the inline messages next to each field appear immediately.
                st.rerun()

            with st.spinner("Creating department…"):
                result = service.create(
                    name=name.strip(),
                    description=description.strip(),
                    information=information.strip(),
                    status=status,
                )
            if result.success:
                st.session_state[CREATE_FLASH_KEY] = f"Department '{name.strip()}' created successfully."
                st.session_state[ATTEMPT_KEY] = False
                st.session_state["_dept_clear_fields"] = True
                st.rerun()
            else:
                display_api_error(result)

    # ---------- List ----------
    with tab_list:
        section_title("All Departments", "Ordered by name. Edit entries inline below each card.")
        _show_flash(EDIT_FLASH_KEY)

        res = service.list(limit=200)
        if not res.success:
            display_api_error(res)
            st.stop()

        raw = res.data
        if isinstance(raw, list):
            departments = [d for d in raw if isinstance(d, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("departments"), list):
            departments = [d for d in raw["departments"] if isinstance(d, dict)]
        else:
            departments = []

        if not departments:
            empty_state(
                "No departments yet.",
                "Create your first department in the New Department tab."
            )
            return

        for d in departments:
            _render_dept_row(d, service)


def _render_dept_row(d: dict, service: DepartmentAdminService) -> None:
    """Render a department card with inline edit controls."""
    dept_id = d.get("department_id")
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{d.get('name')}**")
            st.caption(d.get("description") or "")
            st.caption(
                f"Updated {format_datetime(d.get('updated_at') or d.get('created_at'))}"
                + (f" · ID: {str(dept_id)[:8]}" if dept_id else "")
            )
        with col2:
            status = d.get("status")
            status_pill(status, custom_label=STATUS_OPTIONS.get(status, str(status).title() if status else "—"))

        if not dept_id:
            return

        with st.expander("Edit department"):
            with st.form(f"edit_dept_{dept_id}"):
                name = st.text_input("Name", value=d.get("name") or "", key=f"dn_{dept_id}")
                description = st.text_input("Description", value=d.get("description") or "", key=f"dd_{dept_id}")
                information = st.text_area(
                    "Patient information",
                    value=d.get("information") or "",
                    key=f"di_{dept_id}",
                    height=100,
                )
                status = st.selectbox(
                    "Status",
                    ["active", "inactive"],
                    index=0 if d.get("status") == "active" else 1,
                    format_func=lambda s: STATUS_OPTIONS[s],
                    key=f"ds_{dept_id}",
                )
                c1, c2 = st.columns(2)
                with c1:
                    save = st.form_submit_button("Save Changes", type="primary", width="stretch")
                with c2:
                    cancel = st.form_submit_button("Cancel", width="stretch")

            if save and not cancel:
                if not (name or "").strip():
                    st.error("Department name cannot be empty.")
                elif not (description or "").strip():
                    st.error("Description cannot be empty.")
                elif not (information or "").strip():
                    st.error("Patient information cannot be empty.")
                else:
                    payload = {}
                    if name.strip() != (d.get("name") or ""):
                        payload["name"] = name.strip()
                    if description.strip() != (d.get("description") or ""):
                        payload["description"] = description.strip()
                    if information.strip() != (d.get("information") or ""):
                        payload["information"] = information.strip()
                    if status != d.get("status"):
                        payload["status"] = status
                    if not payload:
                        st.info("No changes to save.")
                    else:
                        result = service.update(dept_id, **payload)
                        if result.success:
                            st.session_state[EDIT_FLASH_KEY] = (
                                f"Department '{name.strip()}' updated."
                            )
                            st.rerun()
                        else:
                            display_api_error(result)


if __name__ == "__main__":
    render()
