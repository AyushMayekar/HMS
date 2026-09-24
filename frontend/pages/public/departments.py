"""
Public Departments page — browsable without sign-in.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, empty_state
from frontend.config import HOSPITAL
from frontend.api.services import CatalogService
from frontend.components.cards import department_card, doctor_card
from frontend.utils.states import display_api_error


def _card_grid(items: list, renderer) -> None:
    """Render items as a responsive grid of shared cards."""
    for i in range(0, len(items), 3):
        cols = st.columns(3, gap="medium")
        for j, col in enumerate(cols):
            idx = i + j
            if idx < len(items):
                with col:
                    renderer(items[idx])


def render() -> None:
    page_head(
        "Our Departments",
        "Browse every clinical department, the services it provides, and the specialists "
        "who work in it — no sign-in required.",
    )

    catalog = CatalogService()

    # ---------------- Departments ----------------
    with st.spinner("Loading departments..."):
        dept_res = catalog.departments()

    if not dept_res.success:
        display_api_error(dept_res)
        empty_state(
            "Departments are unavailable right now",
            "Please try again in a moment.",
        )
        st.caption(HOSPITAL.disclaimer)
        return

    departments = dept_res.data or []
    if not departments:
        empty_state(
            "No departments published yet",
            "Department information will appear here as soon as it is available.",
        )
        st.caption(HOSPITAL.disclaimer)
        return

    # ---------------- Specialists ----------------
    with st.spinner("Loading specialists..."):
        doctor_res = catalog.doctors()
    doctors = list(doctor_res.data or []) if doctor_res.success else []

    # Summary
    active_count = sum(1 for d in departments if d.get("status") == "active")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total departments", len(departments))
    with col2:
        st.metric("Currently active", active_count)
    with col3:
        st.metric(
            "Specialists listed",
            len(doctors) if doctor_res.success else "—",
        )

    st.divider()

    # ---------------- Directory + search ----------------
    section_title(
        "Department Directory",
        "Each card describes what the department does, the services it offers, and its status.",
    )

    query = st.text_input(
        "Search by department name",
        placeholder="e.g. Cardiology",
        key="dept_search",
        help="Type part of a department name to filter the list.",
    )
    q = (query or "").strip().lower()
    if q:
        filtered = [
            d for d in departments if q in (d.get("name") or "").strip().lower()
        ]
    else:
        filtered = departments

    if not filtered:
        empty_state(
            f'No departments match "{(query or "").strip()}"',
            "Try a different or shorter search term.",
        )
    else:
        _card_grid(filtered, department_card)

    st.divider()

    # ---------------- Specialists ----------------
    section_title(
        "Our Specialists",
        "Doctors from the live hospital directory, presented with their department and experience.",
    )

    if not doctor_res.success:
        display_api_error(doctor_res)
        empty_state(
            "Specialist listings are unavailable right now",
            "Please try again in a moment.",
        )
    elif not doctors:
        empty_state(
            "No specialists listed yet",
            "Doctor profiles will appear here once they are published.",
        )
    else:
        dept_names = sorted(
            {d.get("department_name") for d in doctors if d.get("department_name")}
        )
        selected = "All departments"
        shown = doctors
        if dept_names:
            selected = st.selectbox(
                "Filter specialists by department",
                ["All departments"] + dept_names,
                key="doc_dept_filter",
            )
            if selected != "All departments":
                shown = [
                    d for d in doctors if d.get("department_name") == selected
                ]

        if not shown:
            empty_state(
                f"No specialists listed in {selected} yet",
                "Choose another department to see its specialists.",
            )
        else:
            st.caption(
                f"Showing {len(shown)} of {len(doctors)} specialists listed by the hospital."
            )
            _card_grid(shown, doctor_card)

    st.caption(HOSPITAL.disclaimer)


if __name__ == "__main__":
    render()
