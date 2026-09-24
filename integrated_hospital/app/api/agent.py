"""
Agent API routes.
AI assistant chat endpoint.
"""
from __future__ import annotations

import traceback
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from langgraph.types import Command
from supabase import Client

from app.agent.agent import agent
from app.schema.agent import AgentChatRequest, AgentChatResponse
from app.dependencies.auth import (
    AuthContext,
    get_authenticated_supabase_client,
    get_current_user,
    get_current_profile,
)

router = APIRouter(
    prefix="/agent",
    tags=["AI Agent"],
)


def _resolve_thread_id(user_id: str, requested: str | None) -> str:
    """Pick the conversation thread for this request.

    A client-supplied thread id is only honoured when it belongs to the
    authenticated user, so one user can never resume another user's thread.
    Anything else (including the first message of a conversation) gets a fresh
    thread instead of a stale one.
    """
    prefix = f"user-{user_id}"
    if requested and (requested == prefix or requested.startswith(f"{prefix}-")):
        return requested
    return f"{prefix}-{uuid4().hex[:8]}"


def _pending_interrupt_turn(snapshot) -> dict[str, str] | None:
    """The assistant question a thread is currently waiting on, if any.

    Interrupted turns never reach ``generate_response``, so this reconstructs
    that assistant turn for the stored history (best effort — never fatal).
    """
    try:
        for task in getattr(snapshot, "tasks", None) or ():
            for pending in getattr(task, "interrupts", None) or ():
                value = getattr(pending, "value", None)
                text = value.get("message") if isinstance(value, dict) else None
                if text:
                    return {"role": "assistant", "content": str(text)}
    except Exception:  # noqa: BLE001 — history enrichment must never break chat
        return None
    return None


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=status.HTTP_200_OK,
)
def chat_with_agent(
    payload: AgentChatRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_profile),
    supabase: Client = Depends(get_authenticated_supabase_client),
):
    """Chat with the hospital AI assistant.

    The graph pauses on ``interrupt()`` while it collects details, asks the
    user to pick an option, or waits for a confirmation. The pending interrupt
    is returned to the caller and the next message on the same thread resumes
    the graph with ``Command(resume=...)``.
    """
    request_id = request.state.request_id
    thread_id = _resolve_thread_id(auth.user.id, payload.thread_id)

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    context = {
        "supabase": supabase,
        "user_id": auth.user.id,
        "role": auth.profile.get("role", "patient"),
        "profile": auth.profile,
    }

    try:
        # A thread left waiting on an interrupt continues with the user's
        # answer; otherwise this message starts the graph from the top.
        snapshot = agent.get_state(config)
        # A pending interrupt may show up on `next` or only on the snapshot's
        # tasks (LangGraph differs between first-interrupt and re-interrupt),
        # so treat either as "the graph is waiting for this user's answer".
        awaiting_reply = bool(snapshot.next) or any(
            getattr(task, "interrupts", None)
            for task in (getattr(snapshot, "tasks", None) or ())
        )
        prior_messages = [
            dict(message)
            for message in ((snapshot.values or {}).get("messages") or [])
            if isinstance(message, dict)
        ]
        # The API is the single writer of user turns (generate_response writes
        # assistant turns), so history stays correct for both fresh and
        # resumed conversations.
        turns: list[dict[str, str]] = list(prior_messages)
        if awaiting_reply:
            interrupt_turn = _pending_interrupt_turn(snapshot)
            if interrupt_turn:
                turns.append(interrupt_turn)
        history = (turns + [{"role": "user", "content": payload.query}])[-12:]
        if awaiting_reply:
            # update= also refreshes user_input: without it, resumed turns
            # would still see the ORIGINAL message in generate_response.
            step = Command(
                resume=payload.query,
                update={"user_input": payload.query, "messages": history},
            )
        else:
            step = {"user_input": payload.query, "messages": history}

        from app.utils.logger import log_info
        log_info(
            "agent:chat:received",
            thread_id=thread_id,
            awaiting_resume=awaiting_reply,
            history_entries=len(history),
            query=payload.query,
        )

        result = agent.invoke(step, config=config, context=context)
    except Exception as exc:
        # The LLM/embedding credential may be denied (RBAC) or the model
        # unreachable — return a friendly in-band reply instead of a 500.
        from app.utils.logger import log_error
        log_error(
            "agent:chat:failed",
            thread_id=thread_id,
            exception_type=type(exc).__name__,
            error=str(exc)[:1000],
            traceback=traceback.format_exc()[-4000:],
        )
        return AgentChatResponse(
            success=False,
            response=(
                "The AI assistant is temporarily unavailable. Please try again "
                "in a moment, or use the portal menus for appointments, "
                "requests, and hospital information."
            ),
            request_id=request_id,
            thread_id=thread_id,
        )

    from app.utils.logger import log_info

    interrupts = result.get("__interrupt__") or ()
    if interrupts:
        pending = interrupts[0]
        pending = pending.value if hasattr(pending, "value") else pending
        if not isinstance(pending, dict):
            pending = {"message": str(pending)}
        log_info(
            "agent:chat:interrupted",
            thread_id=thread_id,
            interrupt_type=pending.get("type"),
            interrupt_message=str(pending.get("message"))[:300],
        )
        return AgentChatResponse(
            success=True,
            response=pending.get("message")
            or "I need a little more information before I can continue.",
            request_id=request_id,
            thread_id=thread_id,
            interrupt=pending,
        )

    final_response = result.get("final_response")

    if not final_response:
        log_info(
            "agent:chat:empty_result",
            thread_id=thread_id,
            intent=result.get("intent"),
            state_keys=sorted(result.keys()),
        )
        return AgentChatResponse(
            success=False,
            response="I couldn't generate a response for your request.",
            request_id=request_id,
            thread_id=thread_id,
        )

    log_info(
        "agent:chat:completed",
        thread_id=thread_id,
        intent=result.get("intent"),
        reply_chars=len(final_response),
        reply_preview=final_response[:300],
    )
    return AgentChatResponse(
        success=True,
        response=final_response,
        request_id=request_id,
        thread_id=thread_id,
    )
