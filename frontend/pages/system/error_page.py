"""
500 — Unexpected Error.
"""
import streamlit as st

from frontend.components.navbar import page_head


def render():
    page_head("Something Went Wrong", "An unexpected error occurred while loading this page.")
    st.markdown(":material/error:")
    st.markdown(
        """
        <div style="text-align:center; padding:1rem 1rem 3rem 1rem;">
            <h2 style="color: var(--mc-navy);">Unexpected Error</h2>
            <p style="color: var(--mc-muted);">
                We couldn't complete your request. Please try again — if the problem
                persists, contact the care desk with the details shown below.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    exc = st.session_state.get("_last_error")
    if exc:
        with st.expander("Technical Details"):
            st.code(f"{type(exc).__name__}: {exc}")

    registry = st.session_state.get("_mc_pages", {})
    c1, c2 = st.columns(2)
    with c1:
        st.page_link(registry.get("home"), label="Go to Home", icon=":material/home:")
    with c2:
        if st.button("Reload Page", width="stretch"):
            st.rerun()


if __name__ == "__main__":
    render()