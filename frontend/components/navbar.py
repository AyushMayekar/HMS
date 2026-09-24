"""
Navigation and layout components for the Meridian Care frontend.
"""
from __future__ import annotations

import streamlit as st

from frontend.config import HOSPITAL
from frontend.utils.session import current_role, current_user, is_authenticated, logout
from frontend.styles.theme import HOSPITAL as THEME_HOSPITAL


def _details(item):
    """Extract page, label, and icon from navigation item."""
    if isinstance(item, tuple):
        return (
            item[0],
            item[1] if len(item) > 1 else getattr(item[0], "title", "Page"),
            item[2] if len(item) > 2 else getattr(item[0], "icon", None),
        )
    return item, getattr(item, "title", "Page"), getattr(item, "icon", None)


def render_navbar(
    public_nav=None,
    role_nav=None,
    login_page=None,
    authenticated=None,
    role=None,
) -> None:
    """
    Render the horizontal navigation bar.

    Args:
        public_nav: List of (page, label, icon) for public pages
        role_nav: List of (page, label, icon) for role-specific pages
        login_page: Streamlit Page object for login
        authenticated: Whether user is authenticated (auto-detected if None)
        role: User role (auto-detected if None)
    """
    if authenticated is None:
        authenticated = is_authenticated()

    if authenticated:
        role = role or current_role()
        links = [_details(x) for x in (role_nav or [])]
    else:
        links = [_details(x) for x in (public_nav or [])]
        if login_page:
            links.append((login_page, "Sign In", ":material/login:"))

    with st.container(key="mc_main_nav"):
        brand, nav, account = st.columns(
            [2.0, 7.8, 1.6],
            vertical_alignment="center",
            gap="small",
        )

        with brand:
            st.markdown(f"**:material/local_hospital: {HOSPITAL.short_name}**")
            st.caption(HOSPITAL.tagline)

        with nav:
            if links:
                cols = st.columns(len(links), gap="small")
                for col, (page, label, icon) in zip(cols, links):
                    with col:
                        st.page_link(
                            page,
                            label=label,
                            icon=icon,
                            width="stretch",
                        )

        with account:
            if authenticated:
                user = current_user()
                user_name = user.display_name if user else "User"
                role_label = (role or (user.role if user else "user") or "user").title()
                st.caption(f"**{user_name}** · {role_label}")
                if st.button(
                    "Sign out",
                    key="global_sign_out",
                    width="stretch",
                    help="End your secure session",
                ):
                    logout()
                    if login_page:
                        st.switch_page(login_page)
                    else:
                        st.rerun()

    # Trust strip: plain text only (no OS emojis) so it renders identically
    # on Windows and Linux, and without the portal-labelling text.
    st.markdown(
        f"""
        <div class="mc-trust-strip" role="complementary" aria-label="Care information">
            <span>Secure, role-based access</span>
            <span>Emergency {HOSPITAL.emergency}</span>
            <span>{HOSPITAL.care_desk}</span>
            <span>Walk-ins welcome at the care desk</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer(footer_pages: dict = None) -> None:
    """
    Render the common footer.

    Args:
        footer_pages: Dict with keys home, departments, about, contact, help, legal
                     containing Streamlit Page objects
    """
    if st.session_state.get("_mc_footer_done"):
        return

    pages = footer_pages or st.session_state.get("_mc_footer_pages") or {}

    from datetime import datetime

    year = datetime.now().year

    # A keyed st.container genuinely wraps the columns in the DOM, so the
    # navy surface sits behind every footer element (an open/close <div>
    # across separate markdown blocks does NOT wrap in Streamlit).
    with st.container(key="mc_footer"):
        brand_col, explore_col, support_col, notice_col = st.columns(
            [2.0, 1.1, 1.1, 2.0],
            gap="large",
        )

        with brand_col:
            st.markdown(
                f"""
                <div class="mc-footer-brand">
                    <p class="mc-footer-logo">Meridian Care</p>
                    <p class="mc-footer-tagline">{HOSPITAL.tagline}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(f"{HOSPITAL.address}")
            st.caption(f"Care desk: {HOSPITAL.phone}  ·  Emergency: {HOSPITAL.emergency}")
            st.caption(HOSPITAL.email)

        with explore_col:
            st.markdown(
                '<p class="mc-footer-heading">Explore</p>',
                unsafe_allow_html=True,
            )
            for key, label, icon, fallback in (
                ("home", "Home", ":material/home:", "Home"),
                ("departments", "Departments", ":material/local_hospital:", "Departments"),
                ("about", "About us", ":material/info:", "About Meridian Care"),
            ):
                if pages.get(key):
                    st.page_link(pages[key], label=label, icon=icon)
                else:
                    st.caption(fallback)

        with support_col:
            st.markdown(
                '<p class="mc-footer-heading">Support</p>',
                unsafe_allow_html=True,
            )
            for key, label, icon, fallback in (
                ("help", "Help & FAQ", ":material/help:", "Help & FAQ"),
                ("contact", "Contact", ":material/call:", "Contact"),
                ("legal", "Privacy & Terms", ":material/verified_user:", "Privacy & Terms"),
            ):
                if pages.get(key):
                    st.page_link(pages[key], label=label, icon=icon)
                else:
                    st.caption(fallback)

        with notice_col:
            st.markdown(
                f"""
                <div class="mc-footer-notice">
                    <p class="mc-footer-heading">About this platform</p>
                    <p class="mc-footer-meta">{HOSPITAL.disclaimer}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown(
            f"""
            <div class="mc-footer-bottom">
                <span>&copy; {year} {HOSPITAL.name}</span>
                <span>Care desk: {HOSPITAL.phone} &middot; Emergency: {HOSPITAL.emergency}</span>
                <span>Not a clinical decision-support system</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.session_state["_mc_footer_done"] = True


def page_head(
    title: str,
    subtitle: str | None = None,
    noindex: bool = False,
) -> None:
    """
    Render a consistent branded page header.

    Args:
        title: Page title
        subtitle: Optional subtitle
        noindex: Whether to add noindex meta (for private pages)
    """
    import html

    if not (title or "").strip():
        return

    safe_title = html.escape(title.strip())
    safe_sub = html.escape(subtitle.strip()) if subtitle else ""

    sub_html = (
        f'<p class="mc-page-sub">{safe_sub}</p>' if safe_sub else ""
    )

    st.markdown(
        f"""
        <div class="mc-page-head">
            <div class="mc-page-head-accent"></div>
            <div class="mc-page-head-body">
                <p class="mc-page-eyebrow">{html.escape(HOSPITAL.short_name)}</p>
                <h1 class="mc-page-title">{safe_title}</h1>
                {sub_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(
    title: str,
    description: str | None = None,
) -> None:
    """Render a consistent section heading."""
    import html

    safe_title = html.escape(title)
    safe_desc = html.escape(description) if description else ""
    desc_html = (
        f'<p class="mc-section-desc">{safe_desc}</p>' if safe_desc else ""
    )
    st.markdown(
        f"""
        <div class="mc-section-head">
            <h2 class="mc-section-title">{safe_title}</h2>
            {desc_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def breadcrumb(items: list[str]) -> None:
    """Simple text breadcrumb for authenticated workflows."""
    import html

    if not items:
        return
    trail = " / ".join(html.escape(x) for x in items)
    st.markdown(
        f'<nav class="mc-breadcrumb" aria-label="Breadcrumb">{trail}</nav>',
        unsafe_allow_html=True,
    )


def privacy_banner(text: str | None = None) -> None:
    """Lightweight privacy-oriented notice for clinical screens."""
    import html

    body = text or (
        "You are viewing your personal patient record. Your health information "
        "is confidential and is used only for your care. Sensitive actions "
        "require confirmation."
    )
    st.markdown(
        f"""
        <div class="mc-privacy-banner" role="note">
            <span>{html.escape(body)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(message: str, hint: str | None = None, icon: str = ":material/inbox:") -> None:
    """Friendly empty-state block for lists with no rows.

    ``icon`` accepts a Material Symbols shortcode (default). Shortcodes are
    resolved by Streamlit's markdown renderer so they look identical on
    Windows and Linux; legacy emoji arguments are ignored because OS emoji
    fonts differ per platform.
    """
    import html

    hint_html = (
        f'<p class="mc-empty-hint">{html.escape(hint)}</p>' if hint else ""
    )
    if icon.startswith(":material/") and icon.endswith(":"):
        st.markdown(f'<div style="text-align:center;">{icon}</div>')
    st.markdown(
        f"""
        <div class="mc-empty-state">
            <p class="mc-empty-msg">{html.escape(message)}</p>
            {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def success_message(text: str) -> None:
    """Show a success message."""
    st.success(text)


def warning_message(text: str) -> None:
    """Show a warning message."""
    st.warning(text)


def error_message(text: str) -> None:
    """Show an error message."""
    st.error(text)


def info_message(text: str) -> None:
    """Show an info message."""
    st.info(text)