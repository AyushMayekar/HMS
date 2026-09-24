"""
Agent state definition.
TypedDict that flows through the LangGraph workflow.
"""
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """State that flows through the LangGraph workflow."""

    user_input: str

    # Rolling conversation history: [{"role": "user"|"assistant", "content": str}].
    # The API writes user turns, generate_response writes assistant turns.
    messages: list[dict[str, str]]

    intent: str
    needs_rag: bool
    needs_transaction: bool

    retrieved_context: str

    # Human-friendly values + IDs/records resolved from live discovery tools.
    transaction_data: dict[str, Any]
    missing_fields: list[str]
    invalid_fields: list[str]

    validation_errors: list[str]
    summary: list[dict[str, Any]]

    confirmed: bool
    confirmation_response: str

    # Results returned by read/discovery/execution operations.
    tool_result: dict[str, Any]
    final_response: str
