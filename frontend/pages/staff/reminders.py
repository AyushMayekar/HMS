"""
Staff Reminders page — the single staff reminder + no-show prediction workflow.

One page, one mental model:

    Reminders -> review the 24-hour window -> select rows -> Predict Selected
              -> review the refreshed scores -> send reminders

Prediction (``POST /predictions/no-show-batch``) and reminder sending
(``POST /staff/reminders/{appointment_id}``) stay separate backend actions —
this page only presents them together.

Opening the page NEVER runs inference: ``GET /predictions/no-show-eligible``
is read-only and simply reports whatever is already stored in
``prediction_logs``.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import loading
from frontend.components.analytics import (
    RISK_BAND_LEGEND,
    RISK_SCORE_LEGEND,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime
from frontend.api.staff_admin_services import StaffReminderService
from frontend.api.analytics_services import PredictionsService

REMINDER_TYPES = {
    "in_app": "In-app notification",
    "email": "Email",
}

REMINDER_HOURS_BEFORE = 24.0  # fixed 24-hour reminder model
DEFAULT_MESSAGE = "This is a friendly reminder about your upcoming appointment at Meridian Care."
MAX_MESSAGE_CHARS = 500

# Mirrors the backend cap (settings.noshow_max_batch); the API enforces the
# authoritative value and returns 422 if it is exceeded.
MAX_NO_SHOW_BATCH = 10

# Visits above this likelihood are listed first in the table.
FLAG_THRESHOLD = 0.30

FLASH_KEY = "staff_reminder_flash"
PREDICT_FLASH_KEY = "staff_reminders_predict_flash"

# st.dataframe widget state + the row order it was produced for. Row selection
# is index-based, so the selection is cleared whenever the row order changes
# (new appointment scored, one cancelled, ...) to keep indices honest.
SELECTION_KEY = "staff_reminders_selection"
TABLE_ORDER_KEY = "staff_reminders_table_order"


def _empty_selection() -> dict:
    """Fresh dataframe selection state (never share the inner dict)."""
    return {"selection": {"rows": [], "columns": [], "cells": []}}


def render():
    page_head(
        "Reminders",
        "Identify no-show risk, run the 24-hour prediction, then send reminders — one workflow.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Reminders"])

    service = StaffReminderService()
    predictions = PredictionsService()

    # ---------- Feedback from the previous action ----------
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)
    predict_flash = st.session_state.pop(PREDICT_FLASH_KEY, None)
    if predict_flash:
        if predict_flash.get("success"):
            st.success(predict_flash["success"])
        if predict_flash.get("error"):
            st.error(predict_flash["error"])

    # ---------- The 24-hour prediction window (read-only) ----------
    with loading("Loading appointments in the 24-hour window"):
        response = predictions.no_show_eligible()
    if not response.success:
        display_api_error(response)
        st.stop()

    data = response.data or {}
    appointments = data.get("appointments") or []
    max_batch = int(data.get("max_batch") or MAX_NO_SHOW_BATCH)
    tolerance = data.get("tolerance_minutes")
    window_start = str(data.get("window_start") or "")[:16].replace("T", " ")
    window_end = str(data.get("window_end") or "")[:16].replace("T", " ")

    section_title(
        "Upcoming visits and their no-show predictions",
        "Appointments about 24 hours away, with everything already known about their "
        "no-show risk. Select rows in the table to predict or to send a reminder.",
    )
    if tolerance is None:
        tolerance_text = ""
    elif tolerance % 60 == 0:
        tolerance_text = f"±{int(tolerance) // 60} h"
    else:
        tolerance_text = f"±{int(tolerance)} min"
    st.info(
        "Nothing is predicted while this page loads — scores are only produced when you "
        "press **Predict Selected**. "
        f"Window: {window_start} – {window_end} UTC ({tolerance_text}); "
        f"up to {max_batch} appointments per action."
    )

    if not appointments:
        empty_state(
            "No appointments fall inside the 24-hour scoring window right now.",
            "Appointments become eligible once they are about 24 hours away — "
            "refresh this page in a few minutes.",
        )
        return

    rows, row_ids = build_table_rows(appointments)
    has_model_scores = any(a.get("no_show_probability") is not None for a in appointments)

    # Row selection is index-based: clear it whenever the displayed order changes.
    if st.session_state.get(TABLE_ORDER_KEY) != row_ids:
        st.session_state[TABLE_ORDER_KEY] = row_ids
        st.session_state[SELECTION_KEY] = _empty_selection()

    if st.button(
        f"Select visible (up to {max_batch})",
        key="rem_select_visible",
        icon=":material/checklist:",
        help=f"Selects the first {max_batch} rows shown in the table.",
    ):
        st.session_state[SELECTION_KEY] = {
            "selection": {"rows": list(range(min(max_batch, len(rows)))), "columns": [], "cells": []}
        }

    selected_rows = render_appointment_table(rows, has_model_scores=has_model_scores)
    selected_ids = [row_ids[i] for i in selected_rows if 0 <= i < len(row_ids)]
    selected_count = len(selected_ids)
    over_limit = selected_count > max_batch

    # One selection count, shared by both actions below.
    st.caption(f"{selected_count} / {max_batch} selected")

    action_col, reminder_col = st.columns([1, 1], gap="large")

    # ---------- Prediction (manual, capped, never on load) ----------
    with action_col:
        render_predict_action(
            predictions,
            selected_ids,
            max_batch=max_batch,
            over_limit=over_limit,
        )

    # ---------- Reminders (separate action) ----------
    with reminder_col:
        render_reminder_action(
            service,
            selected_ids,
            appointments=appointments,
        )


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def build_table_rows(appointments: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Display-ready table rows plus the appointment id for each row, in the
    same order. Risky (predicted) visits are listed first, then by time.
    """
    entries: list[tuple[bool, str, dict, str]] = []
    for appt in appointments:
        prediction = appt.get("stored_prediction")
        probability = appt.get("no_show_probability")
        level = _normalise_level(appt.get("risk_level"))
        predicted = appt.get("predicted_no_show")
        last_scored_at = appt.get("last_scored_at")

        if prediction is None:
            prediction_value = "Not scored"
        else:
            prediction_value = _prediction_percentage(prediction)
        flagged = bool(predicted) or (probability is not None and _above_threshold(probability))
        scheduled = str(appt.get("scheduled_start") or "")

        row = {
            "Patient": appt.get("patient_name") or "Patient name not available",
            "Department": appt.get("department_name") or "Department not set",
            "Doctor": appt.get("doctor_name") or "—",
            "Appointment": format_datetime(appt.get("scheduled_start")),
            "No-show prediction": prediction_value,
            "Risk level": level or "—",
            "Predicted no-show": (
                "Yes" if predicted is True else "No" if predicted is False else "—"
            ),
            "Last scored": format_datetime(last_scored_at) if last_scored_at else "—",
            "Reminder": _reminder_text(appt),
        }
        entries.append((flagged, scheduled, row, str(appt.get("appointment_id") or "")))

    entries.sort(key=lambda entry: (not entry[0], entry[1]))
    return [e[2] for e in entries], [e[3] for e in entries]


def render_appointment_table(rows: list[dict], *, has_model_scores: bool) -> list[int]:
    """Selectable appointment table; returns the selected row indices."""
    if any(r["No-show prediction"] != "Not scored yet" for r in rows):
        st.caption(RISK_BAND_LEGEND if has_model_scores else RISK_SCORE_LEGEND)
    else:
        st.caption("Nothing in this window has been scored yet.")

    event = st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        key=SELECTION_KEY,
        selection_mode="multi-row",
        on_select="rerun",
        column_config={
            "Patient": st.column_config.TextColumn("Patient", width="medium"),
            "Department": st.column_config.TextColumn("Department", width="small"),
            "Doctor": st.column_config.TextColumn("Doctor", width="small"),
            "Appointment": st.column_config.TextColumn("Appointment", width="medium"),
            "No-show prediction": st.column_config.TextColumn("No-show prediction", width="small"),
            "Risk level": st.column_config.TextColumn("Risk level", width="small"),
            "Predicted no-show": st.column_config.TextColumn("Predicted no-show", width="small"),
            "Last scored": st.column_config.TextColumn("Last scored", width="medium"),
            "Reminder": st.column_config.TextColumn("Reminder", width="medium"),
        },
    )
    selection = getattr(event, "selection", None)
    if selection is None:
        return []
    try:
        return [int(i) for i in selection.rows]
    except (TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def render_predict_action(predictions, selected_ids: list[str], *, max_batch: int, over_limit: bool) -> None:
    """The single primary prediction action."""
    section_title(
        "Predict",
        "Score the selected appointments — nothing runs automatically and there is no "
        "Predict All; the backend caps every action at "
        f"{max_batch} appointments.",
    )

    if over_limit:
        st.warning(
            f"A maximum of {max_batch} appointments can be predicted at once. "
            f"You have selected {len(selected_ids)}. Deselect "
            f"{len(selected_ids) - max_batch} appointment(s) to continue."
        )

    if not st.button(
        "Predict Selected",
        type="primary",
        width="stretch",
        key="rem_predict_selected",
        disabled=(not selected_ids or over_limit),
    ):
        return

    with loading(f"Running no-show prediction for {len(selected_ids)} appointment(s)"):
        result = predictions.no_show_batch(selected_ids)

    if not result.success:
        st.session_state[PREDICT_FLASH_KEY] = {"error": _response_error(result)}
        _clear_selection()
        st.rerun()

    payload = result.data or {}
    executed = payload.get("executed") or []
    failed = payload.get("failed") or []

    success = f"Scored {len(executed)} appointment(s) — the table now shows the new predictions."
    if not executed and not failed:
        success = "No predictions were returned for the selected appointments."
    error = None
    if failed:
        error = "Could not predict: " + "; ".join(
            f"{f.get('appointment_id')}: {f.get('error')}" for f in failed
        )

    st.session_state[PREDICT_FLASH_KEY] = {"success": success, "error": error}
    _clear_selection()
    st.rerun()


def render_reminder_action(service, selected_ids: list[str], *, appointments: list[dict]) -> None:
    """Sending reminders — a separate action, never triggered by prediction."""
    section_title("Send reminders", "Review the scores above, then remind the selected visits.")

    c1, c2 = st.columns([1, 2])
    with c1:
        channel = st.selectbox(
            "Reminder channel",
            list(REMINDER_TYPES.keys()),
            format_func=lambda t: REMINDER_TYPES[t],
            key="rem_channel",
        )
    with c2:
        message = st.text_input(
            "Message",
            value=DEFAULT_MESSAGE,
            max_chars=MAX_MESSAGE_CHARS,
            key="rem_message",
            help=f"Sent to the patient with the reminder (maximum {MAX_MESSAGE_CHARS} characters).",
        )
    message = (message or "").strip()
    st.caption("Timing: reminders go out 24 hours before the scheduled appointment.")

    can_send = bool(message) and bool(selected_ids)
    if not selected_ids:
        st.caption("Select row(s) in the table above to send a reminder.")
    elif not message:
        st.caption("Enter a reminder message before sending.")

    if not st.button(
        f"Send reminder to {len(selected_ids)} selected visit(s)" if selected_ids else "Send reminder",
        type="primary",
        width="stretch",
        key="rem_send_selected",
        disabled=not can_send,
    ):
        return

    by_id = {str(a.get("appointment_id")): a for a in appointments}
    sent, failed = 0, 0
    with loading(f"Sending {len(selected_ids)} reminder(s)"):
        for appointment_id in selected_ids:
            if appointment_id not in by_id:
                failed += 1
                continue
            result = service.create(
                appointment_id=appointment_id,
                reminder_type=channel,
                hours_before_appointment=REMINDER_HOURS_BEFORE,
                message=message,
            )
            if result.success:
                sent += 1
            else:
                failed += 1

    st.session_state[FLASH_KEY] = (
        f"{sent} reminder(s) sent"
        + (f", {failed} could not be sent." if failed else ".")
        + f" ({REMINDER_TYPES[channel].lower()}, {REMINDER_HOURS_BEFORE:.0f}-hour reminder)"
    )
    _clear_selection()
    st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_selection() -> None:
    """
    Invalidate the selection so stale row indices never survive a data change.

    Only the *order marker* is touched here: these helpers run from button
    handlers, which are evaluated AFTER ``st.dataframe`` has already been
    instantiated in the same run, so the widget key itself must not be
    written at that point. The order check at the top of the next run then
    performs the actual reset.
    """
    st.session_state[TABLE_ORDER_KEY] = None

def _prediction_percentage(prediction: dict) -> str:
    """
    Display only the no-show probability.
    
    Risk category is shown separately in the Risk level column.
    Handles both ML probability payloads and fallback payloads.
    """

    probability = prediction.get("no_show_probability")

    if probability is None:
        return "—"

    try:
        probability = float(probability)
    except (TypeError, ValueError):
        return "—"

    # Convert decimal probability (0.72) into percentage (72%)
    if probability <= 1:
        probability *= 100

    return f"{probability:.1f}%"

def _normalise_level(value) -> str | None:
    level = str(value or "").strip().lower()
    return level.capitalize() if level in ("high", "medium", "low") else None


def _above_threshold(probability) -> bool:
    try:
        value = float(probability)
    except (TypeError, ValueError):
        return False
    if value > 1.0:
        value = value / 100.0
    return value > FLAG_THRESHOLD


def _reminder_text(appt: dict) -> str:
    when = appt.get("reminder_sent_at")
    reminder_id = appt.get("reminder_id")
    if reminder_id or when:
        parts = ["Sent"]
        if when:
            parts.append(str(format_datetime(when)))
        reminder_type = REMINDER_TYPES.get(appt.get("reminder_type") or "", appt.get("reminder_type"))
        if reminder_type:
            parts.append(str(reminder_type))
        return " · ".join(parts)
    if appt.get("reminder_sent"):
        return "Sent"
    return "Not sent"


def _response_error(response) -> str:
    message = getattr(response, "error_message", None)
    code = getattr(response, "error_code", None)
    if message and code:
        return f"[{code}] {message}"
    return str(message or "Prediction request failed.")


if __name__ == "__main__":
    render()
