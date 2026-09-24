"""
Admin Doctors page.

Light consistency pass: descriptive CRUD tables/forms with inline validation,
standardized success/error feedback, and Material markdown icons — no emoji.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, status_pill, format_datetime
from frontend.api.staff_admin_services import DoctorAdminService, DepartmentAdminService

STATUS_OPTIONS = {"active": "Active", "inactive": "Inactive"}

CREATE_FLASH_KEY = "doctor_create_flash"
EDIT_FLASH_KEY = "doctor_edit_flash"
ATTEMPT_KEY = "doctor_create_attempted"


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
        "Doctors",
        "Manage clinician records — the team that patients book appointments with.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Doctors"])

    doctor_service = DoctorAdminService()
    dept_res = DepartmentAdminService().list(limit=200)
    if dept_res.success:
        raw_depts = dept_res.data
        if isinstance(raw_depts, list):
            departments = [d for d in raw_depts if isinstance(d, dict)]
        elif isinstance(raw_depts, dict) and isinstance(raw_depts.get("departments"), list):
            departments = [d for d in raw_depts["departments"] if isinstance(d, dict)]
        else:
            departments = []
    else:
        display_api_error(dept_res)
        departments = []
    dept_lookup = {d.get("department_id"): d.get("name", "Unknown") for d in departments}

    tab_list, tab_create = st.tabs(["Doctors", "New Doctor"])

    # ---------- Create ----------
    with tab_create:
        section_title(
            "Add a Doctor",
            "Assign the doctor to a department and record their specialty.",
        )

        _show_flash(CREATE_FLASH_KEY)

        # One-shot field reset, applied before the widgets are instantiated.
        if st.session_state.pop("_doc_clear_fields", False):
            for widget_key in ("doc_new_name", "doc_new_spec"):
                st.session_state.pop(widget_key, None)

        attempted = bool(st.session_state.get(ATTEMPT_KEY, False))

        dept_names = {d.get("name"): d.get("department_id") for d in departments if d.get("name")}
        dept_pick = st.selectbox(
            "Department",
            list(dept_names.keys()),
            disabled=not dept_names,
            key="doc_new_dept",
            help="Departments are managed on the Departments page.",
        )
        if not dept_names:
            st.error("Create a department before adding doctors.")

        full_name = st.text_input(
            "Full name",
            key="doc_new_name",
            placeholder="e.g. Kavita Menon",
            help="At least 2 characters (without the 'Dr.' prefix).",
        )
        err = _required_error(full_name, attempted, "Full name", min_len=2)
        if err:
            st.error(err)

        specialization = st.text_input(
            "Specialization",
            key="doc_new_spec",
            placeholder="e.g. Interventional Cardiology",
            help="At least 3 characters.",
        )
        err = _required_error(specialization, attempted, "Specialization", min_len=3)
        if err:
            st.error(err)

        c1, c2 = st.columns(2)
        with c1:
            experience_years = st.number_input(
                "Experience (years)",
                min_value=0,
                max_value=50,
                value=10,
                step=1,
                key="doc_new_exp",
            )
        with c2:
            status = st.selectbox(
                "Status",
                ["active", "inactive"],
                format_func=lambda s: STATUS_OPTIONS[s],
                key="doc_new_status",
            )

        if st.button("Create Doctor", type="primary", width="stretch"):
            if not dept_names:
                st.error("Create a department before adding doctors.")
            else:
                st.session_state[ATTEMPT_KEY] = True
                if any(
                    (
                        _required_error(full_name, True, "Full name", min_len=2),
                        _required_error(specialization, True, "Specialization", min_len=3),
                    )
                ):
                    # Rerun so the inline messages next to each field appear immediately.
                    st.rerun()

                with st.spinner("Creating doctor…"):
                    result = doctor_service.create(
                        department_id=dept_names[dept_pick],
                        full_name=full_name.strip(),
                        specialization=specialization.strip(),
                        experience_years=int(experience_years),
                        status=status,
                    )
                if result.success:
                    st.session_state[CREATE_FLASH_KEY] = (
                        f"Dr. {full_name.strip()} added to {dept_pick}."
                    )
                    st.session_state[ATTEMPT_KEY] = False
                    st.session_state["_doc_clear_fields"] = True
                    st.rerun()
                else:
                    display_api_error(result)

    # ---------- List ----------
    with tab_list:
        section_title("All Doctors", "Ordered by name. Edit entries inline below each card.")
        _show_flash(EDIT_FLASH_KEY)

        filter_cols = st.columns(2)
        with filter_cols[0]:
            status_filter = st.selectbox(
                "Status",
                ["All", "active", "inactive"],
                format_func=lambda s: "All statuses" if s == "All" else STATUS_OPTIONS[s],
                key="doctors_status_filter",
            )
        with filter_cols[1]:
            dept_filter = st.selectbox(
                "Department",
                ["All"] + [d.get("name") for d in departments],
                key="doctors_dept_filter",
            )

        params = {}
        if status_filter != "All":
            params["status"] = status_filter
        if dept_filter != "All":
            params["department_id"] = next(
                (d.get("department_id") for d in departments if d.get("name") == dept_filter),
                None,
            )

        res = doctor_service.list(limit=200, **params) if params else doctor_service.list(limit=200)
        if not res.success:
            display_api_error(res)
            st.stop()

        raw = res.data
        if isinstance(raw, list):
            doctors = [d for d in raw if isinstance(d, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("doctors"), list):
            doctors = [d for d in raw["doctors"] if isinstance(d, dict)]
        else:
            doctors = []

        if not doctors:
            empty_state(
                "No doctors match the current filters.",
                "Try a different status or department filter."
            )
            return

        for doc in doctors:
            _render_doctor_row(doc, doctor_service, dept_lookup, departments)


def _render_doctor_row(
    doc: dict,
    service: DoctorAdminService,
    dept_lookup: dict,
    departments: list,
) -> None:
    """Render a doctor card with inline edit controls."""
    doctor_id = doc.get("doctor_id")
    with st.container(border=True):
        col1, col2, col3 = st.columns([2.6, 1.6, 1])
        with col1:
            st.write(f"**Dr. {doc.get('full_name')}**")
            st.caption(f"{doc.get('specialization')} · {doc.get('experience_years')} yrs experience")
            st.caption(
                f"Updated {format_datetime(doc.get('updated_at') or doc.get('created_at'))}"
                + (f" · ID: {str(doctor_id)[:8]}" if doctor_id else "")
            )
        with col2:
            dept_name = dept_lookup.get(doc.get("department_id"), "Unknown")
            st.markdown(f":material/local_hospital: {dept_name}")
        with col3:
            status = doc.get("status")
            status_pill(status, custom_label=STATUS_OPTIONS.get(status, str(status).title() if status else "—"))

        if not doctor_id:
            return

        with st.expander("Edit doctor"):
            dept_options = {d.get("name"): d.get("department_id") for d in departments}
            current_dept_name = dept_lookup.get(doc.get("department_id"))
            try:
                current_idx = list(dept_options.keys()).index(current_dept_name) if current_dept_name in dept_options else 0
            except ValueError:
                current_idx = 0

            with st.form(f"edit_doctor_{doctor_id}"):
                dept_pick = st.selectbox(
                    "Department",
                    list(dept_options.keys()),
                    index=current_idx,
                    key=f"docdept_{doctor_id}",
                )
                full_name = st.text_input(
                    "Full name",
                    value=str(doc.get("full_name") or "").removeprefix("Dr. "),
                    key=f"docname_{doctor_id}",
                )
                specialty = st.text_input(
                    "Specialization",
                    value=doc.get("specialization") or "",
                    key=f"docspec_{doctor_id}",
                )
                c1, c2 = st.columns(2)
                with c1:
                    experience = st.number_input(
                        "Experience (years)",
                        min_value=0,
                        max_value=50,
                        value=int(doc.get("experience_years") or 0),
                        key=f"docexp_{doctor_id}",
                    )
                with c2:
                    status = st.selectbox(
                        "Status",
                        ["active", "inactive"],
                        index=0 if doc.get("status") == "active" else 1,
                        format_func=lambda s: STATUS_OPTIONS[s],
                        key=f"docstatus_{doctor_id}",
                    )
                cA, cB = st.columns(2)
                with cA:
                    save = st.form_submit_button("Save Changes", type="primary", width="stretch")
                with cB:
                    cancel = st.form_submit_button("Cancel", width="stretch")

            if save and not cancel:
                clean_name = (full_name or "").strip()
                if _required_error(clean_name, True, "Full name", min_len=2):
                    st.error("Full name must be at least 2 characters.")
                elif _required_error(specialty, True, "Specialization", min_len=3):
                    st.error("Specialization must be at least 3 characters.")
                else:
                    payload = {}
                    new_dept_id = dept_options.get(dept_pick)
                    if new_dept_id and new_dept_id != doc.get("department_id"):
                        payload["department_id"] = new_dept_id
                    if clean_name != str(doc.get("full_name") or ""):
                        payload["full_name"] = clean_name
                    if (specialty or "").strip() != (doc.get("specialization") or ""):
                        payload["specialization"] = (specialty or "").strip()
                    if int(experience) != int(doc.get("experience_years") or 0):
                        payload["experience_years"] = int(experience)
                    if status != doc.get("status"):
                        payload["status"] = status
                    if not payload:
                        st.info("No changes to save.")
                    else:
                        result = service.update(doctor_id, **payload)
                        if result.success:
                            st.session_state[EDIT_FLASH_KEY] = f"Dr. {clean_name} updated."
                            st.rerun()
                        else:
                            display_api_error(result)


if __name__ == "__main__":
    render()
