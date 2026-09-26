"""
Shared, lightweight UI primitives.

One implementation each of: loading state, expandable row/bar, pagination,
circular user menu, inline validation and neutral note blocks. Pages should
use these instead of hand-rolling near-identical markup.
"""
from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import streamlit as st

from frontend.components.navbar import empty_state, section_title  # noqa: F401  (re-export)
from frontend.utils.states import display_api_error, status_pill

__all__ = [
    "loading",
    "expandable_row",
    "pagination",
    "user_menu",
    "field_error",
    "friendly_error",
    "empty_state",
    "section_title",
    "recommendation_note",
    "recommendation_bullets",
    "doctor_label",
    "date_chips",
]


# =====================================================================
# Loading
# =====================================================================
@contextmanager
def loading(label: str = "Loading data") -> Iterator[None]:
    """Render a solid, labelled loading block while the body runs.

    The block is removed when the body finishes, so no stale/translucent
    content is left underneath. Use around any network call that the user
    should not have to guess about.
    """
    slot = st.empty()
    slot.markdown(
        f"""
        <div class="mc-loading" role="status" aria-live="polite">
            <span class="mc-loading-dot"></span>
            <span>{html.escape(label)}…</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        yield
    finally:
        slot.empty()


# =====================================================================
# Expandable row / bar
# =====================================================================
def expandable_row(
    row_id: str,
    *,
    title: str,
    meta: Optional[str] = None,
    meta_lines: Optional[list[str]] = None,
    pill: Optional[str] = None,
    extra: Optional[str] = None,
    open_key: Optional[str] = None,
    default_open: bool = False,
    actions: Optional[Callable[[], Any]] = None,
    badge_html: Optional[str] = None,
    id_text: Optional[str] = None,
) -> bool:
    """Compact row that collapses to essentials and expands to reveal actions.

    Returns True when the row is open. ``actions`` is called only while open,
    so expensive rendering (forms, sub-lists) happens on demand.

    ``meta`` is a single summary line (scheduled time / department / doctor).
    ``meta_lines`` is an optional list of additional lines (e.g. "Checked in
    at ...") rendered one-per-line below ``meta``, instead of being joined
    with " · " onto the same paragraph.
    """
    state_key = open_key or f"mc_row_open::{row_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = default_open
    is_open = bool(st.session_state[state_key])

    with st.container(border=True):
        head, right, toggle = st.columns([6.4, 1.7, 0.9], vertical_alignment="top")

        with head:
            st.markdown(f'<p class="mc-row-title">{html.escape(title)}</p>', unsafe_allow_html=True)
            if id_text:
                st.markdown(
                    f'<p class="mc-row-meta"><span class="mc-row-id">{html.escape(id_text)}</span></p>',
                    unsafe_allow_html=True,
                )
            if meta:
                st.markdown(f'<p class="mc-row-meta">{html.escape(meta)}</p>', unsafe_allow_html=True)
            for line in (meta_lines or []):
                if line:
                    st.markdown(f'<p class="mc-row-meta">{html.escape(line)}</p>', unsafe_allow_html=True)

        with right:
            if badge_html:
                st.markdown(badge_html, unsafe_allow_html=True)
            if pill:
                status_pill(pill)
            elif extra:
                st.caption(extra)

        with toggle:
            if st.button(
                "" if not is_open else "Hide",
                key=f"mc_toggle::{row_id}",
                icon=":material/expand_more:" if not is_open else ":material/expand_less:",
                width="stretch",
                help="Show details and actions" if not is_open else "Hide details",
            ):
                st.session_state[state_key] = not is_open
                st.rerun()

        if is_open and actions is not None:
            st.markdown('<div class="mc-row-actions"></div>', unsafe_allow_html=True)
            actions()

    return is_open

# =====================================================================
# Pagination
# =====================================================================
def pagination(total: int, page_size: int, key: str) -> tuple[int, int]:
    """Render prev/next pagination and return ``(offset, limit)``.

    Page state lives in ``session_state[key]``; it is clamped whenever the
    result set shrinks (e.g. after a filter change).
    """
    total = int(total or 0)
    pages = max(1, -(-total // page_size)) if page_size else 1
    page = int(st.session_state.get(key, 1) or 1)
    page = min(max(page, 1), pages)

    left, mid, right = st.columns([1, 2, 1])
    with left:
        if page > 1 and st.button(
            "Previous",
            key=f"{key}::prev",
            icon=":material/chevron_left:",
            width="stretch",
        ):
            st.session_state[key] = page - 1
            st.rerun()
    with mid:
        start = (page - 1) * page_size + 1 if total else 0
        end = min(page * page_size, total)
        st.markdown(
            f'<div class="mc-pagination"><span>Showing {start}&ndash;{end} of {total} &middot; '
            f"Page {page} of {pages}</span></div>",
            unsafe_allow_html=True,
        )
    with right:
        if page < pages and st.button(
            "Next",
            key=f"{key}::next",
            icon=":material/chevron_right:",
            icon_position="right",
            width="stretch",
        ):
            st.session_state[key] = page + 1
            st.rerun()

    st.session_state[key] = page
    return (page - 1) * page_size, page_size


def page_slice(rows: list, total: int, page_size: int, key: str) -> tuple[list, int, int]:
    """Convenience: paginate ``rows`` and return ``(slice, offset, limit)``."""
    offset, limit = pagination(total, page_size, key)
    return rows[offset:offset + limit], offset, limit


# =====================================================================
# User menu (rounded-square initials control)
# =====================================================================
def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p.strip()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def user_menu(
    *,
    profile_page: Any = None,
    login_page: Any = None,
    home_page: Any = None,
    on_sign_out: Optional[Callable[[], None]] = None,
) -> None:
    """Circular user-initials control; clicking it reveals profile/sign-out."""
    from frontend.utils.session import current_user, is_authenticated, logout

    if not is_authenticated():
        return

    user = current_user()
    name = user.display_name if user else "User"
    role = (user.role_label if user else "User")
    initials = _initials(name)

    st.markdown(
        """
        <style>
        /* Flattened wrapper chain: the chip is centred on the same baseline as
           the brand mark and nav links (margins/padding on any wrapper in the
           chain would push it off that line). */
        div.st-key-mc_user_chip,
        div.st-key-mc_user_chip > div,
        div.st-key-mc_user_chip div[data-testid="stElementContainer"],
        div.st-key-mc_user_chip div[data-testid="stPopover"] {
            margin: 0 !important;
            padding: 0 !important;
        }
        div.st-key-mc_user_chip {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-end !important;
            width: 100% !important;
        }
        div.st-key-mc_user_chip > div {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-end !important;
            width: auto !important;
        }
        /* The box itself: fixed size, clipped, centered content only. */
        div.st-key-mc_user_chip button {
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            width: 2.6rem !important;
            height: 2.6rem !important;
            min-width: 2.6rem !important;
            min-height: 2.6rem !important;
            max-width: 2.6rem !important;
            max-height: 2.6rem !important;
            border-radius: 50% !important;
            background: #86EFAC !important;
            border: 1.5px solid #4ADE80 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            transition: background 0.15s ease, transform 0.1s ease;
        }
        div.st-key-mc_user_chip button:hover {
            background: #6EE7A0 !important;
            transform: scale(1.04);
        }
        div.st-key-mc_user_chip button:active {
            transform: scale(0.97);
        }
        /* Every descendant (Streamlit wraps the label in nested div/p/span)
           collapses to plain inline text, no padding/margin/gap of its own,
           so nothing pushes the box wider than the fixed size above. */
        div.st-key-mc_user_chip button * {
            all: unset !important;
            display: inline !important;
            margin: 0 !important;
            padding: 0 !important;
            font-weight: 800 !important;
            font-size: 0.85rem !important;
            line-height: 1 !important;
            color: #14532D !important;
            font-family: inherit !important;
            white-space: nowrap !important;
        }
        /* Hide any icon/caret Streamlit's popover trigger auto-appends. */
        div.st-key-mc_user_chip button svg,
        div.st-key-mc_user_chip button img,
        div.st-key-mc_user_chip button [data-testid="stIconMaterial"] {
            display: none !important;
        }
        /* Popover panel: rounded card, soft border/shadow, generous padding —
           matches the light-green theme instead of Streamlit's bare default. */
        div[data-testid="stPopoverBody"] {
            border-radius: 12px !important;
            border: 1px solid rgba(134, 239, 172, 0.6) !important;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12) !important;
            padding: 1rem 1.1rem !important;
            min-width: 210px !important;
        }
        div[data-testid="stPopoverBody"] [data-testid="stCaptionContainer"]:first-of-type p {
            font-size: 0.95rem !important;
            color: #111827 !important;
        }
        div[data-testid="stPopoverBody"] [data-testid="stCaption"],
        div[data-testid="stPopoverBody"] [data-testid="stCaption"] span {
            color: #4B5563 !important;
        }
        div[data-testid="stPopoverBody"] a[data-testid="stPageLink-NavLink"] {
            border-radius: 8px !important;
            padding: 0.4rem 0.6rem !important;
        }
        div[data-testid="stPopoverBody"] a[data-testid="stPageLink-NavLink"]:hover {
            background: rgba(134, 239, 172, 0.25) !important;
        }
        div[data-testid="stPopoverBody"] button[kind="secondary"] {
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.popover(initials, key="mc_user_chip", help=f"{name} · {role}") as menu:
        st.caption(f"**{name}**")
        st.caption(role)
        st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
        if profile_page is not None:
            st.page_link(
                profile_page,
                label="My profile",
                icon=":material/person:",
                width="stretch",
            )
        if st.button(
            "Sign out",
            key="mc_user_signout",
            icon=":material/logout:",
            width="stretch",
        ):
            if on_sign_out is not None:
                on_sign_out()
            else:
                logout()
            if login_page is not None:
                st.switch_page(login_page)
            else:
                st.rerun()
        _ = menu  # container kept for API clarity

# =====================================================================
# Validation / errors
# =====================================================================
def date_chips(
    dates: list,
    *,
    session_key: str,
    key_prefix: str,
    label: str = "Choose a date",
    hint: str | None = None,
    clear_keys_on_change: list | None = None,
) -> None:
    """Selectable date chips showing only dates that actually have slots.

    Replaces the full calendar: future dates only, limited to the dates the
    availability endpoint returned.
    """
    if not dates:
        return

    st.markdown(f"**{label}**")
    if hint:
        st.caption(hint)

    cols = st.columns(min(5, max(1, len(dates))), gap="small")
    for idx, day in enumerate(sorted(dates)):
        with cols[idx % len(cols)]:
            selected = st.session_state.get(session_key) == day
            if st.button(
                day.strftime("%a %d %b"),
                key=f"{key_prefix}_{day.isoformat()}",
                type="primary" if selected else "secondary",
                width="stretch",
            ):
                if st.session_state.get(session_key) != day:
                    for k in clear_keys_on_change or []:
                        st.session_state[k] = None
                st.session_state[session_key] = day
                st.rerun()


def field_error(message: Optional[str]) -> None:
    """Inline validation message rendered directly under a field."""
    if message:
        st.markdown(
            f'<p style="color:#B91C1C;font-size:0.82rem;margin:0.15rem 0 0.5rem 0;">'
            f"{html.escape(message)}</p>",
            unsafe_allow_html=True,
        )


def friendly_error(res: Any) -> None:
    """Human-readable API failure — never a raw exception."""
    display_api_error(res)


def doctor_label(name: Optional[str]) -> str:
    """Doctor display name, shown exactly as the backend stores it."""
    raw = (name or "").strip()
    if not raw:
        return "Doctor"
    lowered = raw.lower()
    if lowered.startswith("dr.") or lowered.startswith("dr "):
        return raw
    return f"{raw}"


# =====================================================================
# Neutral note (future recommendation areas)
# =====================================================================
def recommendation_note(title: str = "Insights") -> None:
    """Neutral placeholder for a future LLM-backed recommendation area.

    Deliberately states no numbers, forecasts or advice — it only marks
    where model-generated guidance will appear later.
    """
    st.markdown(
        f"""
        <div class="mc-note">
            <strong>{html.escape(title)}</strong><br>
            Automated insights for this view are not enabled yet. All figures
            shown above come directly from live hospital data.
        </div>
        """,
        unsafe_allow_html=True,
    )


def recommendation_bullets(
    title: str,
    bullets: list[str],
    caption: Optional[str] = None,
) -> None:
    """Model-generated recommendation bullets inside the neutral note block.

    Every bullet is HTML-escaped, so text produced by the model can never
    inject markup into the page. ``caption`` is a short, plain note shown
    under the title (never raw error or provider text).
    """
    items = "".join(f"<li>{html.escape(str(b).strip())}</li>" for b in bullets if str(b).strip())
    caption_html = f"<br><span>{html.escape(caption)}</span>" if caption else ""
    st.markdown(
        f"""
        <div class="mc-note">
            <strong>{html.escape(title)}</strong>{caption_html}
            <ul style="margin:0.4rem 0 0.2rem 1.1rem;padding:0;">{items}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )