"""
Public Contact page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title
from frontend.config import HOSPITAL


def render() -> None:
    page_head(
        "Contact Us",
        f"Reach the {HOSPITAL.short_name} care team, every channel below goes "
        "directly to our hospital.",
    )

    section_title("Contact Information")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.markdown("#### :material/pin_drop: Location")
            st.write(f"**{HOSPITAL.name}**")
            st.write(HOSPITAL.address)
            st.caption(HOSPITAL.website)

        with st.container(border=True):
            st.markdown("#### :material/mail: Email")
            st.write(HOSPITAL.email)
            st.caption("General enquiries, appointments, and feedback.")

    with col2:
        with st.container(border=True):
            st.markdown("#### :material/phone: Care Desk")
            st.write(HOSPITAL.phone)
            st.caption(f"{HOSPITAL.care_desk} for appointments and support.")

        with st.container(border=True):
            st.markdown("#### :material/emergency: Emergency")
            st.write(f"**{HOSPITAL.emergency}**")
            st.caption("For medical emergencies: 24 hours a day, 7 days a week.")

    st.divider()

    # -------------------------------------------------------------
    # Visiting & patient portal
    # -------------------------------------------------------------
    section_title(
        "Visiting & Patient Portal",
        "How to reach us in person and what you can do online.",
    )

    with st.container(border=True):
        st.write(
            f"**In person:** our {HOSPITAL.care_desk.lower()} receives patients at "
            f"{HOSPITAL.address}."
        )
        st.write(
            "**Online:** sign in to the patient portal to book, reschedule, or cancel "
            "appointments, view payments, track requests, and send feedback, without "
            "calling."
        )
        st.write(
            "**Planning a visit:** the Departments page lists every department, its "
            "services, and its specialists, open to everyone, no account needed."
        )

    registry = st.session_state.get("_mc_pages", {}) or {}
    link_cols = st.columns(3, gap="medium")
    with link_cols[0]:
        if not st.session_state.get("mc_auth", {}).get("logged_in"):
            st.page_link(
                registry.get("login") or "pages/public/login.py",
                label="Go to Sign In",
                icon=":material/lock:",
                width="stretch",
            )
        else:
            st.caption("You're signed in, use the navigation above to open your portal.")
    with link_cols[1]:
        st.page_link(
            registry.get("departments") or "pages/public/departments.py",
            label="Browse Departments",
            icon=":material/local_hospital:",
            width="stretch",
        )
    with link_cols[2]:
        st.page_link(
            registry.get("help") or "pages/public/help.py",
            label="Help & FAQ",
            icon=":material/help:",
            width="stretch",
        )




if __name__ == "__main__":
    render()
