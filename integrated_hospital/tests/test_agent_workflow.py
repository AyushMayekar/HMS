"""Focused regression tests for the agent workflow stabilisation fixes.

These tests drive the REAL compiled LangGraph graph with deterministic
stand-ins for the LLM classifier/extractor and for the discovery/mutation
services. They verify routing, interrupt, validation and state-lifecycle
behaviour without any network or database access, and without touching the
production data model.
"""
from __future__ import annotations

import pathlib
import sys
import types
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langgraph.types import Command

from app.agent import nodes
from app.agent.agent import agent
from app.agent.context import AgentContext
from app.agent.intents import (
    INTENT_ROUTING,
    SUPPORTED_INTENTS,
    detect_intent_escape,
    normalize_intent,
    routing_for,
)
from app.agent.prompts import EXTRACTION_PROMPT
from app.services.admin_request_service import create_admin_request
from app.utils.exceptions import InvalidOperationError
from app.utils.helpers import TRANSACTION_SPECS
from app.utils.validators import (
    ADMIN_REQUEST_CATEGORIES,
    normalize_admin_category,
    validate_admin_request,
)


# ============================================================
# Fixtures (test-only rows; never written to the database)
# ============================================================

DEPARTMENTS = [
    {"department_id": "dept-cardiology", "name": "Cardiology", "status": "active"},
    {"department_id": "dept-dermatology", "name": "Dermatology", "status": "active"},
]

DOCTORS = {
    "dept-cardiology": [
        {"doctor_id": "doc-1", "full_name": "Dr. Mehta", "status": "active"},
        {"doctor_id": "doc-2", "full_name": "Dr. Rao", "status": "active"},
    ],
    "dept-dermatology": [
        {"doctor_id": "doc-3", "full_name": "Dr. Iyer", "status": "active"},
    ],
}


def _slot(slot_id: str, doctor_id: str, slot_date: str, start: str) -> dict:
    hour, minute = (int(part) for part in start.split(":"))
    end = f"{hour + 1:02d}:{minute:02d}:00"
    return {
        "availability_id": slot_id,
        "doctor_id": doctor_id,
        "slot_date": slot_date,
        "start_time": f"{start}:00",
        "end_time": end,
        "status": "available",
        "booked_count": 0,
        "slot_capacity": 3,
    }


# Dr. Mehta deliberately has NO slot on 2026-10-05 (no-availability test).
SLOTS = {
    "2026-10-06": [
        _slot("slot-a", "doc-1", "2026-10-06", "10:00"),
        _slot("slot-b", "doc-1", "2026-10-06", "11:00"),
    ],
    "2026-10-07": [
        _slot("slot-c", "doc-1", "2026-10-07", "09:30"),
    ],
}


def fake_discover_departments():
    return [dict(row) for row in DEPARTMENTS]


def fake_discover_doctors(department_id: str):
    return [dict(row) for row in DOCTORS.get(department_id, [])]


def fake_discover_availability(*, doctor_id: str, slot_date: str | None):
    if slot_date is None:
        rows = [
            dict(row)
            for day_rows in SLOTS.values()
            for row in day_rows
            if row["doctor_id"] == doctor_id
        ]
        rows.sort(key=lambda row: (row["slot_date"], row["start_time"]))
        return rows
    return [
        dict(row)
        for row in SLOTS.get(slot_date, [])
        if row["doctor_id"] == doctor_id
    ]


def fake_execute_book_appointment(**kwargs):
    return {"appointment_id": "appt-created", **kwargs}


def fake_execute_admin_request(**kwargs):
    return {"request_id": "req-created", **kwargs}


def fake_retrieve_knowledge_context(**kwargs):
    return {"results": [], "context": ""}


# ============================================================
# Deterministic LLM stand-ins
# ============================================================

def _segment(prompt: str, marker: str) -> str:
    if marker in prompt:
        return prompt.rsplit(marker, 1)[1].strip()
    return prompt


def _current_message(prompt: str) -> str:
    if "Current message:" in prompt:
        return _segment(prompt, "Current message:")
    return _segment(prompt, "User message:")


def classify(message: str) -> str:
    text = message.lower()
    if "opd" in text or "visiting hours" in text or "timings" in text:
        return "hospital_information"
    if "cancel" in text:
        return "appointment_cancellation"
    if "charged twice" in text or "raise a request" in text:
        return "administrative_request"
    if "my appointments" in text:
        return "appointment_lookup"
    if "book" in text or "appointment" in text:
        return "appointment_booking"
    return "general_conversation"


class FakeIntentLLM:
    def invoke(self, prompt: str):
        message = _segment(prompt, "User message:")
        return nodes.IntentClassification(intent=classify(message), analytics_type=None)


class FakeExtractLLM:
    def __init__(self, mapper):
        self.mapper = mapper

    def invoke(self, prompt: str):
        values = self.mapper(_current_message(prompt)) or {}
        return types.SimpleNamespace(model_dump=lambda exclude_none=True: dict(values))


class FakeResponseLLM:
    def invoke(self, prompt: str):
        return types.SimpleNamespace(content="LLM_REPLY")


def appointment_extract(message: str) -> dict:
    text = message.lower()
    values: dict = {}
    if "cardiology" in text:
        values["department"] = "Cardiology"
    if "mehta" in text:
        values["doctor"] = "Dr. Mehta"
    if "2026-10-05" in text:
        values["appointment_date"] = "2026-10-05"
    elif "2026-10-06" in text:
        values["appointment_date"] = "2026-10-06"
    if " at 11:00" in text:
        values["appointment_time"] = "11:00"
    elif " at 15:00" in text:
        values["appointment_time"] = "15:00"
    elif " at 7 pm" in text:
        values["appointment_time"] = "7 PM"
    return values


def admin_extract(message: str) -> dict:
    text = message.lower()
    values: dict = {}
    if "weird_category" in text:
        values["category"] = "weird_category"
        values["description"] = "There is a problem with my recent visit"
    elif "refund" in text:
        values["category"] = "refund"
        values["description"] = "I was charged twice for my appointment"
    elif "charged twice" in text:
        values["category"] = "refund"
        values["description"] = "I was charged twice for my appointment"
    elif "raise a request" in text:
        values["category"] = "general_support"
        values["description"] = "I need help with an administrative matter"
    return values


@pytest.fixture(autouse=True)
def agent_env(monkeypatch):
    monkeypatch.setattr(nodes, "intent_llm", FakeIntentLLM())
    monkeypatch.setattr(nodes, "appointment_llm", FakeExtractLLM(appointment_extract))
    monkeypatch.setattr(nodes, "admin_request_llm", FakeExtractLLM(admin_extract))
    monkeypatch.setattr(nodes, "llm", FakeResponseLLM())
    monkeypatch.setattr(nodes, "discover_departments", fake_discover_departments)
    monkeypatch.setattr(nodes, "discover_doctors", fake_discover_doctors)
    monkeypatch.setattr(nodes, "discover_availability", fake_discover_availability)
    monkeypatch.setattr(nodes, "execute_book_appointment", fake_execute_book_appointment)
    monkeypatch.setattr(nodes, "execute_admin_request", fake_execute_admin_request)
    monkeypatch.setattr(nodes, "retrieve_knowledge_context", fake_retrieve_knowledge_context)
    yield


def run_turn(message: str, *, thread_id: str | None = None, resume: bool = False):
    thread = thread_id or f"test-{uuid.uuid4().hex[:8]}"
    context = AgentContext(
        supabase=None,
        user_id="patient-test",
        role="patient",
        profile={"role": "patient"},
    )
    step = {"user_input": message, "messages": [{"role": "user", "content": message}]}
    if resume:
        step = Command(resume=message, update=step)
    result = agent.invoke(
        step,
        config={"configurable": {"thread_id": thread}},
        context=context,
    )
    return thread, result


def interrupt_of(result) -> dict | None:
    items = result.get("__interrupt__") or ()
    if not items:
        return None
    value = items[0].value
    return value if isinstance(value, dict) else {"message": str(value)}


def option_labels(interrupt: dict) -> list[str]:
    return [str(item.get("label")) for item in interrupt.get("options") or []]


# ============================================================
# FIX #1 / #3 — progressive booking + availability safety
# ============================================================

def test_booking_spec_no_longer_blocks_on_all_details():
    spec = TRANSACTION_SPECS["appointment_booking"]
    assert spec["required_fields"] == ()
    # Volunteered details are still extracted (they feed discovery).
    assert "department" in spec["extract_fields"]
    assert "appointment_time" in spec["extract_fields"]


def test_minimal_booking_starts_with_department_catalog():
    _, result = run_turn("I want to book an appointment.")
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "selection"
    assert pending["selection_type"] == "department"
    assert "Cardiology" in option_labels(pending)
    assert "Dermatology" in option_labels(pending)


def test_supplied_department_skips_department_step():
    _, result = run_turn("I want a cardiology appointment.")
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "selection"
    assert pending["selection_type"] == "doctor"
    assert "Dr. Mehta" in option_labels(pending)


def test_unknown_department_reopens_real_catalog():
    _, result = run_turn("I want a cardiology appointment.")
    thread = _
    # The department came from the message, so only the doctor is asked; the
    # catalog is used again when a department cannot be resolved.
    pending = interrupt_of(result)
    assert pending["selection_type"] == "doctor"


def test_supplied_date_and_time_hit_real_availability():
    _, result = run_turn(
        "I want a cardiology appointment with Dr. Mehta on 2026-10-06 at 11:00"
    )
    pending = interrupt_of(result)
    assert pending is not None
    # Exact real slot -> straight to confirmation, no further questions.
    assert pending["type"] == "confirmation"
    values = {item["field"]: item["value"] for item in pending["summary"]}
    assert values["appointment_date"] == "2026-10-06"
    assert values["appointment_time"] == "11:00"


def test_unmatched_time_shows_real_slots_for_that_date():
    _, result = run_turn(
        "I want a cardiology appointment with Dr. Mehta on 2026-10-06 at 15:00"
    )
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "selection"
    assert pending["selection_type"] == "availability"
    labels = option_labels(pending)
    assert len(labels) == 2
    assert all("2026-10-06" in label for label in labels)


def test_no_availability_offers_real_alternative_slots():
    _, result = run_turn("I want a cardiology appointment with Dr. Mehta on 2026-10-05")
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "selection"
    assert pending["selection_type"] == "availability"
    labels = option_labels(pending)
    assert labels, "alternatives must come from real availability rows"
    assert all("2026-10-05" not in label for label in labels)
    assert any("2026-10-06" in label for label in labels)
    assert "No available slots were found" in pending["message"]


def test_booking_requires_resolved_availability():
    update = nodes.validate_transaction({
        "intent": "appointment_booking",
        "transaction_data": {
            "department": "Cardiology",
            "appointment_date": "2026-10-06",
            "appointment_time": "10:00",
        },
    })
    assert update["validation_errors"]
    assert not update["invalid_fields"]


def test_unresolved_menu_answer_asks_again_without_crashing():
    """An unrecognised menu answer must re-ask on a fresh graph execution.

    Interrupting twice inside one node execution leaves LangGraph's input
    writes uncommitted, which used to make the *next* resume fail with
    InvalidUpdateError instead of being processed.
    """
    thread, result = run_turn("I want a cardiology appointment.")
    assert interrupt_of(result)["selection_type"] == "doctor"

    _, result = run_turn("Dr. Nobody", thread_id=thread, resume=True)
    pending = interrupt_of(result)
    assert pending is not None, "the doctor menu must be shown again"
    assert pending["selection_type"] == "doctor"

    _, result = run_turn("Dr. Mehta", thread_id=thread, resume=True)
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["selection_type"] == "availability"


def test_booking_reaches_execution_only_after_confirmation():
    thread, result = run_turn("I want a cardiology appointment.")
    pending = interrupt_of(result)
    assert pending["selection_type"] == "doctor"

    _, result = run_turn("Dr. Mehta", thread_id=thread, resume=True)
    pending = interrupt_of(result)
    assert pending["selection_type"] == "availability"

    _, result = run_turn("1", thread_id=thread, resume=True)
    pending = interrupt_of(result)
    assert pending["type"] == "confirmation"

    # A non-confirmation answer must not execute anything.
    _, result = run_turn("no", thread_id=thread, resume=True)
    assert result["final_response"] == (
        "No transaction was performed because you did not confirm."
    )


# ============================================================
# FIX #4 / #5 — controlled intent + deterministic routing
# ============================================================

def test_intent_set_is_closed():
    assert set(SUPPORTED_INTENTS) == set(INTENT_ROUTING)


def test_routing_is_derived_from_intent_not_llm_flags():
    expected = {
        "general_conversation": (False, False),
        "hospital_information": (True, False),
        "appointment_booking": (False, True),
        "appointment_lookup": (False, True),
        "appointment_reschedule": (False, True),
        "appointment_cancellation": (False, True),
        "administrative_request": (False, True),
        "analytics_recommendation": (False, True),
        "billing_information": (True, False),
        "unsafe_clinical_request": (False, False),
    }
    for intent, (needs_rag, needs_transaction) in expected.items():
        route = routing_for(intent)
        assert route["needs_rag"] is needs_rag, intent
        assert route["needs_transaction"] is needs_transaction, intent

    # The classifier schema no longer carries routing booleans.
    fields = nodes.IntentClassification.model_fields
    assert "needs_rag" not in fields
    assert "needs_transaction" not in fields
    assert "intent" in fields


def test_invalid_intent_falls_back_safely():
    assert normalize_intent("appointment_boking") == ("general_conversation", True)
    assert normalize_intent(None) == ("general_conversation", True)
    assert normalize_intent("Appointment Booking") == ("appointment_booking", False)
    assert normalize_intent("appointment-booking") == ("appointment_booking", False)


def test_invalid_intent_routes_to_conversational_fallback(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "intent_llm",
        types.SimpleNamespace(
            invoke=lambda prompt: nodes.IntentClassification(intent="totally_made_up")
        ),
    )
    _, result = run_turn("hello there")
    assert result["intent"] == "general_conversation"
    assert result["intent_fallback"] is True
    assert result["needs_transaction"] is False
    assert result["final_response"]


# ============================================================
# FIX #11 — interrupt escape
# ============================================================

def test_escape_detection_is_precise():
    assert detect_intent_escape("Actually, what are your OPD timings?") == "hospital_information"
    assert detect_intent_escape("Please cancel my appointment") == "appointment_cancellation"
    assert detect_intent_escape("3") is None
    assert detect_intent_escape("Cardiology") is None
    assert detect_intent_escape("yes") is None
    assert detect_intent_escape("Dr. Mehta") is None
    assert detect_intent_escape(None) is None


def test_pending_selection_escapes_on_new_intent():
    thread, result = run_turn("I want a cardiology appointment.")
    assert interrupt_of(result)["selection_type"] == "doctor"

    _, result = run_turn(
        "Actually, what are your OPD timings?", thread_id=thread, resume=True
    )
    assert "__interrupt__" not in result or not result.get("__interrupt__")
    assert result["intent"] == "hospital_information"
    # No usable knowledge retrieved -> safe answer instead of a guess.
    assert "knowledge base" in result["final_response"]


# ============================================================
# FIX #6 / #7 / #8 — admin request categories
# ============================================================

def test_canonical_admin_categories_are_unchanged():
    assert ADMIN_REQUEST_CATEGORIES == (
        "refund",
        "appointment_issue",
        "account_issue",
        "admin_requirement",
        "general_support",
    )


def test_extraction_prompt_lists_canonical_categories():
    prompt = EXTRACTION_PROMPT.format(
        intent="administrative_request",
        current_datetime="now",
        existing_data={},
        extract_fields=("category", "description"),
        missing_fields=("category", "description"),
        admin_categories=", ".join(ADMIN_REQUEST_CATEGORIES),
        user_input="I was charged twice for my appointment",
    )
    for category in ADMIN_REQUEST_CATEGORIES:
        assert category in prompt
    assert "Never return a value outside that list" in prompt


def test_natural_language_maps_to_canonical_category():
    assert normalize_admin_category("charged twice") == "refund"
    assert normalize_admin_category("charged_twice") == "refund"
    assert normalize_admin_category("I was charged twice for my appointment.") is None
    assert normalize_admin_category("Refund") == "refund"
    assert normalize_admin_category("billing_issue") == "refund"
    assert normalize_admin_category("billing_dispute") == "refund"
    assert normalize_admin_category("medical_records") == "admin_requirement"
    assert normalize_admin_category("not_a_real_category") is None


def test_validate_admin_request_rejects_unknown_category():
    result = validate_admin_request("billing_issue_not_real", "A long enough description")
    assert not result["valid"]
    assert result["field"] == "category"
    assert "refund" in result["message"]


def test_invalid_admin_category_asks_instead_of_looping():
    thread, result = run_turn("Please raise a request about weird_category now")
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "collect_details"
    assert "Invalid category" in pending["message"]
    for category in ADMIN_REQUEST_CATEGORIES:
        assert category in pending["message"]

    # A canonical answer completes the workflow.
    _, result = run_turn("refund", thread_id=thread, resume=True)
    pending = interrupt_of(result)
    assert pending is not None
    assert pending["type"] == "confirmation"
    summary = {item["field"]: item["value"] for item in pending["summary"]}
    assert summary["category"] == "refund"


def test_service_rejects_invalid_category_outside_the_agent():
    with pytest.raises(InvalidOperationError) as exc:
        create_admin_request(
            patient_id="patient-test",
            category="billing_issue_invented",
            description="A perfectly valid description",
        )
    assert "refund" in str(exc.value)


# ============================================================
# FIX #9 / #10 — state lifecycle
# ============================================================

def test_turn_scoped_state_is_always_cleared():
    state = {
        "user_input": "hello",
        "intent": "appointment_booking",
        "retrieved_context": "stale knowledge",
        "tool_result": {"success": True, "data": {"appointment_id": "old"}},
        "summary": [{"field": "department", "label": "Department", "value": "Cardiology"}],
        "confirmed": True,
        "confirmation_response": "yes",
        "validation_errors": ["stale"],
        "invalid_fields": ["stale"],
        "missing_fields": ["stale"],
        "transaction_data": {"department": "Cardiology"},
        "messages": [],
    }
    update = nodes.understand_intent(state)
    assert update["retrieved_context"] == ""
    assert update["tool_result"] == {}
    assert update["summary"] == []
    assert update["confirmed"] is False
    assert update["validation_errors"] == []
    assert update["invalid_fields"] == []
    assert update["missing_fields"] == []
    # Same intent but the previous transaction already executed -> reset.
    assert update["transaction_data"] == {}


def test_interrupt_resume_preserves_current_transaction_data():
    state = {
        "user_input": "book cardiology with Dr. Mehta",
        "intent": "appointment_booking",
        "transaction_data": {"department": "Cardiology"},
        "tool_result": {"success": True, "action": "booking_discovery"},
        "confirmed": False,
    }
    update = nodes.understand_intent(state)
    # Continuation of the same, unfinished transaction keeps collected details.
    assert update["transaction_data"] == {"department": "Cardiology"}


def test_new_transaction_clears_previous_details():
    state = {
        "user_input": "book dermatology",
        "intent": "appointment_cancellation",
        "transaction_data": {"department": "Cardiology", "appointment_date": "2026-10-06"},
        "tool_result": {"success": True, "action": "cancellation_discovery"},
        "confirmed": False,
    }
    update = nodes.understand_intent(state)
    assert update["transaction_data"] == {}


def test_second_booking_does_not_reuse_first_booking():
    thread, result = run_turn("I want a cardiology appointment.")
    assert interrupt_of(result)["selection_type"] == "doctor"
    _, result = run_turn("Dr. Mehta", thread_id=thread, resume=True)
    assert interrupt_of(result)["selection_type"] == "availability"
    _, result = run_turn("1", thread_id=thread, resume=True)
    assert interrupt_of(result)["type"] == "confirmation"
    _, result = run_turn("yes", thread_id=thread, resume=True)
    assert result["final_response"] == "Your appointment was booked successfully."

    _, result = run_turn("I want to book another appointment.", thread_id=thread)
    pending = interrupt_of(result)
    assert pending["type"] == "selection"
    # The completed booking's department/doctor/slot must not be reused.
    assert pending["selection_type"] == "department"


# ============================================================
# RAG safety
# ============================================================

def test_rag_without_knowledge_does_not_guess(monkeypatch):
    monkeypatch.setattr(
        nodes, "retrieve_knowledge_context", fake_retrieve_knowledge_context
    )
    _, result = run_turn("What are your OPD timings?")
    assert result["intent"] == "hospital_information"
    assert "knowledge base" in result["final_response"]
    assert result["final_response"] != "LLM_REPLY"


def test_rag_with_knowledge_uses_retrieved_context(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "retrieve_knowledge_context",
        lambda **kwargs: {
            "results": [{"title": "OPD"}],
            "context": "[Source 1: OPD]\nOPD timings are 09:00-17:00.",
        },
    )
    _, result = run_turn("What are your OPD timings?")
    assert result["final_response"] == "LLM_REPLY"
