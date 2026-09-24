"""
Patient Feedback page.

Rate completed visits (1-5 with an optional comment) and review previously
submitted feedback. Only completed appointments are eligible — matching the
backend rule — and duplicate submissions are prevented.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner, empty_state
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime
from frontend.api.services import FeedbackService, AppointmentService, CatalogService
from frontend.pages.patient._helpers import (
    appointment_context,
    build_doctor_map,
    render_flash,
    set_flash,
    short_id,
)

RATING_LABELS = {
    5: "Excellent",
    4: "Good",
    3: "Average",
    2: "Below average",
    1: "Poor",
}
COMMENT_MAX = 1000  # backend SubmitFeedbackRequest.comment limit
COMMENT_MIN = 3     # inline rule: no one-or-two character comments


def _rating_markdown(rating: int) -> str:
    """Filled/unfilled star row using Material shortcodes (no emoji)."""
    filled = " ".join([":material/star:"] * int(rating))
    empty = " ".join([":material/star_outline:"] * max(0, 5 - int(rating)))
    return f"{filled} {empty}".strip()


def render():
    page_head(
        "Feedback",
        "Share how your visit went — your input helps us improve care.",
        noindex=True,
    )
    require_role(["patient"])
    current_user()

    breadcrumb(["Patient", "Feedback"])
    privacy_banner()
    render_flash("feedback")

    feedback_service = FeedbackService()
    appt_service = AppointmentService()
    catalog = CatalogService()

    # ---------- Load real data ----------
    appts_res = appt_service.list(limit=200)
    if not appts_res.success:
        display_api_error(appts_res)
    appts = appts_res.data if appts_res.success else []

    fb_list_res = feedback_service.list(limit=200)
    if not fb_list_res.success:
        display_api_error(fb_list_res)
    feedback_list = fb_list_res.data if fb_list_res.success else []

    doctors_res = catalog.doctors()
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    appt_by_id = {a.get("appointment_id"): a for a in appts}
    completed = [a for a in appts if a.get("appointment_status") == "completed"]
    already_rated = {f.get("appointment_id") for f in feedback_list}

    # ---------- Submit ----------
    section_title(
        "Rate a Completed Visit",
        "Only completed visits can be rated, and each visit can be rated once.",
    )

    if not completed:
        st.info("You don't have any completed visits to rate yet. Feedback becomes available after your visit is completed.")
    else:
        rateable = [a for a in completed if a.get("appointment_id") not in already_rated]

        if not rateable:
            st.success("You've rated all your completed visits. Thank you for the feedback!")
        else:
            rateable.sort(key=lambda a: a.get("scheduled_start") or "")
            options = {appointment_context(a, doctor_map): a for a in rateable}

            pick = st.selectbox("Completed visit", list(options.keys()), key="fb_appt_pick")
            rating = int(st.slider(
                "Overall rating",
                min_value=1,
                max_value=5,
                value=5,
                format="%d",
                key="fb_rating",
            ))
            st.caption(f"{rating}/5 — {RATING_LABELS.get(rating, '')}")
            comment = st.text_area(
                "Comments (optional)",
                placeholder="What went well, and what could we improve?",
                max_chars=COMMENT_MAX,
                key="fb_comment",
                help=f"Up to {COMMENT_MAX} characters. Leave blank if you have nothing to add.",
            )

            comment_value = (comment or "").strip()
            comment_error = None
            if comment_value and len(comment_value) < COMMENT_MIN:
                comment_error = f"Comments must be at least {COMMENT_MIN} characters, or left blank."

            # Show the contextual message as soon as it is relevant.
            if comment_error and comment_value:
                st.error(comment_error)

            submitted = st.button(
                "Submit Feedback",
                type="primary",
                icon=":material/send:",
                width="stretch",
                key="fb_submit",
                disabled=bool(comment_error),
            )

            if submitted and not comment_error:
                appt = options[pick]
                with st.spinner("Submitting your feedback..."):
                    result = feedback_service.submit(
                        appointment_id=appt.get("appointment_id"),
                        rating=rating,
                        comment=comment_value or None,
                    )
                if result.success:
                    set_flash(
                        "feedback",
                        "success",
                        "Thank you! Your feedback ("
                        f"{rating}/5 for {appt.get('department_name') or 'your visit'} on "
                        f"{format_datetime(appt.get('scheduled_start'))}) has been recorded.",
                    )
                    st.rerun()
                else:
                    display_api_error(result)

    st.divider()

    # ---------- History (read-only) ----------
    section_title("Your Feedback", "Everything you've shared with us — read-only, one entry per visit.")

    if not feedback_list:
        empty_state("No feedback yet.", "Feedback you submit will appear here.", icon="")
        return

    for f in feedback_list:
        with st.container(border=True):
            rating_value = int(f.get("rating", 0) or 0)
            col1, col2 = st.columns([1, 4], vertical_alignment="top")
            with col1:
                st.markdown(f"**{rating_value}/5**")
                st.caption(RATING_LABELS.get(rating_value, ""))
            with col2:
                st.markdown(_rating_markdown(rating_value))
                comment_text = f.get("comment")
                if comment_text:
                    st.write(comment_text)
                else:
                    st.caption("No written comment.")
                appt_ref = appt_by_id.get(f.get("appointment_id"))
                if appt_ref:
                    st.caption(appointment_context(appt_ref, doctor_map))
                else:
                    st.caption(f"Visit ID: {short_id(f.get('appointment_id'))}")
                channel = f.get("feedback_channel", "form")
                st.caption(f"Via {channel} · Submitted {format_datetime(f.get('submitted_at') or f.get('created_at'))}")


if __name__ == "__main__":
    render()
