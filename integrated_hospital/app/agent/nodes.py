"""LangGraph nodes for the hospital administrative assistant."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langgraph.runtime import Runtime
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from langgraph.errors import GraphInterrupt

from app.config.time import get_current_datetime, get_current_datetime_context
from app.services.rag_service import retrieve_knowledge_context
from app.services.analytics_service import (
    get_appointment_analytics,
    get_no_show_risk_queue,
    get_bed_demand_analytics,
    get_patient_flow_analytics,
    get_billing_analytics,
    get_satisfaction_analytics,
    get_booking_channel_analytics,
    get_no_show_analytics,
    get_waiting_time_analytics,
)
from app.utils.exceptions import AppException
from app.utils.helpers import build_missing_fields_message, get_transaction_spec
from app.utils.logger import log_info
from app.utils.validators import parse_appointment_date, parse_appointment_time, validate_book_appointment, validate_admin_request

from .context import AgentContext
from .prompts import EXTRACTION_PROMPT, INTENT_PROMPT, RESPONSE_PROMPT
from .state import AgentState
from .tools import (
    discover_availability,
    discover_department,
    discover_departments,
    discover_doctors,
    discover_doctor,
    discover_patient_appointments,
    execute_admin_request,
    execute_book_appointment,
    execute_cancel_appointment,
    execute_reschedule_appointment,
    resolve_option,
)

load_dotenv()

http_client = httpx.Client(verify=False)
llm = ChatOpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    model=os.getenv("LLM_MODEL"),
    api_key=os.getenv("LLM_API_KEY"),
    http_client=http_client,
)


class IntentClassification(BaseModel):
    intent: str
    needs_rag: bool
    needs_transaction: bool
    analytics_type: str | None = None


intent_llm = llm.with_structured_output(IntentClassification)

# Cap the history carried into prompts/state (6 turns = 12 entries).
MAX_HISTORY_ENTRIES = 12


def _history_entries(state: AgentState) -> list[dict[str, str]]:
    """Conversation turns BEFORE the current message.

    The API appends the current user turn to ``messages`` before invoking the
    graph, so it is dropped here to keep it out of the ``history`` sections
    (which are always rendered next to an explicit current-message block).
    """
    entries = [dict(m) for m in (state.get("messages") or []) if isinstance(m, dict)]
    current = str(state.get("user_input") or "").strip()
    if (
        entries
        and entries[-1].get("role") == "user"
        and str(entries[-1].get("content") or "").strip() == current
    ):
        entries = entries[:-1]
    return entries


def _format_history(state: AgentState) -> str:
    """Render prior turns for the prompts."""
    entries = _history_entries(state)
    if not entries:
        return "(no earlier conversation)"
    lines = [
        f"{entry.get('role')}: {str(entry.get('content'))[:300]}"
        for entry in entries
        if entry.get("content")
    ]
    return "\n".join(lines) or "(no earlier conversation)"


def _retrieval_query(state: AgentState) -> str:
    """Knowledge-base query for this turn.

    Short follow-ups ("and tomorrow?", "what about cardiology?") embed badly on
    their own, so the previous user line is prepended to anchor them.
    """
    current = str(state.get("user_input") or "").strip()
    if len(current.split()) >= 8:
        return current
    prior = [str(e.get("content") or "") for e in _history_entries(state) if e.get("role") == "user"]
    if prior and prior[-1].strip():
        return f"{prior[-1].strip()} {current}".strip()
    return current


def _with_assistant_turn(state: AgentState, reply: str) -> dict[str, Any]:
    """Record the assistant turn and return the state update."""
    history = [dict(m) for m in (state.get("messages") or []) if isinstance(m, dict)]
    history.append({"role": "assistant", "content": reply})
    return {"final_response": reply, "messages": history[-MAX_HISTORY_ENTRIES:]}


class AppointmentDetails(BaseModel):
    department: str | None = Field(default=None)
    doctor: str | None = Field(default=None)
    appointment_date: str | None = Field(default=None)
    appointment_time: str | None = Field(default=None)
    new_appointment_date: str | None = Field(default=None)
    new_appointment_time: str | None = Field(default=None)


appointment_llm = llm.with_structured_output(AppointmentDetails)


class AdminRequestDetails(BaseModel):
    category: str | None = Field(default=None)
    description: str | None = Field(default=None)


admin_request_llm = llm.with_structured_output(AdminRequestDetails)


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    parsed = parse_appointment_date(value)
    if parsed:
        return parsed.isoformat()

    normalized = value.strip().lower()
    today = get_current_datetime().date()
    if normalized == "today":
        return today.isoformat()
    if normalized == "tomorrow":
        from datetime import timedelta
        return (today + timedelta(days=1)).isoformat()
    if normalized in {"day after tomorrow", "day-after-tomorrow"}:
        from datetime import timedelta
        return (today + timedelta(days=2)).isoformat()
    return value.strip()


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    return parse_appointment_time(value) or value.strip()


def _extract_details(intent: str, user_input: str, existing: dict[str, Any], fields: tuple[str, ...]):
    if intent == "administrative_request":
        prompt = EXTRACTION_PROMPT.format(
            intent=intent,
            current_datetime=get_current_datetime_context(),
            existing_data=existing,
            extract_fields=fields,
            missing_fields=get_transaction_spec(intent)["required_fields"],
            user_input=user_input,
        )
        return admin_request_llm.invoke(prompt).model_dump(exclude_none=True)

    prompt = EXTRACTION_PROMPT.format(
        intent=intent,
        current_datetime=get_current_datetime_context(),
        existing_data=existing,
        extract_fields=fields,
        missing_fields=get_transaction_spec(intent)["required_fields"],
        user_input=user_input,
    )
    return appointment_llm.invoke(prompt).model_dump(exclude_none=True)


def understand_intent(state: AgentState):
    print("Inside IntentClassification")
    result = intent_llm.invoke(
        INTENT_PROMPT.format(
            user_input=state["user_input"],
            history=_format_history(state),
        )
    )
    needs_transaction = result.needs_transaction or result.intent in {"analytics_recommendation"}
    log_info(
        "agent:node:intent",
        user_input=state["user_input"],
        intent=result.intent,
        needs_rag=result.needs_rag,
        needs_transaction=needs_transaction,
        analytics_type=result.analytics_type,
        history_entries=len(state.get("messages") or []),
    )
    return {
        "intent": result.intent,
        "needs_rag": result.needs_rag,
        "needs_transaction": needs_transaction,
        "transaction_data": {
            **state.get("transaction_data", {}),
            **({"analytics_type": result.analytics_type} if result.analytics_type else {}),
        },
    }


def retrieve_knowledge(state: AgentState, runtime: Runtime[AgentContext]):
    print("retrieving knowledge")
    query = _retrieval_query(state)
    result = retrieve_knowledge_context(
        supabase=runtime.context.supabase,
        query=query,
    )
    log_info(
        "agent:node:retrieve_knowledge",
        query=query,
        hits=len(result.get("results") or []),
        context_chars=len(result.get("context") or ""),
        titles=[r.get("title") for r in (result.get("results") or [])],
    )
    return {"retrieved_context": result["context"]}


def _extraction_input(state: AgentState) -> str:
    """Current message plus recent turns for field extraction.

    A turn that ends in ``interrupt()`` never commits its state writes, so on
    resume the node re-runs with an empty ``transaction_data``. Re-reading the
    history recovers details the user already gave ("I said General Medicine
    already") instead of asking for them a second time.
    """
    current = str(state.get("user_input") or "")
    history = _format_history(state)
    if history == "(no earlier conversation)":
        return current
    return f"Conversation so far:\n{history}\nCurrent message: {current}"


def collect_details(state: AgentState):
    intent = state["intent"]
    spec = get_transaction_spec(intent)
    existing_data = dict(state.get("transaction_data", {}))
    required_fields = list(spec["required_fields"])
    extract_fields = tuple(spec.get("extract_fields", required_fields))

    extracted_data = _extract_details(intent, _extraction_input(state), existing_data, extract_fields)
    extracted_data = {k: v for k, v in extracted_data.items() if k in set(extract_fields)}

    if "appointment_date" in extracted_data:
        extracted_data["appointment_date"] = _normalize_date(extracted_data["appointment_date"])
    if "appointment_time" in extracted_data:
        extracted_data["appointment_time"] = _normalize_time(extracted_data["appointment_time"])
    if "new_appointment_date" in extracted_data:
        extracted_data["new_appointment_date"] = _normalize_date(extracted_data["new_appointment_date"])
    if "new_appointment_time" in extracted_data:
        extracted_data["new_appointment_time"] = _normalize_time(extracted_data["new_appointment_time"])

    transaction_data = {**existing_data, **extracted_data}
    missing_fields = [field for field in required_fields if not transaction_data.get(field)]

    if not missing_fields:
        return {"transaction_data": transaction_data, "missing_fields": [], "invalid_fields": []}

    log_info(
        "agent:node:collect_details",
        intent=intent,
        missing_fields=missing_fields,
        known_details=transaction_data,
        action="interrupt_for_details",
    )
    response = interrupt({
        "type": "collect_details",
        "message": build_missing_fields_message(intent, missing_fields),
        "transaction_type": intent,
        "known_details": transaction_data,
        "missing_fields": [
            {
                "field": field,
                "label": spec["summary_labels"].get(field, field.replace("_", " ").title()),
                "instruction": spec["user_input_guidance"].get(field, field.replace("_", " ").title()),
            }
            for field in missing_fields
        ],
    })

    follow_up = _extract_details(intent, _extraction_input(state), transaction_data, tuple(missing_fields))
    follow_up = {k: v for k, v in follow_up.items() if k in set(missing_fields)}
    if "appointment_date" in follow_up:
        follow_up["appointment_date"] = _normalize_date(follow_up["appointment_date"])
    if "appointment_time" in follow_up:
        follow_up["appointment_time"] = _normalize_time(follow_up["appointment_time"])

    transaction_data.update(follow_up)
    missing_fields = [field for field in required_fields if not transaction_data.get(field)]
    return {
        "transaction_data": transaction_data,
        "missing_fields": missing_fields,
        "invalid_fields": [],
    }


def _department_label(row: dict[str, Any]) -> str:
    return str(row.get("name") or "Department")


def _doctor_label(row: dict[str, Any]) -> str:
    return str(row.get("full_name") or "Doctor")


def _slot_label(row: dict[str, Any]) -> str:
    date = str(row.get("slot_date", ""))
    start = str(row.get("start_time", ""))[:5]
    end = str(row.get("end_time", ""))[:5]
    return f"{date} at {start}{f'–{end}' if end else ''}"


def _appointment_display(appointment: dict[str, Any], doctors: dict[str, dict[str, Any]], departments: dict[str, dict[str, Any]]) -> str:
    doctor = doctors.get(appointment.get("doctor_id", {}), {})
    department = departments.get(appointment.get("department_id", {}), {})
    doctor_name = appointment.get("doctor_name") or doctor.get("full_name") or "Doctor"
    department_name = appointment.get("department_name") or department.get("name") or "Department"
    start = str(appointment.get("scheduled_start", ""))
    start = start.replace("T", " ")
    return f"{doctor_name} · {department_name} · {start}"


def _select_from_interrupt(kind: str, prompt: str, options: list[dict[str, Any]], label_fn, id_key: str):
    while True:
        answer = interrupt({
            "type": "selection",
            "selection_type": kind,
            "message": prompt,
            "options": [
                {"number": index, "label": label_fn(option)}
                for index, option in enumerate(options, start=1)
            ],
        })
        selected = resolve_option(answer, options, id_key=id_key, label_fn=label_fn)
        if selected:
            return selected


def _enrich_appointments(appointments: list[dict[str, Any]]):
    doctors: dict[str, dict[str, Any]] = {}
    departments: dict[str, dict[str, Any]] = {}
    for appointment in appointments:
        doctor_id = appointment.get("doctor_id")
        department_id = appointment.get("department_id")
        if doctor_id and doctor_id not in doctors:
            try:
                doctors[doctor_id] = discover_doctor(doctor_id)
            except AppException:
                doctors[doctor_id] = {}
        if department_id and department_id not in departments:
            try:
                departments[department_id] = discover_department(department_id)
            except AppException:
                departments[department_id] = {}
    return doctors, departments


def _resolve_patient_appointment(state: AgentState, patient_id: str, *, mutation: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    appointments = discover_patient_appointments(patient_id)
    if mutation:
        appointments = [
            appointment
            for appointment in appointments
            if appointment.get("appointment_status") == "booked"
        ]

    if not appointments:
        return None, {"success": False, "message": "No matching patient appointments were found."}

    doctors, departments = _enrich_appointments(appointments)
    transaction_data = state.get("transaction_data", {})

    # Lookup/cancel can use explicit doctor/date/time hints from the user's message.
    if state["intent"] in {"appointment_lookup", "appointment_cancellation"}:
        filtered = appointments
        doctor_hint = str(transaction_data.get("doctor") or "").lower().strip()
        date_hint = str(transaction_data.get("appointment_date") or "").strip()
        time_hint = str(transaction_data.get("appointment_time") or "").strip()
        if doctor_hint:
            filtered = [
                appt for appt in filtered
                if doctor_hint in _appointment_display(appt, doctors, departments).lower()
            ]
        if date_hint:
            filtered = [appt for appt in filtered if str(appt.get("scheduled_start", "")).startswith(date_hint)]
        if time_hint:
            filtered = [appt for appt in filtered if str(appt.get("scheduled_start", ""))[11:16] == time_hint]
        if filtered:
            appointments = filtered

    if len(appointments) == 1:
        return appointments[0], {"success": True}

    labels = lambda a: _appointment_display(a, doctors, departments)
    selected = _select_from_interrupt(
        "appointment",
        "Which appointment would you like to use?",
        appointments,
        labels,
        "appointment_id",
    )
    return selected, {"success": True}


def discover_data(state: AgentState, runtime: Runtime[AgentContext]):
    """Resolve names/selections against current DB records before any mutation."""
    intent = state["intent"]
    transaction_data = dict(state.get("transaction_data", {}))
    patient_id = runtime.context.user_id

    try:
        if intent == "appointment_booking":
            departments = discover_departments()
            department_name = transaction_data.get("department")
            department = resolve_option(
                department_name,
                departments,
                id_key="department_id",
                label_fn=_department_label,
            ) if department_name else None
            if not department:
                if not departments:
                    return {"tool_result": {"success": False, "message": "No active departments are currently available."}}
                department = _select_from_interrupt(
                    "department",
                    "Which department would you like to book with?",
                    departments,
                    _department_label,
                    "department_id",
                )
            transaction_data["department_id"] = department["department_id"]
            transaction_data["department"] = department.get("name") or department_name

            doctors = discover_doctors(transaction_data["department_id"])
            doctor = resolve_option(
                transaction_data.get("doctor"),
                doctors,
                id_key="doctor_id",
                label_fn=_doctor_label,
            ) if transaction_data.get("doctor") else None
            if not doctor:
                if not doctors:
                    return {"tool_result": {"success": False, "message": f"No active doctors were found in {transaction_data['department']}."}}
                doctor = _select_from_interrupt(
                    "doctor",
                    f"Which doctor would you like in {transaction_data['department']}?",
                    doctors,
                    _doctor_label,
                    "doctor_id",
                )
            transaction_data["doctor_id"] = doctor["doctor_id"]
            transaction_data["doctor"] = doctor.get("full_name") or transaction_data.get("doctor")

            date = _normalize_date(transaction_data.get("appointment_date"))
            transaction_data["appointment_date"] = date
            slots = discover_availability(doctor_id=doctor["doctor_id"], slot_date=date)
            if not slots:
                return {"tool_result": {"success": False, "message": f"No available slots were found for {transaction_data['doctor']} on {date}."}}

            requested_time = _normalize_time(transaction_data.get("appointment_time"))
            matching = [
                slot for slot in slots
                if requested_time
                and str(slot.get("start_time", ""))[:5] == requested_time
            ]
            if len(matching) == 1:
                slot = matching[0]
            elif len(matching) > 1:
                slot = _select_from_interrupt("availability", "Multiple slots match that time. Please choose one:", matching, _slot_label, "availability_id")
            else:
                slot = _select_from_interrupt(
                    "availability",
                    f"I couldn't find that exact time. Here are the available slots for {date}:",
                    slots,
                    _slot_label,
                    "availability_id",
                )
            transaction_data["availability_id"] = slot["availability_id"]
            transaction_data["appointment_time"] = str(slot.get("start_time", ""))[:5]
            transaction_data["slot"] = slot
            return {"transaction_data": transaction_data, "tool_result": {"success": True, "action": "booking_discovery"}}

        if intent == "appointment_lookup":
            appointment = None
            appointment, discovery = _resolve_patient_appointment(state, patient_id, mutation=False)
            if not discovery["success"]:
                return {"tool_result": discovery}
            doctors, departments = _enrich_appointments([appointment])
            result = {
                "success": True,
                "action": "appointment_lookup",
                "appointment": appointment,
                "display": _appointment_display(appointment, doctors, departments),
            }
            transaction_data["appointment_id"] = appointment["appointment_id"]
            transaction_data["selected_appointment"] = appointment
            return {"transaction_data": transaction_data, "tool_result": result}

        if intent in {"appointment_reschedule", "appointment_cancellation"}:
            appointment, discovery = _resolve_patient_appointment(state, patient_id, mutation=True)
            if not discovery["success"]:
                return {"tool_result": discovery}
            transaction_data["appointment_id"] = appointment["appointment_id"]
            transaction_data["selected_appointment"] = appointment

            if intent == "appointment_cancellation":
                return {
                    "transaction_data": transaction_data,
                    "tool_result": {"success": True, "action": "cancellation_discovery", "appointment": appointment},
                }

            new_date = _normalize_date(transaction_data.get("new_appointment_date"))
            new_time = _normalize_time(transaction_data.get("new_appointment_time"))
            if not new_date or not new_time:
                answer = interrupt({
                    "type": "collect_details",
                    "message": "What date and specific time would you like for the new appointment?",
                    "transaction_type": intent,
                    "known_details": {"appointment": appointment},
                    "missing_fields": ["new_appointment_date", "new_appointment_time"],
                })
                follow_up = _extract_details(intent, str(answer), transaction_data, ("new_appointment_date", "new_appointment_time"))
                new_date = _normalize_date(follow_up.get("new_appointment_date"))
                new_time = _normalize_time(follow_up.get("new_appointment_time"))
            if not new_date or not new_time:
                return {"tool_result": {"success": False, "message": "A new appointment date and specific time are required."}}

            slots = discover_availability(
                doctor_id=appointment["doctor_id"],
                slot_date=new_date,
            )
            if not slots:
                return {"tool_result": {"success": False, "message": f"No available slots were found for {new_date}."}}
            matching = [slot for slot in slots if str(slot.get("start_time", ""))[:5] == new_time]
            if len(matching) == 1:
                slot = matching[0]
            else:
                slot = _select_from_interrupt(
                    "availability",
                    f"Choose a new slot for {new_date}:",
                    slots,
                    _slot_label,
                    "availability_id",
                )
            transaction_data["new_appointment_date"] = new_date
            transaction_data["new_appointment_time"] = str(slot.get("start_time", ""))[:5]
            transaction_data["availability_id"] = slot["availability_id"]
            transaction_data["new_slot"] = slot
            return {"transaction_data": transaction_data, "tool_result": {"success": True, "action": "reschedule_discovery"}}

        if intent == "analytics_recommendation":
            if runtime.context.role not in {"staff", "admin"}:
                return {"tool_result": {"success": False, "message": "Analytics are available to staff and admin users."}}
            analytics_type = transaction_data.get("analytics_type") or "appointments"
            analytics = {
                "appointments": get_appointment_analytics,
                "no_show_risk": lambda: {"risk_queue": get_no_show_risk_queue()},
                "bed_demand": lambda: get_bed_demand_analytics(),
                "patient_flow": lambda: get_patient_flow_analytics(),
                "billing": lambda: get_billing_analytics(),
                "satisfaction": lambda: get_satisfaction_analytics(),
                "booking_channel": lambda: get_booking_channel_analytics(),
                "no_show": lambda: get_no_show_analytics(),
                "waiting_time": lambda: get_waiting_time_analytics(),
            }.get(analytics_type)
            if analytics is None:
                return {"tool_result": {"success": False, "message": "That analytics view is not supported by the existing analytics service."}}
            result = analytics()
            return {"transaction_data": transaction_data, "tool_result": {"success": True, "action": "analytics_recommendation", "analytics_type": analytics_type, "data": result}}

    except AppException as exc:
        return {"tool_result": {"success": False, "error_code": exc.error_code, "message": exc.message}}
    except GraphInterrupt:
        raise
    except Exception as exc:
        return {"tool_result": {"success": False, "message": f"Discovery failed: {type(exc).__name__}."}}

    return {"transaction_data": transaction_data, "tool_result": {"success": True}}


def validate_transaction(state: AgentState):
    intent = state["intent"]
    data = state.get("transaction_data", {})
    errors: list[str] = []

    if intent == "appointment_booking":
        result = validate_book_appointment(
            department=data.get("department", ""),
            appointment_date=data.get("appointment_date", ""),
            appointment_time=data.get("appointment_time", ""),
        )
        if not result["valid"]:
            errors.append(result["message"])
    elif intent == "administrative_request":
        result = validate_admin_request(
            category=data.get("category", ""),
            description=data.get("description", ""),
        )
        if not result["valid"]:
            errors.append(result["message"])
    elif intent == "appointment_reschedule":
        if not data.get("appointment_id") or not data.get("availability_id"):
            errors.append("A real appointment and new availability slot must be resolved before rescheduling.")
    elif intent == "appointment_cancellation":
        if not data.get("appointment_id"):
            errors.append("A real appointment must be resolved before cancellation.")
    return {"validation_errors": errors}


def show_summary(state: AgentState):
    intent = state["intent"]
    data = state.get("transaction_data", {})
    if intent == "appointment_booking":
        summary = [
            {"field": "department", "label": "Department", "value": data.get("department")},
            {"field": "doctor", "label": "Doctor", "value": data.get("doctor")},
            {"field": "appointment_date", "label": "Date", "value": data.get("appointment_date")},
            {"field": "appointment_time", "label": "Time", "value": data.get("appointment_time")},
        ]
    elif intent == "appointment_reschedule":
        old = data.get("selected_appointment", {})
        summary = [
            {"field": "current_appointment", "label": "Current appointment", "value": old.get("scheduled_start", "")},
            {"field": "new_appointment_date", "label": "New date", "value": data.get("new_appointment_date")},
            {"field": "new_appointment_time", "label": "New time", "value": data.get("new_appointment_time")},
        ]
    elif intent == "appointment_cancellation":
        old = data.get("selected_appointment", {})
        summary = [
            {"field": "appointment", "label": "Appointment", "value": old.get("scheduled_start", "")},
            {"field": "appointment_id", "label": "Appointment reference", "value": old.get("appointment_id")},
        ]
    else:
        spec = get_transaction_spec(intent)
        summary = [
            {"field": field, "label": spec["summary_labels"].get(field, field.replace("_", " ").title()), "value": data.get(field)}
            for field in spec["required_fields"]
            if data.get(field) is not None
        ]
    return {"summary": summary}


def confirmation(state: AgentState):
    intent = state["intent"]
    spec = get_transaction_spec(intent)
    log_info(
        "agent:node:confirmation",
        intent=intent,
        summary=state.get("summary", []),
        action="interrupt_for_confirmation",
    )
    answer = interrupt({
        "type": "confirmation",
        "message": f"Please confirm the following {spec['label']}:",
        "transaction_type": intent,
        "summary": state.get("summary", []),
    })
    if isinstance(answer, bool):
        confirmed = answer
    elif isinstance(answer, dict):
        confirmed = str(answer.get("confirmed", answer.get("answer", ""))).strip().lower() in {"yes", "y", "confirm", "confirmed"}
    else:
        confirmed = str(answer).strip().lower() in {"yes", "y", "confirm", "confirmed"}
    return {"confirmed": confirmed, "confirmation_response": str(answer)}


def execute_tool(state: AgentState, runtime: Runtime[AgentContext]):
    if not state.get("confirmed"):
        return {"tool_result": {"success": False, "message": "No mutation was performed because confirmation was not given."}}

    intent = state["intent"]
    data = state.get("transaction_data", {})
    patient_id = runtime.context.user_id

    try:
        if intent == "appointment_booking":
            result = execute_book_appointment(
                patient_id=patient_id,
                doctor_id=data["doctor_id"],
                availability_id=data["availability_id"],
            )
        elif intent == "appointment_reschedule":
            result = execute_reschedule_appointment(
                patient_id=patient_id,
                appointment_id=data["appointment_id"],
                availability_id=data["availability_id"],
            )
        elif intent == "appointment_cancellation":
            result = execute_cancel_appointment(
                patient_id=patient_id,
                appointment_id=data["appointment_id"],
            )
        elif intent == "administrative_request":
            result = execute_admin_request(
                patient_id=patient_id,
                category=data["category"],
                description=data["description"],
            )
        else:
            return {"tool_result": {"success": False, "message": "No mutation is defined for this intent."}}
        log_info("agent:node:execute_tool", intent=intent, success=True)
        return {"tool_result": {"success": True, "data": result}}
    except AppException as exc:
        log_info("agent:node:execute_tool", intent=intent, success=False, error_code=exc.error_code, detail=exc.message)
        return {"tool_result": {"success": False, "error_code": exc.error_code, "message": exc.message}}
    except Exception as exc:
        log_info("agent:node:execute_tool", intent=intent, success=False, exception_type=type(exc).__name__)
        return {"tool_result": {"success": False, "message": f"Execution failed: {type(exc).__name__}."}}


def _deterministic_transaction_response(state: AgentState) -> str | None:
    intent = state["intent"]
    result = state.get("tool_result", {})
    confirmed = state.get("confirmed", False)
    
    if intent == "appointment_lookup":
        if not result.get("success"):
            return result.get("message", "I couldn't find your appointments.")
        appointment = result.get("appointment", {})
        doctor = appointment.get("doctor_name") or "your doctor"
        start = str(appointment.get("scheduled_start", "")).replace("T", " ")
        status = appointment.get("appointment_status", "unknown")
        return f"Your appointment is with {doctor} on {start} (status: {status})."

    if intent in {"appointment_booking", "appointment_reschedule", "appointment_cancellation", "administrative_request"}:
        # A failed discovery/execution must report ITS message first — e.g.
        # "No available slots were found …" — not a misleading confirmation
        # note the user never saw a confirmation for.
        if not result.get("success") and result.get("message"):
            return result["message"]
        # Only report success if the mutation was actually executed (confirmed=True)
        if not confirmed:
            return "No transaction was performed because you did not confirm."
        if not result.get("success"):
            return "The requested operation was not completed."
        if intent == "appointment_booking":
            return "Your appointment was booked successfully."
        if intent == "appointment_reschedule":
            return "Your appointment was rescheduled successfully."
        if intent == "appointment_cancellation":
            return "Your appointment was cancelled successfully."
        return "Your administrative request was created successfully."
    return None


def generate_response(state: AgentState):
    reply = _compose_response(state)
    log_info(
        "agent:node:generate_response",
        intent=state.get("intent"),
        reply_chars=len(reply or ""),
        reply_preview=(reply or "")[:200],
        history_entries=len(state.get("messages") or []),
    )
    return _with_assistant_turn(state, reply)


def _compose_response(state: AgentState) -> str:
    if state.get("intent") == "analytics_recommendation":
        if not state.get("tool_result", {}).get("success"):
            return state.get("tool_result", {}).get(
                "message", "I couldn't retrieve the requested analytics."
            )

    deterministic = _deterministic_transaction_response(state)
    if deterministic is not None:
        return deterministic

    response = llm.invoke(
        RESPONSE_PROMPT.format(
            user_input=state["user_input"],
            history=_format_history(state),
            retrieved_context=state.get("retrieved_context", ""),
            tool_result=state.get("tool_result", {}),
            confirmation_status=state.get("confirmation_response", ""),
        )
    )
    return response.content
