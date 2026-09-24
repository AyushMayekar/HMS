"""
Administration › Management — one place for users, departments and doctors.

The three sections reuse the exact list/create code from their original pages
(``render_content``), so behaviour, validation and API calls are unchanged.
Only the selected section renders, which keeps the API calls identical to
visiting a single page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb
from frontend.utils.session import require_role, current_user

from frontend.pages.admin import users as users_page
from frontend.pages.admin import departments as departments_page
from frontend.pages.admin import doctors as doctors_page

SECTIONS = {
    "Users": (
        users_page,
        "Accounts across the hospital — roles, status, and staff provisioning.",
    ),
    "Departments": (
        departments_page,
        "Clinical departments shown in the patient portal and booking flow.",
    ),
    "Doctors": (
        doctors_page,
        "Clinician records — the team that patients book appointments with.",
    ),
}


def render() -> None:
    page_head(
        "Management",
        "Users, departments and doctors in a single management experience.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Management"])

    choice = st.radio(
        "Section",
        list(SECTIONS.keys()),
        key="admin_mgmt_section",
        horizontal=True,
        help="Switch between the three management areas without leaving the page.",
    )

    module, blurb = SECTIONS[choice]
    section_title(choice, blurb)
    module.render_content()


if __name__ == "__main__":
    render()
