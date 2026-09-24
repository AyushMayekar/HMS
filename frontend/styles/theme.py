"""
Shared CSS styles for the Meridian Care Streamlit frontend.
Based on the theme from streamlit_app_latest2 but modernized.
"""
from __future__ import annotations

import streamlit as st

from frontend.config import COLORS, HOSPITAL


def inject_base_css() -> None:
    """Inject the base CSS styles for the application."""
    st.markdown(
        f"""
        <style>
        /* ------------------------------------------------------------
           Cross-platform foundations.
           - Explicit font stack: identical metrics on Windows (Segoe UI),
             macOS and Linux (Noto/Liberation/DejaVu) so spacing and
             wrapping match everywhere.
           - Minimal CSS reset: browsers/platforms differ in default
             box-sizing, margins and font smoothing.
           ------------------------------------------------------------ */
        *, *::before, *::after {{
            box-sizing: border-box;
        }}
        html {{
            -webkit-text-size-adjust: 100%;
            text-size-adjust: 100%;
        }}
        html, body {{
            margin: 0;
            padding: 0;
        }}
        .stApp,
        .stApp input,
        .stApp button,
        .stApp textarea,
        .stApp select {{
            font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont,
                         Roboto, "Helvetica Neue", Arial, "Noto Sans",
                         "Liberation Sans", DejaVu, sans-serif;
        }}
        .stApp code,
        .stApp pre,
        .stApp [data-testid="stCodeBlock"] {{
            font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono",
                         "Liberation Mono", Menlo, monospace;
        }}
        .stApp {{
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: optimizeLegibility;
        }}

        :root {{
            --mc-navy: {COLORS["navy"]};
            --mc-teal: {COLORS["teal"]};
            --mc-teal-soft: {COLORS["teal_soft"]};
            --mc-canvas: {COLORS["canvas"]};
            --mc-surface: {COLORS["surface"]};
            --mc-text: {COLORS["text"]};
            --mc-muted: {COLORS["muted"]};
            --mc-border: {COLORS["border"]};
            --mc-danger: {COLORS["danger"]};
            --mc-success: {COLORS["success"]};
            --mc-warning: {COLORS["warning"]};
            --mc-radius: 12px;
            --mc-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(11, 60, 93, 0.06);
        }}

        /* App canvas */
        .stApp {{
            background: var(--mc-canvas);
            color: var(--mc-text);
        }}

        .block-container {{
            padding-top: 1rem;
            padding-bottom: 3rem;
            max-width: 1180px;
        }}

        /* Hide Streamlit chrome noise */
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        header[data-testid="stHeader"] {{
            background: transparent;
        }}

        /* Typography */
        h1, h2, h3, h4 {{
            color: var(--mc-navy) !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
        }}

        p, label, .stMarkdown, .stCaption {{
            color: var(--mc-text);
        }}

        /* Page hero */
        .mc-page-head {{
            display: flex;
            gap: 1rem;
            align-items: stretch;
            background: var(--mc-surface);
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
            box-shadow: var(--mc-shadow);
            margin: 0.25rem 0 1.35rem 0;
            overflow: hidden;
        }}
        .mc-page-head-accent {{
            width: 6px;
            background: linear-gradient(180deg, var(--mc-navy), var(--mc-teal));
            flex-shrink: 0;
        }}
        .mc-page-head-body {{
            padding: 1.15rem 1.35rem 1.2rem 0.35rem;
        }}
        .mc-page-eyebrow {{
            margin: 0 0 0.25rem 0;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--mc-teal);
        }}
        .mc-page-title {{
            margin: 0 !important;
            font-size: clamp(1.45rem, 2.2vw, 1.85rem) !important;
            line-height: 1.2 !important;
            color: var(--mc-navy) !important;
        }}
        .mc-page-sub {{
            margin: 0.45rem 0 0 0;
            color: var(--mc-muted);
            font-size: 0.98rem;
            line-height: 1.55;
            max-width: 52rem;
        }}

        .mc-section-head {{
            margin: 0.35rem 0 0.85rem 0;
        }}
        .mc-section-title {{
            margin: 0 !important;
            font-size: 1.2rem !important;
            color: var(--mc-navy) !important;
        }}
        .mc-section-desc {{
            margin: 0.3rem 0 0 0;
            color: var(--mc-muted);
            font-size: 0.92rem;
        }}

        .mc-breadcrumb {{
            font-size: 0.82rem;
            color: var(--mc-muted);
            margin: 0 0 0.75rem 0;
        }}

        .mc-privacy-banner {{
            display: flex;
            gap: 0.65rem;
            align-items: flex-start;
            background: #F0F9FF;
            border: 1px solid #BAE6FD;
            color: #0C4A6E;
            border-radius: 10px;
            padding: 0.75rem 1rem;
            margin: 0 0 1rem 0;
            font-size: 0.9rem;
            line-height: 1.45;
        }}
        .mc-privacy-icon {{ flex-shrink: 0; }}

        .mc-empty-state {{
            background: var(--mc-surface);
            border: 1px dashed var(--mc-border);
            border-radius: var(--mc-radius);
            padding: 1.35rem 1.25rem;
            text-align: center;
            margin: 0.35rem 0 1rem 0;
        }}
        .mc-empty-msg {{
            margin: 0;
            color: var(--mc-text);
            font-weight: 600;
        }}
        .mc-empty-hint {{
            margin: 0.35rem 0 0 0;
            color: var(--mc-muted);
            font-size: 0.9rem;
        }}

        /* Navbar */
        .st-key-mc_main_nav {{
            background: var(--mc-surface);
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
            box-shadow: var(--mc-shadow);
            padding: 0.65rem 1rem 0.55rem 1rem;
            margin-bottom: 0.65rem;
            position: sticky;
            top: 0.35rem;
            z-index: 100;
        }}
        .st-key-mc_main_nav [data-testid="stCaption"] {{
            color: var(--mc-muted) !important;
        }}

        .mc-trust-strip {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem 1.1rem;
            align-items: center;
            justify-content: flex-start;
            background: var(--mc-navy);
            color: #E2E8F0;
            border-radius: 10px;
            padding: 0.55rem 1rem;
            margin: 0 0 1.1rem 0;
            font-size: 0.82rem;
            letter-spacing: 0.01em;
        }}
        .mc-trust-strip span {{
            white-space: nowrap;
        }}

        /* Cards / bordered containers */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: var(--mc-surface);
            border: 1px solid var(--mc-border) !important;
            border-radius: var(--mc-radius) !important;
            box-shadow: var(--mc-shadow);
            padding: 0.15rem 0.1rem;
        }}

        /* Metrics */
        div[data-testid="stMetric"] {{
            background: var(--mc-surface);
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
            padding: 0.85rem 1rem;
            box-shadow: var(--mc-shadow);
        }}
        div[data-testid="stMetricLabel"] {{
            color: var(--mc-muted) !important;
        }}
        div[data-testid="stMetricValue"] {{
            color: var(--mc-navy) !important;
        }}

        /* Buttons */
        .stButton > button,
        .stFormSubmitButton > button {{
            border-radius: 10px !important;
            font-weight: 600 !important;
            border: 1px solid var(--mc-border) !important;
            transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        .stButton > button:hover,
        .stFormSubmitButton > button:hover {{
            border-color: var(--mc-teal) !important;
            box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
        }}
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"],
        .stButton > button[data-testid="baseButton-primary"],
        button[kind="primary"] {{
            background: var(--mc-navy) !important;
            border-color: var(--mc-navy) !important;
            color: #fff !important;
        }}
        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primary"]:hover,
        button[kind="primary"]:hover {{
            background: #0A4F6E !important;
            border-color: #0A4F6E !important;
        }}
        .stButton > button:not([kind="primary"]),
        .stFormSubmitButton > button:not([kind="primary"]) {{
            background: var(--mc-surface) !important;
            color: var(--mc-text) !important;
        }}
        .stButton > button:focus-visible,
        .stFormSubmitButton > button:focus-visible,
        .stTextInput input:focus,
        .stTextArea textarea:focus,
        .stSelectbox [data-baseweb="select"] > div:focus-within {{
            outline: 2px solid var(--mc-teal) !important;
            outline-offset: 2px;
        }}

        /* Inputs */
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stDateInput input {{
            border-radius: 10px !important;
            border-color: var(--mc-border) !important;
        }}
        .stTextInput input:focus,
        .stTextArea textarea:focus {{
            border-color: var(--mc-teal) !important;
            box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.15) !important;
        }}

        /* Tabs */
        button[data-baseweb="tab"] {{
            font-weight: 600 !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] {{
            color: var(--mc-navy) !important;
        }}

        /* Expanders */
        details[data-testid="stExpander"] {{
            background: var(--mc-surface);
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
            box-shadow: var(--mc-shadow);
        }}

        /* Alerts */
        div[data-testid="stAlert"] {{
            border-radius: 10px;
        }}

        /* Dataframes */
        div[data-testid="stDataFrame"] {{
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
            overflow: hidden;
        }}

        /* Status pills */
        .mc-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            margin: 0.15rem 0 0.35rem 0;
        }}
        .mc-pill-neutral {{ background: #F1F5F9; color: #334155; }}
        .mc-pill-info {{ background: #E0F2FE; color: #075985; }}
        .mc-pill-success {{ background: #D1FAE5; color: #065F46; }}
        .mc-pill-warning {{ background: #FEF3C7; color: #92400E; }}
        .mc-pill-danger {{ background: #FEE2E2; color: #991B1B; }}
        .mc-pill-teal {{ background: var(--mc-teal-soft); color: #0F766E; }}

        /* Footer — content is wrapped by the keyed st.container (mc_footer),
           so the navy surface sits behind every footer element. */
        .st-key-mc_footer {{
            margin-top: 2.5rem;
            padding: 1.75rem 1.25rem 0.75rem 1.25rem;
            background: var(--mc-navy);
            border-radius: var(--mc-radius);
            color: #E2E8F0;
            clear: both;
        }}
        .st-key-mc_footer [data-testid="stMarkdownContainer"] p,
        .st-key-mc_footer [data-testid="stCaptionContainer"],
        .st-key-mc_footer [data-testid="stCaption"],
        .st-key-mc_footer [data-testid="stCaption"] span {{
            color: #E2E8F0 !important;
        }}
        .st-key-mc_footer a[data-testid="stPageLink-NavLink"] {{
            background: rgba(255, 255, 255, 0.10) !important;
            border: 1px solid rgba(255, 255, 255, 0.30);
            color: #F8FAFC !important;
        }}
        .st-key-mc_footer a[data-testid="stPageLink-NavLink"] * {{
            color: inherit !important;
        }}
        .st-key-mc_footer a[data-testid="stPageLink-NavLink"]:hover {{
            background: rgba(255, 255, 255, 0.18) !important;
        }}
        .mc-footer-logo {{
            margin: 0 0 0.4rem 0;
            font-size: 1.15rem;
            font-weight: 800;
            color: #FFFFFF !important;
        }}
        .mc-footer-heading {{
            margin: 0 0 0.55rem 0;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            color: #99F6E4 !important;
        }}
        .mc-footer-tagline,
        .mc-footer-meta {{
            margin: 0 0 0.35rem 0;
            font-size: 0.88rem;
            line-height: 1.5;
            color: #CBD5E1 !important;
        }}
        .mc-footer-bottom {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem 1.25rem;
            justify-content: space-between;
            margin-top: 1.25rem;
            padding: 0.9rem 0.15rem 0.35rem 0.15rem;
            border-top: 1px solid rgba(148, 163, 184, 0.35);
            font-size: 0.8rem;
            color: #CBD5E1;
        }}

        .meridian-card {{
            padding: 1rem 1.1rem;
            border-radius: var(--mc-radius);
            border: 1px solid var(--mc-border);
            background: var(--mc-surface);
            box-shadow: var(--mc-shadow);
            margin-bottom: 1rem;
        }}
        .meridian-muted {{
            color: var(--mc-muted);
        }}

        /* Chat */
        [data-testid="stChatMessage"] {{
            background: var(--mc-surface);
            border: 1px solid var(--mc-border);
            border-radius: var(--mc-radius);
        }}

        /* Page links: never clip labels — wrap instead of cutting off */
        [data-testid="stPageLink-NavLink"] {{
            border-radius: 8px;
            font-weight: 600;
            color: var(--mc-navy) !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            word-break: break-word;
            text-align: center;
            line-height: 1.25;
            min-height: 2.4rem;
        }}
        [data-testid="stPageLink-NavLink"] span {{ color: inherit !important; }}
        .st-key-mc_main_nav [data-testid="stPageLink-NavLink"] {{
            font-size: 0.8rem;
            padding: 0.45rem 0.4rem;
        }}
        .st-key-mc_main_nav {{ overflow: visible; }}

        @media (max-width: 768px) {{
            .block-container {{
                padding-left: 1rem;
                padding-right: 1rem;
            }}
            .mc-trust-strip {{
                font-size: 0.75rem;
            }}
            .mc-footer-bottom {{
                flex-direction: column;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def configure_page() -> None:
    """Configure the Streamlit page settings."""
    st.set_page_config(
        page_title=HOSPITAL.name,
        # Material icon (not an OS emoji) so the browser-tab mark renders
        # identically on Windows, macOS and Linux.
        page_icon=":material/local_hospital:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


# Re-export for backward compatibility
apply_theme = inject_base_css
inject_custom_css = inject_base_css