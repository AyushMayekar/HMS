"""
Patient AI Assistant page.
"""
import logging

import streamlit as st

from frontend.components.navbar import page_head, breadcrumb, privacy_banner
from frontend.utils.session import require_role, current_user
from frontend.api.catalog_services import AgentService
from frontend.config import HOSPITAL

# Everything the user sends and everything the assistant answers (or fails with)
# is written to the Streamlit log so it can be inspected after a UI test:
#   tail -f /tmp/opencode/frontend.log
chat_log = logging.getLogger("frontend.assistant")
if not chat_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    chat_log.addHandler(_handler)
chat_log.setLevel(logging.INFO)
chat_log.propagate = False

SUGGESTED_PROMPTS = [
    (":material/event:", "Book an appointment", "Please help me book an appointment."),
    (":material/calendar_month:", "My appointments", "Show me my upcoming appointments."),
    (":material/local_hospital:", "Departments", "What departments are available at Meridian Care?"),
    (":material/receipt_long:", "Billing help", "How does billing work for appointments?"),
    (":material/inbox:", "Raise a request", "I want to raise an administrative request."),
    (":material/schedule:", "Visiting hours", "What are the visiting hours?"),
]


def render():
    page_head(
        "AI Assistant",
        "Your smart care companion for booking visits, checking appointment status, and hospital information.",
        noindex=True,
    )
    user = require_role(["patient"])
    breadcrumb(["Patient", "AI Assistant"])
    privacy_banner(
        "The assistant handles appointments, requests, and general hospital information. "
        "It does not provide medical advice — clinical questions should be directed to your doctor."
    )

    # Per-user conversation thread key (backend threads by user id too)
    thread_key = f"agent_thread_{user.user_id}"
    # Server-side conversation id returned by the agent endpoint. Keeping it
    # lets the backend resume the same thread (details/confirmation steps).
    thread_id_key = f"agent_thread_id_{user.user_id}"
    if thread_key not in st.session_state:
        st.session_state[thread_key] = []

    messages = st.session_state[thread_key]

    # Header actions
    c1, c2, c3 = st.columns([4, 1.6, 1.6])
    with c1:
        st.caption(f"Connected as {user.display_name}")
    with c2:
        if st.button("New conversation", width="stretch", help="Clear the current thread"):
            st.session_state[thread_key] = []
            st.session_state.pop(thread_id_key, None)
            st.rerun()
    with c3:
        pass

    sentinel = f"agent_offset_{user.user_id}"

    # Render chat history up to the latest message
    chat_container = st.container(height=520, key=f"agent_chat_{user.user_id}")
    with chat_container:
        if not messages:
            st.markdown(
                f"""
                <div style="text-align:center; padding:2.5rem 1rem; color: var(--mc-muted);">
                    <div style="font-weight:600;">Hello {user.display_name.split(' ')[0]}</div>
                    <div style="margin-top:0.35rem; font-size:0.95rem;">
                        Ask me anything about your care. I can help you book
                        appointments, check schedules, and raise administrative requests
                        — with your explicit confirmation before any action.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            start_idx = st.session_state.get(sentinel, 0)
            for msg in messages[start_idx:]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

    # Suggestion chips when conversation is empty or short
    if len(messages) <= 1:
        st.markdown("**Try asking:**")
        chip_cols = st.columns(3, gap="small")
        for idx, (icon, label, prompt) in enumerate(SUGGESTED_PROMPTS):
            with chip_cols[idx % 3]:
                if st.button(
                    label,
                    key=f"chip_{idx}",
                    icon=icon,
                    width="stretch",
                ):
                    stream_agent_reply(prompt, messages, thread_key, thread_id_key)
                    st.rerun()

    # Chat input
    if prompt := st.chat_input("Ask about appointments, departments, billing, or requests…"):
        stream_agent_reply(prompt, messages, thread_key, thread_id_key)
        st.rerun()

    st.divider()
    st.caption(
        "The assistant may perform actions such as booking or raising requests only after you explicitly "
        "confirm within the conversation. Critical information should be verified with hospital staff."
    )


def stream_agent_reply(
    prompt: str,
    messages: list,
    thread_key: str,
    thread_id_key: str,
) -> None:
    """Send a message to the agent and append the replies to the thread."""
    messages.append({"role": "user", "content": prompt})

    with st.spinner("Meridian assistant is thinking…"):
        agent = AgentService()
        response = agent.chat(prompt, thread_id=st.session_state.get(thread_id_key))

    if response.success:
        data = response.data if isinstance(response.data, dict) else {}
        # Remember the conversation thread so the backend can continue it
        # (missing details, option picks, confirmations).
        if data.get("thread_id"):
            st.session_state[thread_id_key] = data["thread_id"]
        reply = format_agent_reply(data)
        messages.append({"role": "assistant", "content": reply})
        chat_log.info(
            "assistant chat | thread=%s | interrupt=%s | user=%r | assistant=%r",
            data.get("thread_id"),
            (data.get("interrupt") or {}).get("type"),
            prompt,
            reply[:300],
        )
    else:
        chat_log.error(
            "assistant chat FAILED | code=%s | status=%s | request_id=%s | user=%r | error=%s",
            response.error_code,
            response.status_code,
            response.request_id,
            prompt,
            response.error_message,
        )
        messages.append(
            {
                "role": "assistant",
                "content": response.error_message
                or (
                    "I'm having trouble completing that request right now. "
                    "Please try again in a moment, or use the portal menus for "
                    "appointments and requests."
                ),
            }
        )


def format_agent_reply(data: dict) -> str:
    """Turn an agent reply into the markdown shown in the chat.

    Plain answers come back as ``response``. When the agent pauses for input
    (missing details, a list to choose from, or a confirmation) the structured
    payload in ``interrupt`` is rendered underneath its question, so the user
    can simply type the answer — a number, a value, or yes/no.
    """
    text = str(data.get("response") or "").strip()
    interrupt = data.get("interrupt")
    if not isinstance(interrupt, dict) or not interrupt:
        return text or "I've received your request. How else can I help?"

    extras: list[str] = []
    kind = str(interrupt.get("type") or "")

    if kind == "confirmation":
        summary = [
            f"- **{item.get('label')}:** {item.get('value')}"
            for item in interrupt.get("summary") or []
            if isinstance(item, dict)
        ]
        if summary:
            extras.append("**Please review:**\n" + "\n".join(summary))
        extras.append("Reply **yes** to confirm, or **no** to cancel.")
    elif kind == "selection":
        options = [
            f"{item.get('number')}. {item.get('label')}"
            for item in interrupt.get("options") or []
            if isinstance(item, dict)
        ]
        if options:
            extras.append("**Choose one:**\n" + "\n".join(options))
        extras.append("Reply with the number or the exact name.")
    # "collect_details" already lists everything that is needed in its message.

    blocks = ([text] if text else []) + extras
    return "\n\n".join(blocks) or "I've received your request. How else can I help?"


if __name__ == "__main__":
    render()