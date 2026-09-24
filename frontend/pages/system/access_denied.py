"""
403 — Access Denied.
"""
import streamlit as st

from frontend.components.navbar import page_head
from frontend.utils.session import is_authenticated, current_role


def render():
    page_head("Access Denied", "You don't have permission to view this page.")
    role = current_role()
    st.markdown(":material/lock:")
    st.markdown(
        f"""
        <div style="text-align:center; padding:3rem 1rem;">
            <div style="font-size:2.5rem; color: var(--mc-navy);">:material/lock:</div>
            <h2 style="color: var(--mc-navy);">Access Denied</h2>
            <p style="color: var(--mc-muted);">
                This area is restricted{ f" to a different role than your current account ({role})" if role else "" }.
                If you believe this is a mistake, please contact the care desk.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    registry = st.session_state.get("_mc_pages", {})
    c1, c2 = st.columns(2)
    with c1:
        st.page_link(registry.get("home"), label="Go to Home", icon=":material/home:")
    with c2:
        if not is_authenticated():
            st.page_link(registry.get("login"), label="Sign In", icon=":material/login:")
        else:
            st.page_link(registry.get("home"), label="My Home", icon=":material/person:")


if __name__ == "__main__":
    render()