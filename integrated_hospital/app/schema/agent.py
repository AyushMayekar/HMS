from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's message to the hospital AI assistant.",
    )
    thread_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Conversation thread returned by a previous response. Omit it to "
            "start a new conversation."
        ),
    )


class AgentChatResponse(BaseModel):
    success: bool
    response: str
    request_id: str
    thread_id: str = ""
    interrupt: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Set when the agent is waiting for the user (missing details, an "
            "option to pick, or a confirmation). The next message on the same "
            "thread resumes the conversation."
        ),
    )
