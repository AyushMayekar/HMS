"""Transaction specifications for the AI agent."""


TRANSACTION_SPECS = {
    "appointment_booking": {
        "label": "appointment booking",
        "required_fields": ("department", "appointment_date", "appointment_time"),
        "extract_fields": ("department", "doctor", "appointment_date", "appointment_time"),
        "summary_labels": {
            "department": "Department",
            "doctor": "Doctor",
            "appointment_date": "Date",
            "appointment_time": "Time",
        },
        "user_input_guidance": {
            "department": "Hospital department, e.g. Cardiology",
            "doctor": "Doctor name (optional if you want to choose from the available doctors)",
            "appointment_date": "Date, e.g. 20 September 2026 or tomorrow",
            "appointment_time": "Specific time, e.g. 7 PM or 19:00",
        },
    },
    "administrative_request": {
        "label": "administrative request",
        "required_fields": ("category", "description"),
        "extract_fields": ("category", "description"),
        "summary_labels": {"category": "Category", "description": "Description"},
        "user_input_guidance": {
            "category": "Request category: refund, appointment_issue, account_issue, admin_requirement, or general_support",
            "description": "Describe your request in detail",
        },
    },
    "appointment_lookup": {
        "label": "appointment lookup",
        "required_fields": (),
        "extract_fields": ("doctor", "appointment_date", "appointment_time"),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "appointment_reschedule": {
        "label": "appointment reschedule",
        "required_fields": (),
        "extract_fields": ("new_appointment_date", "new_appointment_time"),
        "summary_labels": {},
        "user_input_guidance": {
            "new_appointment_date": "New appointment date",
            "new_appointment_time": "New appointment time",
        },
    },
    "appointment_cancellation": {
        "label": "appointment cancellation",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "billing_information": {
        "label": "billing information",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "hospital_information": {
        "label": "hospital information",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "general_conversation": {
        "label": "general conversation",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "unsafe_clinical_request": {
        "label": "unsafe clinical request",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
    "analytics_recommendation": {
        "label": "analytics recommendation",
        "required_fields": (),
        "extract_fields": (),
        "summary_labels": {},
        "user_input_guidance": {},
    },
}


def get_transaction_spec(intent: str) -> dict:
    try:
        return TRANSACTION_SPECS[intent]
    except KeyError as exc:
        raise ValueError(f"No transaction specification configured for intent: {intent}") from exc


def build_missing_fields_message(intent: str, missing_fields: list[str]) -> str:
    spec = get_transaction_spec(intent)
    lines = [f"I need a few more details to complete the {spec['label']}.", "", "Please provide:"]
    for field in missing_fields:
        instruction = spec["user_input_guidance"].get(field, field.replace("_", " ").title())
        lines.append(f"- {instruction}")
    return "\n".join(lines)
