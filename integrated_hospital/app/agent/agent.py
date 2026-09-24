"""Agent graph definition."""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .context import AgentContext
from .nodes import (
    collect_details,
    confirmation,
    discover_data,
    execute_tool,
    generate_response,
    retrieve_knowledge,
    show_summary,
    understand_intent,
    validate_transaction,
)
from .router import (
    route_after_confirmation,
    route_after_details,
    route_after_discovery,
    route_after_intent,
    route_after_rag,
    route_after_tool,
    route_after_validation,
)
from .state import AgentState

builder = StateGraph(AgentState, context_schema=AgentContext)

builder.add_node("understand_intent", understand_intent)
builder.add_node("retrieve_knowledge", retrieve_knowledge)
builder.add_node("collect_details", collect_details)
builder.add_node("discover_data", discover_data)
builder.add_node("validate_transaction", validate_transaction)
builder.add_node("show_summary", show_summary)
builder.add_node("confirmation", confirmation)
builder.add_node("execute_tool", execute_tool)
builder.add_node("generate_response", generate_response)

builder.add_edge(START, "understand_intent")
builder.add_conditional_edges("understand_intent", route_after_intent)
builder.add_conditional_edges("retrieve_knowledge", route_after_rag)
builder.add_conditional_edges("collect_details", route_after_details)
builder.add_conditional_edges("discover_data", route_after_discovery)
builder.add_conditional_edges("validate_transaction", route_after_validation)
builder.add_edge("show_summary", "confirmation")
builder.add_conditional_edges("confirmation", route_after_confirmation)
builder.add_conditional_edges("execute_tool", route_after_tool)
builder.add_edge("generate_response", END)

checkpointer = InMemorySaver()
agent = builder.compile(checkpointer=checkpointer)
