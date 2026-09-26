"""Controlled intent vocabulary and intent-derived routing.

The LLM only *proposes* an intent. Every routing decision the graph makes
(needs_rag / needs_transaction) is derived here from that single controlled
value, so the model can no longer emit contradictory routing flags such as
``appointment_booking + needs_rag=True``.

This module also holds the small, deterministic "escape" check used when a
pending interrupt receives a message that clearly belongs to a different
supported intent ("Actually, what are your OPD timings?").
"""
from __future__ import annotations

from typing import Any

# The complete, closed set of intents the agent understands. Never extend this
# list silently: the classifier, the router and the transaction specs must all
# stay in sync.
SUPPORTED_INTENTS: tuple[str, ...] = (
    "general_conversation",
    "hospital_information",
    "appointment_booking",
    "appointment_lookup",
    "appointment_reschedule",
    "appointment_cancellation",
    "administrative_request",
    "analytics_recommendation",
    "billing_information",
    "unsafe_clinical_request",
)

# Single source of truth for graph routing, derived purely from the intent.
#   needs_rag         -> run knowledge retrieval before responding
#   needs_transaction -> run the collect/discover/validate/confirm workflow
INTENT_ROUTING: dict[str, dict[str, bool]] = {
    "general_conversation": {"needs_rag": False, "needs_transaction": False},
    "hospital_information": {"needs_rag": True, "needs_transaction": False},
    "appointment_booking": {"needs_rag": False, "needs_transaction": True},
    "appointment_lookup": {"needs_rag": False, "needs_transaction": True},
    "appointment_reschedule": {"needs_rag": False, "needs_transaction": True},
    "appointment_cancellation": {"needs_rag": False, "needs_transaction": True},
    "administrative_request": {"needs_rag": False, "needs_transaction": True},
    "analytics_recommendation": {"needs_rag": False, "needs_transaction": True},
    "billing_information": {"needs_rag": True, "needs_transaction": False},
    "unsafe_clinical_request": {"needs_rag": False, "needs_transaction": False},
}

# Used whenever the classifier returns something outside SUPPORTED_INTENTS:
# a safe conversational turn instead of a ValueError -> API failure.
FALLBACK_INTENT = "general_conversation"


def routing_for(intent: str | None) -> dict[str, bool]:
    """Routing flags for a controlled intent (falls back to the safe intent)."""
    return INTENT_ROUTING.get(intent or "", INTENT_ROUTING[FALLBACK_INTENT])


def normalize_intent(value: Any) -> tuple[str, bool]:
    """Map a raw classifier output onto the controlled intent set.

    Returns ``(intent, used_fallback)``. Near-matches are normalised
    (case/spacing/dashes) but never fuzzy-matched into an invented label:
    an unrecognised value becomes ``general_conversation`` so the graph can
    ask a clarifying question instead of crashing.
    """
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    text = "_".join(part for part in text.split("_") if part)
    if text in INTENT_ROUTING:
        return text, False
    return FALLBACK_INTENT, True


def routing_for_intent(value: Any) -> tuple[str, bool, bool]:
    """Convenience: ``(intent, needs_rag, needs_transaction)`` for a raw value."""
    intent, used_fallback = normalize_intent(value)
    route = routing_for(intent)
    return intent, route["needs_rag"], route["needs_transaction"]


# ---------------------------------------------------------------------------
# Interrupt escape: a pending interrupt assumes the next message answers its
# question. A clearly different supported intent must be able to leave the
# pending transaction instead of being re-prompted forever.
#
# Patterns are deliberately high-precision phrases (not single ambiguous
# words), checked in order, so an ordinary menu answer ("3", "Cardiology",
# "yes") never triggers an escape.
# ---------------------------------------------------------------------------
_INTENT_ESCAPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "appointment_cancellation",
        (
            "cancel my appointment",
            "cancel my booking",
            "cancel appointment",
            "i want to cancel",
            "i'd like to cancel",
            "need to cancel",
            "cancel it",
        ),
    ),
    (
        "appointment_reschedule",
        (
            "reschedule",
            "move my appointment",
            "change my appointment",
            "change the appointment",
            "book a different",
            "another slot",
            "different time",
        ),
    ),
    (
        "appointment_lookup",
        (
            "show my appointments",
            "list my appointments",
            "my appointments",
            "upcoming appointments",
            "appointment status",
            "do i have any appointment",
        ),
    ),
    (
        "appointment_booking",
        (
            "book an appointment",
            "book a new appointment",
            "book appointment",
            "i want to book",
            "new booking",
        ),
    ),
    (
        "administrative_request",
        (
            "raise a request",
            "raise an admin",
            "raise a support",
            "raise a refund",
            "create a request",
            "submit a request",
            "i want to request",
            "file a complaint",
        ),
    ),
    (
        "hospital_information",
        (
            "opd timing",
            "opd hour",
            "visiting hours",
            "opening hours",
            "hospital timing",
            "department hours",
            "what are the timings",
            "what are your timings",
            "what are your hours",
            "where are you located",
            "parking",
        ),
    ),
    (
        "billing_information",
        (
            "billing policy",
            "refund policy",
            "how much does it cost",
            "consultation charge",
        ),
    ),
    (
        "unsafe_clinical_request",
        (
            "what medicine",
            "which medicine",
            "should i take",
            "what should i take",
            "diagnose",
            "prescribe",
        ),
    ),
)


def detect_intent_escape(answer: Any) -> str | None:
    """Return a supported intent when the reply clearly starts a new topic."""
    if isinstance(answer, dict):
        parts = [
            str(answer.get(key) or "")
            for key in ("answer", "selected", "value", "message", "label")
        ]
        text = " ".join(part for part in parts if part)
    elif answer is None:
        return None
    else:
        text = str(answer)

    text = " ".join(text.strip().lower().split())
    if not text:
        return None

    for intent, patterns in _INTENT_ESCAPE_PATTERNS:
        for pattern in patterns:
            if pattern in text:
                return intent
    return None
