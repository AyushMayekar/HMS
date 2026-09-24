"""
Patient Profile page.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner
from frontend.utils.session import require_role, current_user, logout
from frontend.api.auth_services import AuthService
from frontend.utils.states import display_api_error, status_pill
from frontend.config import HOSPITAL


def render():
    page_head(
        "My Profile",
        "Your account details and preferences.",
        noindex=True,
    )
    user = require_role(["patient"])
    breadcrumb(["Patient", "Profile"])
    privacy_banner()

    # Refresh profile from the API for the latest details
    profile_res = AuthService().get_me()

    col1, col2 = st.columns([1.2, 2], gap="large")

    with col1:
        with st.container(border=True):
            st.markdown("### :material/person:")
            st.write(f"**{user.display_name}**")
            st.caption(user.role_label)
            status_pill(user.status or "active")
            st.divider()
            if st.button("Sign out", icon=":material/logout:", width="stretch"):
                logout()
                st.switch_page("pages/public/home.py")

    with col2:
        section_title("Account Information")

        data = profile_res.data if profile_res.success else {}
        full_name = (data or {}).get("full_name") or user.full_name or "—"
        email = (data or {}).get("email") or user.email
        phone = (data or {}).get("phone") or user.phone or "—"
        role = (data or {}).get("role") or user.role

        field_cols = st.columns(2)
        with field_cols[0]:
            st.write("**Full name**")
            st.write(full_name)
            st.write("**Email**")
            st.write(email)
        with field_cols[1]:
            st.write("**Phone**")
            st.write(phone)
            st.write("**Account type**")
            st.write((role or "patient").title())

        st.divider()

        with st.expander("Account & privacy"):
            st.markdown(
                f"""
                - Your medical and booking records are visible only to you and your care team.
                - The AI assistant keeps a per-account conversation thread for continuity.
                - For corrections to your profile or records, raise a **Support Request**
                  from your patient portal, or contact {HOSPITAL.email}.
                """
            )

    if not profile_res.success:
        display_api_error(profile_res)


if __name__ == "__main__":
    render()