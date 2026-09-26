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
    profile_page=None,
    home_page=None,
) -> None:
    """
    Render the horizontal navigation bar.

    Args:
        public_nav: List of (page, label, icon) for public pages
        role_nav: List of (page, label, icon) for role-specific pages
        login_page: Streamlit Page object for login
        authenticated: Whether user is authenticated (auto-detected if None)
        role: User role (auto-detected if None)
        profile_page: Optional page used by the user-initial menu
        home_page: Optional page the brand mark links to
    """
    if authenticated is None:
        authenticated = is_authenticated()

    if authenticated:
        role = role or current_role()
        links = [_details(x) for x in (role_nav or [])]
    else:
        links = [_details(x) for x in (public_nav or [])]
        if login_page:
            links.append((login_page, "Sign In / Sign Up", ":material/login:"))

    # The brand mark (icon + wordmark) already routes to home, so drop any
    # "Home" entry from the link row to avoid a duplicate way to get there.
    links = [item for item in links if (item[1] or "").strip().lower() != "home"]

    registry = st.session_state.get("_mc_pages", {}) or {}
    home = home_page or registry.get("home")

    # White navbar, black text, centered links, thin light-green border
    # underneath — matching the flat white navbar style referenced (brand
    # mark left, links centered, account control right). Sticky-pinned to
    # the top of the viewport so it stays visible while scrolling.
    st.markdown(
        """
        <style>
        div.st-key-mc_main_nav {
            background: #FFFFFF !important;
            border: none !important;
            border-bottom: 3px solid rgba(134, 239, 172, 0.9) !important;
            box-shadow: none !important;
            border-radius: 0 !important;
            padding: 0.7rem 1rem !important;
            position: sticky !important;
            top: 0 !important;
            z-index: 999 !important;
            overflow: visible;
        }
        div.st-key-mc_main_nav [data-testid="stCaption"],
        div.st-key-mc_main_nav [data-testid="stCaption"] span {
            color: #000000 !important;
        }
        div.st-key-mc_main_nav [data-testid="stPageLink-NavLink"] {
            color: #000000 !important;
            font-weight: 600 !important;
            justify-content: center !important;
        }
        div.st-key-mc_main_nav [data-testid="stPageLink-NavLink"] span {
            color: #000000 !important;
        }
        div.st-key-mc_main_nav [data-testid="stPageLink-NavLink"]:hover {
            background: rgba(134, 239, 172, 0.2) !important;
        }
        /* Brand mark: icon + wordmark, capped small enough to sit fully
           inside the navbar's own padding, vertically centered. */
        div.st-key-mc_brand {
            display: flex;
            align-items: center;
            justify-content: flex-start;
        }
        div.st-key-mc_brand div[data-testid="stVerticalBlock"] {
            display: flex;
            align-items: center;
        }
        div.st-key-mc_brand button {
            background: transparent !important;
            border: 1px solid transparent !important;
            box-shadow: none !important;
            padding: 0.15rem 0.4rem !important;
            margin: 0 !important;
            color: #000000 !important;
            min-width: auto !important;
            width: auto !important;
            height: 1.9rem !important;
            min-height: 1.9rem !important;
            max-height: 1.9rem !important;
            line-height: 1 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 0.3rem;
        }
        div.st-key-mc_brand button p {
            font-size: 0.92rem !important;
            font-weight: 800 !important;
            color: #000000 !important;
            margin: 0 !important;
            line-height: 1 !important;
            white-space: nowrap;
        }
        div.st-key-mc_brand button span[data-testid="stIconMaterial"] {
            font-size: 1.15rem !important;
            color: #000000 !important;
            line-height: 1 !important;
        }
        div.st-key-mc_brand button:hover {
            background: rgba(134, 239, 172, 0.25) !important;
        }
        /* Account chip wrapper: same flex-centering treatment as mc_brand,
           so the user-menu chip aligns on the same baseline as the brand
           mark and nav links instead of drifting from default widget
           spacing (Streamlit's element-container margins).

           Both wrappers below must declare `flex-direction: row`. Streamlit's
           stVerticalBlock defaults to `column`, and on a column axis
           `justify-content: flex-end` means BOTTOM, not right — which is what
           pushed the avatar ~18px below the nav baseline. On the row axis the
           same two declarations give exactly the intended result: right-hand
           edge (main) + dead-centre vertically (cross). `height: 100%` on the
           inner block guarantees the free space that centring needs. */
        div.st-key-mc_account {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            justify-content: flex-end !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        div.st-key-mc_account div[data-testid="stVerticalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            justify-content: flex-end !important;
            height: 100% !important;
            gap: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        /* The trigger's own wrappers must not contribute spacing either —
           any margin here inflates the box and re-offsets the centre. */
        div.st-key-mc_account div[data-testid="stButton"],
        div.st-key-mc_account div[data-testid="stPopover"] {
            margin: 0 !important;
            padding: 0 !important;
            height: auto !important;
        }
        div.st-key-mc_account div[data-testid="stVerticalBlockBorderWrapper"],
        div.st-key-mc_account div[data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
            width: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="mc_main_nav"):
        brand, nav, account = st.columns(
            # nav gets the larger share so the longest label ("Management")
            # fits its equal-width column instead of being sliced at the edge.
            [1.6, 7.1, 1.0],
            vertical_alignment="center",
            gap="small",
        )

        # Brand mark: icon + wordmark, always routes to home.
        with brand:
            with st.container(key="mc_brand"):
                if st.button(
                    "Meridian Care",
                    key="mc_brand_btn",
                    icon=":material/local_hospital:",
                    help=f"{HOSPITAL.short_name}. Go to the home page",
                ):
                    if home is not None:
                        st.switch_page(home)
                    else:
                        st.switch_page("pages/public/home.py")

        with nav:
            if links:
                cols = st.columns(len(links), gap="medium")
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
                from frontend.components.ui import user_menu

                with st.container(key="mc_account"):
                    user_menu(
                        profile_page=profile_page,
                        login_page=login_page,
                        home_page=home,
                    )

    # Trust strip: plain text only (no OS emojis) so it renders identically
    # on Windows and Linux, and without the portal-labelling text.
  

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

    # The footer's glass styling is injected globally by theme.inject_base_css()
    # — it is deliberately NOT emitted here. A render-time <style> only exists
    # for the run that emitted it, so any run where this function did not reach
    # its body left the old navy fallback in theme.py as the only rule.
    from datetime import datetime

    year = datetime.now().year

    # A keyed st.container genuinely wraps the columns in the DOM, so the
    # glass surface sits behind every footer element (an open/close <div>
    # across separate markdown blocks does NOT wrap in Streamlit).
    with st.container(key="mc_footer"):
        # 4th column carries no content (the bottom bar spans the full width
        # on its own); its weight is only there to keep the original layout
        # rhythm. Support is widened so "Privacy & Terms" is not clipped.
        brand_col, explore_col, support_col, notice_col = st.columns(
            [2.0, 1.1, 1.6, 1.5],
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

        st.markdown(
            f"""
            <div class="mc-footer-bottom">
                <span>&copy; {year} {HOSPITAL.name}</span>
                <span>Care desk: {HOSPITAL.phone} &middot; Emergency: {HOSPITAL.emergency}</span>
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