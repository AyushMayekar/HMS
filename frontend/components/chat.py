"""
AI Agent chat widget component for the Meridian Care frontend.
"""
from __future__ import annotations

import streamlit as st

from frontend.api.catalog_services import AgentService
from frontend.utils.session import get_access_token
from frontend.config import HOSPITAL


def render_agent_chat(
    title: str = "AI Assistant",
    subtitle: str = "Ask about appointments, departments, billing, or administrative requests.",
    height: int = 500,
) -> None:
    """
    Render the AI agent chat interface.

    Args:
        title: Chat title
        subtitle: Chat subtitle
        height: Chat container height
    """
    st.subheader(title)
    st.caption(subtitle)

    # Initialize chat history
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    # Display chat messages
    chat_container = st.container(height=height)
    with chat_container:
        for message in st.session_state.agent_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Type your message here..."):
        # Add user message
        st.session_state.agent_messages.append({"role": "user", "content": prompt})

        # Show user message immediately
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        # Get agent response
        with st.spinner("Thinking..."):
            agent = AgentService()
            # Set access token in client headers
            token = get_access_token()
            if token:
                agent.client.session.headers["Authorization"] = f"Bearer {token}"

            response = agent.chat(prompt)

        # Handle response
        if response.success:
            agent_response = response.data.get("response", "I couldn't generate a response.")
            st.session_state.agent_messages.append({"role": "assistant", "content": agent_response})

            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(agent_response)
        else:
            error_msg = f"Sorry, I encountered an error: {response.error_message}"
            st.session_state.agent_messages.append({"role": "assistant", "content": error_msg})

            with chat_container:
                with st.chat_message("assistant"):
                    st.error(error_msg)

        # Rerun to update chat
        st.rerun()


def render_simple_chat(
    on_send=None,
    placeholder: str = "Ask me anything...",
    height: int = 400,
) -> None:
    """
    Render a simple chat interface with custom send handler.

    Args:
        on_send: Callback function(message: str) -> str (returns response)
        placeholder: Input placeholder
        height: Container height
    """
    if "simple_chat_messages" not in st.session_state:
        st.session_state.simple_chat_messages = []

    chat_container = st.container(height=height)
    with chat_container:
        for message in st.session_state.simple_chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    if prompt := st.chat_input(placeholder):
        st.session_state.simple_chat_messages.append({"role": "user", "content": prompt})

        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        if on_send:
            with st.spinner("Processing..."):
                response = on_send(prompt)
            st.session_state.simple_chat_messages.append({"role": "assistant", "content": response})

            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(response)

        st.rerun()


def agent_chat_with_confirmation(
    on_confirm=None,
    on_cancel=None,
) -> None:
    """
    Render agent chat with explicit confirmation for transactions.

    This follows the backend agent flow:
    User -> Agent -> Intent -> RAG/Details -> Validation -> Summary -> Confirmation -> Execute
    """
    st.subheader(":material/support_agent: AI Assistant")
    st.caption("I can help with appointments, admin requests, hospital information, and more.")

    if "agent_chat_state" not in st.session_state:
        st.session_state.agent_chat_state = {
            "messages": [],
            "pending_confirmation": None,
            "pending_summary": None,
        }

    state = st.session_state.agent_chat_state

    # Display messages
    chat_container = st.container(height=400)
    with chat_container:
        for msg in state["messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Show confirmation dialog if pending
    if state["pending_confirmation"]:
        st.divider()
        st.warning("**Confirmation required**, please confirm or cancel below.")
        st.markdown(state["pending_summary"])

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Confirm & Execute", icon=":material/task_alt:", type="primary", width="stretch"):
                if on_confirm:
                    result = on_confirm(state["pending_confirmation"])
                    state["messages"].append({"role": "assistant", "content": result})
                state["pending_confirmation"] = None
                state["pending_summary"] = None
                st.rerun()

        with col2:
            if st.button("Cancel", icon=":material/close:", width="stretch"):
                if on_cancel:
                    on_cancel()
                state["messages"].append({"role": "assistant", "content": "Action cancelled."})
                state["pending_confirmation"] = None
                state["pending_summary"] = None
                st.rerun()

    # Chat input (disabled during confirmation)
    disabled = state["pending_confirmation"] is not None
    if prompt := st.chat_input("Type your message...", disabled=disabled):
        state["messages"].append({"role": "user", "content": prompt})
        st.rerun()


def clear_chat_history(key: str = "agent_messages") -> None:
    """Clear chat history."""
    if key in st.session_state:
        st.session_state[key] = []
    if "agent_chat_state" in st.session_state:
        st.session_state.agent_chat_state = {
            "messages": [],
            "pending_confirmation": None,
            "pending_summary": None,
        }