"""
Agent context.
Dataclass that carries request-scoped context into the agent graph.
"""
from dataclasses import dataclass

from supabase import Client


@dataclass
class AgentContext:
    """Context injected into the agent graph at runtime."""
    supabase: Client
    user_id: str
    role: str
    profile: dict
