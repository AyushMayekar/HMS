"""
404 — Page Not Found.
"""
import streamlit as st

from frontend.components.navbar import page_head, empty_state


def render():
    page_head("Page Not Found", "The page you were looking for doesn't exist or has moved.")
    st.markdown(":material/search:")
    st.markdown(
        """
        <div style="text-align:center; padding:1rem 1rem 3rem 1rem;">
            <h2 style="color: var(--mc-navy);">404 — Page Not Found</h2>
            <p style="color: var(--mc-muted);">
                The link may be outdated, or you may not have permission to view this screen.
                Use the navigation above to continue.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    registry = st.session_state.get("_mc_pages", {})
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        st.page_link(registry.get("home"), label="Go to Home", icon=":material/home:")
    with c2:
        st.page_link(registry.get("departments"), label="Browse Departments", icon=":material/local_hospital:")
    with c3:
        st.page_link(registry.get("login"), label="Sign In", icon=":material/login:")


if __name__ == "__main__":
    render()