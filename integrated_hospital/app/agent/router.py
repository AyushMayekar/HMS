"""LangGraph routing functions.

Every decision is logged so the backend log shows the exact path the agent
took for a given request (intent -> rag/details/discovery -> confirmation).
"""
from app.utils.logger import log_info

from .state import AgentState


def _route(source: str, decision: str, **kwargs) -> str:
    log_info("agent:route", after=source, next=decision, **kwargs)
    return decision


def route_after_intent(state: AgentState):
    if state.get("intent") == "analytics_recommendation":
        return _route("understand_intent", "discover_data", intent=state.get("intent"))
    if state.get("needs_rag"):
        return _route("understand_intent", "retrieve_knowledge", intent=state.get("intent"))
    if state.get("needs_transaction"):
        return _route("understand_intent", "collect_details", intent=state.get("intent"))
    return _route("understand_intent", "generate_response", intent=state.get("intent"))


def route_after_rag(state: AgentState):
    if state.get("needs_transaction"):
        return _route("retrieve_knowledge", "collect_details", intent=state.get("intent"))
    return _route("retrieve_knowledge", "generate_response", intent=state.get("intent"))


def route_after_details(state: AgentState):
    if state.get("missing_fields"):
        return _route("collect_details", "collect_details", missing_detail=state.get("missing_fields"))
    if state.get("intent") in {
        "appointment_booking",
        "appointment_lookup",
        "appointment_reschedule",
        "appointment_cancellation",
    }:
        return _route("collect_details", "discover_data", intent=state.get("intent"))
    return _route("collect_details", "validate_transaction", intent=state.get("intent"))


def route_after_discovery(state: AgentState):
    result = state.get("tool_result", {})
    if state.get("intent") in {"appointment_lookup", "analytics_recommendation"}:
        return _route("discover_data", "generate_response", intent=state.get("intent"))
    if not result.get("success", False):
        return _route(
            "discover_data",
            "generate_response",
            intent=state.get("intent"),
            discovery_detail=result.get("message"),
        )
    return _route("discover_data", "validate_transaction", intent=state.get("intent"))


def route_after_validation(state: AgentState):
    if state.get("validation_errors"):
        return _route("validate_transaction", "collect_details", validation_detail=state.get("validation_errors"))
    if state.get("intent") in {
        "appointment_booking",
        "appointment_reschedule",
        "appointment_cancellation",
        "administrative_request",
    }:
        return _route("validate_transaction", "show_summary", intent=state.get("intent"))
    return _route("validate_transaction", "generate_response", intent=state.get("intent"))


def route_after_confirmation(state: AgentState):
    if state.get("confirmed"):
        return _route("confirmation", "execute_tool", confirmed=True)
    return _route("confirmation", "generate_response", confirmed=False)


def route_after_tool(state: AgentState):
    # Never loop into another confirmation after an attempted mutation. The
    # service result is authoritative; the user can start a fresh operation if
    # execution failed or the live slot changed.
    result = state.get("tool_result", {})
    return _route(
        "execute_tool",
        "generate_response",
        success=result.get("success"),
        tool_message=result.get("message"),
    )
