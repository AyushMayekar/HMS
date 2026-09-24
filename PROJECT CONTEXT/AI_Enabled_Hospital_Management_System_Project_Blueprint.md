# AI-Enabled Hospital Management System — Project Blueprint

Final Product + Architecture + Data + AI + Security + Implementation Contract

Blueprint version: 1.0 | Date: 20 September 2026

# 0. Blueprint Purpose and Reading Rules

This document is the single source of truth for the final AI-Enabled Hospital Management System capstone. It is written so that a human developer can understand the product and so that a coding agent can translate the requirements into implementation without inventing business rules.

The blueprint describes the target product and the durable architectural decisions. It deliberately does not contain a five-day execution plan, current model-quality metrics, or a documentation-generation plan. Temporary implementation accidents are not treated as product requirements.

When a statement is marked MUST, it is an implementation invariant. SHOULD means the behavior is preferred unless an existing framework constraint makes it impractical. MAY means optional and non-blocking.

- The backend is authoritative for identity, authorization, IDs, availability, business rules, transaction state, and database writes.
- The LLM is an orchestration component. It may classify intent and extract user-provided details, but it must not invent internal IDs, bypass permissions, or write arbitrary SQL.
- RAG is for grounded static hospital knowledge. Dynamic facts are obtained from database-backed tools.
- The AI agent is administrative. It must not diagnose, prescribe, or make clinical decisions.
- Every AI-initiated transaction follows: collect details -> validate -> show summary -> require explicit confirmation -> execute -> return result.
- Supabase Auth owns authentication. FastAPI validates the authenticated JWT and derives user_id and role from trusted context.
# 1. Product Definition

## 1.1 Product Goal

Build one integrated web application for hospital operations, patient self-service, administrative workflows, grounded hospital information, analytics, prediction-assisted operations, and simulated payment handling.

## 1.2 Primary User Roles

| Role | Primary responsibilities | AI access | Data scope |
| --- | --- | --- | --- |
| Patient / End User | Own appointments, admin requests, feedback, payments, profile, hospital information, AI-assisted booking/requests | Yes - administrative agent | Own records plus public/published hospital information |
| Operational Staff | Appointments, patient operations, analytics, no-show risk/reminders, operational records | No agent | Operational hospital data within staff scope |
| Admin / Manager | Governance, staff/admin user management, department management, KB management, audit/governance, all operational analytics | No agent | Administrative scope across the application |

## 1.3 Core Product Surfaces

- Authentication: email + OTP login/signup using Supabase Auth; successful signup creates the corresponding public profile for the legitimate user.
- Patient portal: dashboard, appointments, appointment detail, admin requests, feedback, payments, profile, hospital information, AI assistant.
- Staff portal: operational dashboard, appointment views, prediction/reminder workflow, patient operations, analytics and forecasting views.
- Admin portal: governance dashboard, user management, department CRUD, knowledge-base management, admin-request supervision, audit visibility.
- Backend: FastAPI API layer with request IDs, validation, role authorization, database access, AI orchestration, analytics and ML services.
- Data/AI: Supabase Postgres, pgvector, RAG retrieval, tool calling, two ML models, analytics pipelines, MLOps metadata/logging.
# 2. Target System Architecture

The final system is a layered architecture. The frontend never owns security decisions, and the LLM never owns transactional truth.

```text
Browser / Web UI
    |
    | HTTPS + Supabase Auth JWT
    v
FastAPI API Layer
    |---- Auth / JWT validation
    |---- Role authorization
    |---- Patient/staff/admin services
    |---- Appointment/payment/request services
    |---- Analytics + ML services
    |---- AI Agent service (LangGraph)
    |---- RAG service
    |---- Audit + structured logging
    |
    +--------------------+----------------------+--------------------+
    |                    |                      |
    v                    v                      v
Supabase Postgres    pgvector / RAG       MLOps metadata
    |                    |                      |
    +-- profiles        +-- knowledge_docs    +-- dataset_versions
    +-- departments     +-- document_chunks   +-- model_versions
    +-- doctors         +-- embeddings        +-- prediction_logs
    +-- appointments
    +-- payments
    +-- reminders
    +-- feedback
    +-- admin_requests
    +-- audit_logs

Authentication is Supabase Auth; application profile identity is public.profiles.user_id = auth.users.id for legitimate users.
```

## 2.1 Architectural Rules

| Rule | Required behavior |
| --- | --- |
| Identity | For protected API calls, derive user_id from the validated JWT. Never trust a user_id supplied by the client when the operation is self-scoped. |
| Authorization | Enforce role and record scope in backend code and with Supabase RLS. Backend checks are explicit and understandable; RLS is the database safety net. |
| Transactions | All writes go through typed service/repository functions. AI tools call those functions; the LLM never receives unrestricted DB access. |
| RAG boundary | Use RAG for published, static hospital knowledge. Use live DB/tool calls for schedules, appointments, patient records, payment status, queue, and availability. |
| Model boundary | Only two ML models are productized: no-show prediction and waiting-time prediction. Other analytics are analytics/forecasting, not separate ML models. |
| Observability | Every request has a request ID. Important mutations and privileged operations produce audit records. ML predictions are logged. |

# 3. Authentication, Identity, Session and Authorization

## 3.1 Authentication Model

Email OTP is the authentication mechanism. Email signup is enabled. Email confirmation is replaced by OTP-based authentication. On a successful OTP verification, Supabase creates the auth.users record when appropriate and the application creates or reconciles the matching public profile for the legitimate user.

The canonical identity is the Supabase Auth user UUID. For legitimate users created through the application, public.profiles.user_id MUST equal auth.users.id. Seeded synthetic profiles are data-science fixtures and are not required to correspond to auth users.

## 3.2 Signup Rules

- Public signup creates only the patient role. Client input must not be allowed to create staff or admin accounts.
- A profile row is created with the Auth UUID as user_id and the authenticated email as the profile email.
- Admin/staff creation is an administrative workflow, not a public-signup workflow.
- If profile creation fails after Auth signup, surface a controlled application error and provide a reconciliation path; do not create a second unrelated UUID profile.
## 3.3 Session Flow

1. Client requests an OTP for an email address.
2. Supabase sends the OTP through the configured SMTP provider.
3. Client submits email + OTP to verification endpoint or completes the Supabase verification flow.
4. Supabase returns the authenticated session/JWT.
5. Client attaches the access token as Bearer authentication to protected FastAPI calls.
6. FastAPI validates the JWT, obtains auth.uid, then loads/validates the matching profile and role.
7. Backend creates request context: request_id, user_id, role, email, route, timestamp.
## 3.4 Authorization Matrix

| Capability | Patient | Staff | Admin |
| --- | --- | --- | --- |
| Read own profile | Yes | Yes for own profile | Yes |
| Update own profile | Yes, without role escalation | Yes, without role escalation | Yes |
| Read own appointments/payments/requests/feedback/reminders | Yes | N/A for own scope; staff operational scope as defined | Yes |
| Create appointment | Yes (own patient identity) | Yes for operational workflows | Yes |
| Update/cancel appointment | Own permitted records | Operational scope | Admin scope |
| Create admin request | Yes | Yes | Yes |
| View operational analytics | No | Yes | Yes |
| No-show prediction/reminder management | No | Yes | Yes |
| Department CRUD | No | No | Yes |
| Knowledge-base CRUD | No | No | Yes |
| User/staff/admin governance | No | No | Yes |
| Audit-log visibility | No | No unless explicitly granted by policy | Yes |

## 3.5 Supabase RLS Baseline

Current RLS direction is retained as the database-level enforcement model. Public application tables have RLS enabled. The blueprint assumes the following policy intent: patients can access own records; staff/admin can access operational records according to role; admin-only resources are protected; all authenticated users can read departments/doctors/availability as currently designed; document chunks are readable only when their parent knowledge document is published unless the caller is staff/admin.

The existing profile policy also prevents a non-admin from changing their role during self-update. This invariant MUST remain. Backend authorization remains mandatory even when RLS is present.

# 4. Supabase Database Blueprint

Supabase Postgres is the system of record. The schema intentionally supports two needs: normalized application relationships and a denormalized appointments fact table used for analytics/ML experimentation.

## 4.1 Core Tables and Purpose

| Table | Purpose | Primary identity / relationship | Product role |
| --- | --- | --- | --- |
| profiles | Application profile and role metadata | user_id = Auth user UUID for legitimate users | Identity + RBAC |
| departments | Hospital departments | department_id | Reference/configuration |
| doctors | Doctor master records | doctor_id -> department_id | Reference/configuration |
| doctor_availability | Doctor time/availability records | availability_id; doctor_id relationship | Scheduling |
| appointments | Main appointment fact and lifecycle record; denormalized for ML/analytics | appointment_id; patient_id -> profiles; department_id -> departments; doctor_id -> doctors | Core transaction + analytics |
| payments | Simulated payment transaction records | payment_id; appointment_id/patient_id relationships | Billing/payment |
| reminders | Reminder delivery records | reminder_id; appointment_id/patient_id | Operations + patient visibility |
| feedback | Patient feedback associated with appointments | feedback_id; appointment_id/patient_id | Patient experience |
| admin_requests | Administrative support/request workflow | request_id; patient_id; optional appointment/payment linkage | Administrative workflow |
| audit_logs | Privileged/application audit trail | audit_id; user_id | Governance + traceability |
| knowledge_documents | RAG source documents and publication metadata | document_id | Knowledge management |
| document_chunks | Chunked knowledge content + pgvector embeddings | chunk_id; document_id | RAG retrieval |
| dataset_versions | Training dataset lineage | dataset_version_id | MLOps |
| model_versions | Saved model/pipeline registry metadata | model_version_id | MLOps |
| prediction_logs | Inference events and prediction trace | prediction_id | ML monitoring/audit |

## 4.2 Confirmed Appointment Fact Table Shape

public.appointments is intentionally a 64-column denormalized fact table. The following column groups are the canonical interpretation for application design. The application must not treat every column as required for every lifecycle stage.

| Group | Columns / semantics |
| --- | --- |
| Identity | appointment_id, patient_id, department_id, department_name, doctor_id |
| Doctor / appointment context | doctor_experience_years, appointment_type, booking_channel |
| Schedule | booked_at, scheduled_start, scheduled_end, lead_time_hours, appointment_hour, appointment_weekday, appointment_month |
| Patient history | is_new_patient, past_appointment_count, past_completed_count, past_no_show_count, past_cancellation_count, past_no_show_rate, past_avg_wait_minutes, past_avg_payment_delay_days |
| Capacity / department context | slot_capacity, slot_booked_count, slot_utilization_pct, department_scheduled_today, department_active_doctors, department_active_staff |
| Queue / operational state | queue_length_at_checkin, patients_ahead_at_checkin, avg_wait_last_24h, avg_service_time_last_24h, arrivals_last_24h, completed_last_24h, admissions_last_24h, discharges_last_24h, occupied_beds, total_beds, occupancy_rate, beds_demand_last_7d_avg, patient_flow_last_7d_avg |
| Reminder/payment context | reminder_sent, reminder_hours_before, payment_required, payment_status_at_booking, invoice_amount, insurance_used, claim_required |
| Lifecycle/outcome | appointment_status, actual_checkin_time, actual_service_start, actual_service_end, actual_wait_minutes, billing_delay_days, satisfaction_score, no_show_target, waiting_time_target, billing_delay_target, satisfaction_target, next_day_bed_demand, next_day_patient_flow |
| Audit timestamps | created_at, updated_at |

## 4.3 Lifecycle Rule for NULLs

NULL is a legitimate lifecycle state, not a validation error. For example, a future appointment should not require actual_checkin_time, actual_service_start, actual_service_end, actual_wait_minutes, billing_delay_days, satisfaction_score, or other outcome-only fields. UI summaries, analytics, and ML feature builders must select only fields relevant to the current use case.

## 4.4 Seeded Data vs Legitimate Auth Data

The current database contains seeded synthetic profiles and approximately 8,000 seeded appointments. Only newly created legitimate users are linked to Supabase Auth. This is acceptable and should be treated explicitly: seeded records are demonstration/training/analytics fixtures; authenticated users are real application identities. Application workflows must never assume every seeded profile is an Auth user.

## 4.5 Current Scale Snapshot

| Table | Current rows | Interpretation |
| --- | --- | --- |
| profiles | 1,205 | Includes seeded synthetic profiles plus legitimate Auth-linked profiles |
| departments | 9 | Configured hospital departments |
| doctors | 20 | Configured doctor master records |
| doctor_availability | 1,200 | Availability records |
| appointments | 8,000 | Main seeded fact table |
| payments | 3,342 | Appointments with simulated payment records in the seeded dataset |
| reminders | 2,355 | Reminder records |
| feedback | 2,609 | Feedback records |
| admin_requests | 350 | Administrative request history |
| audit_logs | 912 | Application audit history |
| dataset_versions | 1 | Dataset lineage baseline |
| model_versions | 0 | To be populated by the finalized ML pipeline |
| prediction_logs | 0 | To be populated during productized inference |

# 5. Backend API Contract

FastAPI is the application boundary. Routes should be versioned (for example /api/v1/...) and grouped by domain. Exact implementation names may differ, but behavior and authorization must match this contract.

## 5.1 Authentication Endpoints

| Endpoint concept | Method | Auth | Purpose |
| --- | --- | --- | --- |
| /api/v1/auth/request-otp | POST | Public | Request email OTP |
| /api/v1/auth/verify-otp | POST | Public | Verify OTP; return application session/user context as appropriate |
| /api/v1/auth/me | GET | Bearer JWT | Return authenticated user profile and role |
| /api/v1/auth/logout | POST | Bearer JWT | Client/session logout handling |

## 5.2 Patient Endpoints

| Endpoint concept | Method | Scope | Purpose |
| --- | --- | --- | --- |
| /api/v1/appointments | POST | Authenticated patient/staff/admin | Create an appointment after backend validation |
| /api/v1/appointments | GET | Patient sees own; staff/admin operational scope | List appointments |
| /api/v1/appointments/{id} | GET | Scoped | Appointment detail |
| /api/v1/appointments/{id} | PATCH | Scoped | Reschedule/update permitted fields |
| /api/v1/appointments/{id}/cancel | POST | Scoped | Cancel with business rules |
| /api/v1/admin-requests | POST | Authenticated | Create administrative request |
| /api/v1/admin-requests | GET | Patient own; staff/admin wider | List requests |
| /api/v1/admin-requests/{id} | GET/PATCH | Scoped | View/update workflow state according to role |
| /api/v1/payments | POST | Authenticated, backend-validated | Create simulated payment attempt |
| /api/v1/payments/{id} | GET | Patient own; staff/admin operational | Payment detail |
| /api/v1/feedback | POST | Authenticated patient | Submit feedback |
| /api/v1/feedback | GET | Scoped | Read feedback |

## 5.3 Operations/Admin Endpoints

| Endpoint concept | Role | Purpose |
| --- | --- | --- |
| /api/v1/departments ... | Admin CRUD; authenticated read | Department management |
| /api/v1/doctors ... | Staff/Admin management; authenticated read | Doctor management |
| /api/v1/availability ... | Staff/Admin write; authenticated read | Doctor availability |
| /api/v1/analytics/... | Staff/Admin | Dashboard analytics and refresh |
| /api/v1/predictions/no-show/... | Staff/Admin | No-show inference and prediction review |
| /api/v1/predictions/waiting-time/... | Staff/Admin | Waiting-time inference at eligible lifecycle points |
| /api/v1/reminders/... | Staff/Admin | Send/log reminders; patient read own reminders |
| /api/v1/knowledge/... | Admin write; authenticated published read | KB management |
| /api/v1/audit-logs ... | Admin | Governance/audit viewing |
| /api/v1/users ... | Admin | Staff/admin governance and user management |

## 5.4 API Response Envelope

```text
Success shape (recommended):
{
  "success": true,
  "data": <typed payload>,
  "request_id": "<uuid>"
}

Controlled error shape:
{
  "success": false,
  "error": {
    "code": "<stable_machine_code>",
    "message": "<safe_human_message>",
    "details": <optional_safe_details>
  },
  "request_id": "<uuid>"
}

Never return raw stack traces, SQL, provider secrets, JWTs, or internal exception text to end users.
```

# 6. Appointment Management

## 6.1 Canonical Booking Flow

1. Resolve authenticated patient identity from JWT; do not accept arbitrary patient_id for self-service booking.
2. Resolve department by department_id or validated department name. The LLM may suggest a name, but the backend maps it to a real department row.
3. Resolve an available doctor/slot using doctor_availability and current appointment state/business rules.
4. Validate date/time, operating hours, slot availability, duplicate/conflicting appointments, and other configured rules.
5. Calculate or confirm payment requirement/invoice information where applicable.
6. Create the appointment using a transactional service function. Populate only fields known at booking time.
7. If payment is required, create the corresponding payment/invoice state and return the payment action required by the UI.
8. Emit audit information for important mutations.
## 6.2 Appointment Status

The application must support the seeded lifecycle concepts booked, completed, no_show, and cancelled. Future/active appointments are represented by appropriate status plus NULL outcome fields. Any additional display state must be derived from the canonical DB state rather than invented independently by the frontend.

## 6.3 Reschedule/Cancel

Reschedule and cancellation are domain operations, not generic PATCHes. The service validates ownership/role, scheduling rules, conflicts, payment consequences, and downstream state. The UI should expose these as explicit actions.

# 7. Simulated Payment and Billing Support

Payment is simulated. No real payment gateway is required. The system must not store real bank/card credentials.

## 7.1 Payment Flow

1. Appointment or workflow determines that payment is required.
2. Backend creates or exposes the payment requirement and amount.
3. Patient selects one of the supported simulated methods: UPI, card, or cash.
4. UI collects simulated credential/token fields suitable for demonstration only; these are not persisted as real financial credentials.
5. Backend runs a deterministic/demo simulation that can produce success, failure, or pending.
6. Payment row is updated with method, status, transaction reference, timestamps and related appointment/patient linkage.
7. Appointment/payment UI reflects the resulting state.
8. Relevant actions are auditable.
## 7.2 Billing Support Boundaries

- AI may explain billing procedures from RAG knowledge.
- AI may inspect the user’s live payment/appointment information through scoped tools.
- AI may raise a refund/admin request, but it cannot approve or guarantee a refund.
- Actual payment processing is simulated; never imply a real external charge was made.
# 8. Administrative Requests

Admin requests are a first-class workflow. Supported categories include refund, appointment_issue, account_issue, admin_requirement, and general_support. Requests have workflow states such as pending, in_progress, resolved, and rejected.

## 8.1 Request Creation Rules

- Patient-created requests automatically use the authenticated patient identity.
- Optional appointment_id/payment_id associations must be validated to belong to the caller when the caller is a patient.
- Priority, assignment, resolution and other privileged fields are backend-controlled.
- The AI assistant can collect the description and related record context, show it in a confirmation summary, and create the request only after explicit confirmation.
# 9. AI Assistant Architecture

The AI assistant uses a LangGraph-style state machine. The graph is designed to be deterministic at the boundaries where data, permissions, and transactions matter.

## 9.1 Supported Intents

| Intent | Action |
| --- | --- |
| general_conversation | Respond conversationally without transaction or RAG unless needed |
| hospital_information | Retrieve grounded published knowledge via RAG |
| appointment_booking | Collect/validate booking details, confirm, execute booking tool |
| appointment_lookup | Use live appointment lookup tool scoped to the authenticated patient |
| administrative_request | Collect request details, confirm, execute request-creation tool |
| billing_information | Use RAG for static policy; use live tools for user-specific payment data |
| unsafe_clinical_request | Refuse clinical diagnosis/prescribing behavior and redirect to appropriate human/clinical care pathway |

## 9.2 Graph

```text
START
  -> understand_intent
  -> conditional route
       -> general response
       -> retrieve_knowledge
       -> transaction collection
  -> collect_details
  -> validate_transaction
  -> show_summary
  -> explicit_confirmation
  -> execute_tool
  -> generate_response
  -> END

Important: execution is unreachable until explicit confirmation is recorded in state.
```

## 9.3 Agent State Contract

| State field | Meaning | Authority |
| --- | --- | --- |
| user_id | Authenticated caller identity | Backend/JWT; never LLM |
| role | Authenticated application role | Backend/profile; never LLM |
| intent | Classified user intent | LLM proposal, validated by graph rules |
| messages | Conversation history | Conversation state |
| collected_details | User-provided booking/request fields | LLM extraction + backend validation |
| missing_details | Fields still required | Derived from business rules |
| retrieved_sources | RAG source metadata/chunks | Retriever |
| validated_action | Backend-approved operation + normalized values | Backend only |
| summary | Human-readable proposed transaction | Graph/backend |
| confirmation | Explicit approval flag / event | User action only |
| tool_result | Committed backend result | Backend tool |

## 9.4 Dynamic Summary Rule

Transaction summaries are dynamic. Do not define a universal required_fields array for every intent. Required fields are intent-specific and business-rule-specific. Only values that are known and meaningful for the current transaction should be displayed. Missing/NULL optional fields must be omitted rather than shown as null, None, Unknown, or empty placeholders.

## 9.5 Tool Calling Rules

- Tools expose narrow business operations, not SQL execution.
- Tools receive trusted backend context such as authenticated user_id and validated role.
- The LLM may pass user-facing values such as department name/date/time/description, but backend services resolve internal IDs.
- Tools must re-check authorization and critical business conditions even if validation already ran earlier in the graph.
- Execution tools return structured results, not natural-language paragraphs.
## 9.6 Example Tool Contracts

```text
book_appointment(
    *,
    authenticated_user_id: UUID,
    department_name: str,
    appointment_date: date,
    appointment_time: time,
    appointment_type: str | None = None,
    doctor_name: str | None = None,
) -> {
    appointment_id, department, doctor, scheduled_start,
    appointment_status, payment_required, invoice_amount
}

create_admin_request(
    *,
    authenticated_user_id: UUID,
    category: AdminRequestCategory,
    description: str,
    appointment_id: UUID | None = None,
    payment_id: UUID | None = None,
) -> { request_id, status, category, created_at }
```

# 10. RAG / Knowledge Base

RAG is the source of truth for static hospital information: department descriptions, appointment procedures, visiting procedures, billing policies, refund procedures, and other published policy/content.

## 10.1 RAG Pipeline

1. Admin creates or updates a knowledge document.
2. Backend normalizes document metadata and content.
3. Document is chunked with stable chunk_index values.
4. Each chunk is embedded using the configured embedding model.
5. Embeddings are stored in document_chunks.embedding using pgvector.
6. Document publication state controls end-user visibility.
7. At query time, embed the user question and perform cosine-similarity retrieval using the HNSW index.
8. Only chunks whose parent document is published are eligible for patient-facing retrieval unless caller is authorized for draft/admin content.
9. The LLM generates an answer grounded in retrieved chunks and should mention source/document context where the UI supports it.
## 10.2 RAG vs Database Tool Decision

| Question type | Source |
| --- | --- |
| What departments exist / what does cardiology handle? | RAG or direct reference data where structured lookup is better |
| What is the hospital refund procedure? | RAG |
| What are visiting hours? | RAG |
| What appointments do I have? | Live DB tool |
| Is a 10:30 slot available tomorrow? | Live scheduling tool |
| What is my payment status? | Live DB tool |
| How long will I wait? | Prediction/analytics tool or live operations data, not RAG |

# 11. ML and Analytics Architecture

The product contains exactly two ML prediction models: no-show prediction and waiting-time prediction. Bed demand, patient flow, billing, and satisfaction are analytics/forecasting/recommendation functions and are not treated as additional product ML models unless a later scope change explicitly introduces them.

## 11.1 No-Show Prediction

Operational point: approximately 24 hours before the scheduled appointment. The backend should select eligible upcoming appointments, compute the same historical feature semantics used during training, load a versioned saved preprocessing/model pipeline, score the appointment, and log the prediction.

- Do not use reminder_sent as a causal/no-show feature when the model is deciding whether to send a reminder for the appointment.
- Do not use post-outcome fields such as actual check-in/service/feedback fields for the pre-appointment prediction.
- Historical patient features such as prior appointment counts, cancellations and no-show history are legitimate when computed using information available before the target appointment.
- Staff sees a risk indicator and can trigger a reminder through the reminder service.
- Predictions are logged with model version, input/reference context, timestamp and appointment identity as permitted by the schema.
## 11.2 Waiting-Time Prediction

Waiting-time prediction should run at an operational point where queue and check-in context exists. If the feature builder relies on patients-ahead, queue length, recent service time, or current operational state, inference should occur at check-in or near check-in rather than blindly at booking.

- Feature semantics must match training semantics.
- Only currently available fields may be used at inference time.
- The result is a prediction for operational guidance, not a guarantee.
- The UI should distinguish predicted waiting time from actual measured waiting time.
## 11.3 Analytics / Forecasting Components

| Component | Role | Typical refresh model |
| --- | --- | --- |
| Appointments analytics | Volume, completion/no-show/cancellation trends, scheduling patterns | On demand refresh from current DB data |
| Patient flow | Arrivals/completions/admissions/discharges trends and forecasts | On demand refresh |
| Bed demand | Occupancy/current utilization and next-day demand analytics | On demand refresh |
| Billing analytics | Payment status, delays, amounts, collection patterns | On demand refresh |
| Satisfaction analytics | Ratings, feedback trends, channel patterns | On demand refresh |

## 11.4 Live Analytics Execution Model

1. Staff/admin clicks Refresh or loads a dashboard requiring fresh data.
2. Backend queries the relevant current table(s).
3. Backend selects the lifecycle-appropriate non-null subset for each metric.
4. Backend converts the result set to a DataFrame or equivalent analysis structure.
5. Analysis function computes KPIs, trend series, distributions or forecasts.
6. Backend returns a typed analytics payload; no raw DataFrame is returned.
7. Frontend re-renders current KPIs/visuals and records refresh timestamp.
## 11.5 Training/Inference Consistency

Training and inference must share the same conceptual feature definitions. Where features such as past_no_show_rate are used, inference must reconstruct them from historical records at the correct cutoff time instead of trusting accidentally leaked or post-outcome fields.

# 12. MLOps and Prediction Traceability

The database contains dataset_versions, model_versions and prediction_logs to provide lightweight but explicit ML lineage.

| Artifact | Minimum responsibility |
| --- | --- |
| dataset_versions | Record the dataset identity/version used to train a model, along with creation/source metadata. |
| model_versions | Record model name, version, training dataset reference, feature definition/reference, artifact location and active/deployment status as supported by the schema. |
| prediction_logs | Record each production inference event sufficiently to trace model version, target record, timestamp, outcome/score and request context where appropriate. |

Inference services should load explicit model versions rather than silently using whichever local file happens to exist. The application should be able to identify which model version produced a prediction.

# 13. Frontend Product Blueprint

## 13.1 Patient Dashboard

- Personalized KPI cards: upcoming appointments, completed appointments, outstanding/admin requests, payment status as applicable.
- Appointments list with create/reschedule/cancel actions.
- Appointment detail with schedule, department, doctor, payment state, reminder/feedback state as applicable.
- Admin request list and status tracking.
- Payment history.
- Feedback history and submission for eligible appointments.
- Profile management.
- AI assistant entry point for booking, appointment lookup, administrative requests, billing information, and hospital information.
## 13.2 Staff Dashboard

- Operational KPI cards and recent activity.
- Appointment trends by day/week/month/year.
- No-show risk queue and one-click reminder action.
- Patient-flow analytics and operational forecasts.
- Bed-demand analytics and occupancy indicators.
- Billing analytics.
- Satisfaction analytics.
- Appointment/patient operational management screens within authorized scope.
## 13.3 Admin Dashboard

- All relevant staff analytics plus governance-level visibility.
- User/staff/admin management.
- Department CRUD.
- Doctor/availability administration as authorized.
- Knowledge-document CRUD and publication workflow.
- Administrative request supervision.
- Audit-log review.
## 13.4 UX Rule for Missing Data

Do not display null lifecycle fields as awkward placeholders. Cards, table cells and summary blocks should render conditionally: show a field only when it exists and is relevant to the current object/state.

# 14. Errors, Validation and Observability

## 14.1 Request IDs

A request ID is generated or propagated at middleware entry and included in logs and API responses. All major processing stages should use that same request ID: authentication, route entry, service validation, DB access, AI graph transitions, tool execution, analytics/ML inference, and response completion.

## 14.2 Safe Error Handling

| Failure | User-facing behavior | Developer behavior |
| --- | --- | --- |
| Invalid OTP | Clear generic authentication message | Log provider/result code + request ID, never OTP itself |
| Expired/invalid token | Authentication required / session expired | Log auth validation failure without token contents |
| Unauthorized role | Permission denied | Log role/route/request ID |
| Missing appointment slot | Explain that slot is unavailable; request another slot | Keep normalized backend reason code |
| RAG no relevant source | Say information could not be verified from current hospital knowledge | Log retrieval diagnostics |
| Payment simulation failure | Show simulated failure and next action | Log simulation state/reference, not sensitive credentials |
| Database/provider exception | Generic retry/support message | Log full internal diagnostic securely |
| ML unavailable | Continue non-ML workflow where safe; clearly indicate prediction unavailable | Log model load/inference failure |

## 14.3 Structured Logging

Recommended fields: timestamp, level, request_id, user_id when available, role, route, operation, status, latency_ms, entity_id, model_version where relevant, error_code, and safe metadata. Never log access tokens, OTP values, raw simulated payment credentials, or provider secrets.

# 15. Security and Trust Boundaries

| Boundary | Rule |
| --- | --- |
| Browser -> API | Bearer JWT; HTTPS; no privileged DB credentials in frontend |
| API -> Supabase | Use appropriate Supabase credentials; server-side secrets remain server-side |
| LLM -> tools | Only narrow typed tools; backend injects identity and validates arguments |
| LLM -> RAG | Retriever controls source set; model cannot fabricate a source |
| Patient -> records | Always scope by authenticated user_id |
| Staff/Admin -> records | Explicit role + operation authorization |
| Payment demo | Never store real payment credentials |
| Audit logs | Immutable-by-policy where possible; insert actor is authenticated actor |

## 15.1 Secrets and Configuration

API keys, Supabase service-role credentials, LLM credentials, SMTP credentials and other secrets come from environment/configuration. Never hard-code them, return them in API responses, commit them to Git, or place them in prompts.

## 15.2 Prompt Security

- Treat retrieved text and user input as untrusted content, not instructions with authority over the application.
- The model must not be able to alter its own authorization context.
- The system prompt should establish that tool execution requires graph-level validation and explicit user confirmation.
- Never pass service-role credentials or database connection strings into the LLM context.
# 16. Testing and Acceptance Criteria

## 16.1 Authentication Acceptance

- Valid OTP creates/returns a valid authenticated session.
- Invalid or expired OTP returns a safe error.
- New signup creates patient role only.
- Legitimate profile user_id exactly matches auth.users.id.
- Protected endpoint rejects missing/invalid JWT.
- Role escalation through profile update is impossible for non-admin users.
## 16.2 AI Transaction Acceptance

- Agent identifies appointment booking vs admin request vs information request.
- Agent asks only for fields still required by the active intent.
- Agent never executes a transaction before explicit confirmation.
- Summary contains only populated/relevant fields.
- Backend validates availability/ownership/authorization at execution time.
- Database contains the resulting appointment/request immediately after success.
- Final assistant response is generated from the structured tool result, not invented transaction details.
## 16.3 RAG Acceptance

- Published KB content is retrievable using vector search.
- Unpublished/draft documents are not visible to unauthorized callers.
- Static policy questions use grounded KB content.
- Dynamic patient/scheduling facts are never fabricated from RAG.
## 16.4 ML Acceptance

- No-show inference only uses pre-outcome information available at prediction time.
- Reminder action is available to authorized staff for eligible high-risk appointments.
- Waiting-time prediction runs only when required operational features are available.
- Prediction logs identify the model version that produced each prediction.
## 16.5 End-to-End Demo Acceptance

1. Patient logs in with email OTP.
2. Patient asks AI to book an appointment.
3. Agent collects missing information.
4. Agent validates the proposed slot and shows a clean summary.
5. Patient explicitly confirms.
6. Backend creates the appointment.
7. Patient dashboard immediately shows the appointment.
8. If payment is required, patient completes the simulated payment and the status is reflected in the relevant screens.
9. Staff dashboard can see the appointment in operational views.
10. Eligible no-show prediction can later produce a risk record and reminder action.
11. Admin can manage KB and observe the resulting governance/audit trail.
# 17. Coding-Agent Implementation Contract

A coding agent implementing this project should treat the following as non-negotiable constraints. The agent should prefer the smallest coherent implementation that satisfies them rather than adding speculative abstractions.

## 17.1 MUST

- Use authenticated JWT identity as the source of truth for protected user scope.
- Keep patient, staff and admin authorization explicit in service code and protected by RLS.
- Use typed domain/service functions for appointment, admin request, payment, reminder and feedback mutations.
- Keep the AI agent administrative only; no clinical diagnosis/prescription.
- Require explicit confirmation before AI transaction execution.
- Use RAG only for static/published hospital knowledge and live tools for dynamic data.
- Keep internal IDs out of the model’s authority boundary whenever possible; resolve them server-side.
- Use a single source of feature definitions between training and inference.
- Log request IDs and important mutations.
- Return safe, stable API error envelopes.
- Conditionally render missing/NULL lifecycle data.
## 17.2 MUST NOT

- Do not trust patient_id, role, appointment ownership, or internal IDs sent by the LLM/client without server-side validation.
- Do not give the LLM raw SQL/database write capability.
- Do not execute an AI transaction merely because the model inferred that the user probably meant yes.
- Do not use RAG as a substitute for live appointment/payment/patient state.
- Do not use reminder_sent as a no-show intervention-selection feature when predicting whether a reminder should be sent.
- Do not require every appointments column for booking or every lifecycle state.
- Do not store real payment credentials.
- Do not expose stack traces, tokens, OTPs, secrets or database internals to end users.
## 17.3 PREFERRED Implementation Shape

```text
app/
  api/              # FastAPI route handlers / request-response schemas
  auth/             # JWT validation, current-user dependency, role checks
  services/         # Domain/business operations
  database/         # Supabase client + repositories/queries
  agent/            # LangGraph state, prompts, tools, routing
  rag/              # chunking, embeddings, retrieval, grounded answer helpers
  analytics/        # appointments, patient flow, bed demand, billing, satisfaction
  ml/               # feature builders, train/load/infer for only two models
  models/            # Pydantic/domain schemas
  middleware/        # request IDs, logging, error mapping
  config/            # environment/configuration
tests/
docs/              # optional project documentation
```

The exact folder structure may differ, but separation of concerns should remain clear: routes orchestrate HTTP, services own business rules, database modules own persistence, agent owns conversation state, and ML/analytics own computation.

# 18. Canonical End-to-End Flows

## 18.1 Patient Books by Form

```text
UI form
  -> POST /appointments
  -> JWT validation
  -> patient identity resolution
  -> department/doctor/slot validation
  -> business-rule validation
  -> appointment insert
  -> payment requirement if applicable
  -> audit event
  -> typed response
  -> patient dashboard refresh
```

## 18.2 Patient Books with AI

```text
User message
  -> intent classification
  -> collect missing details
  -> normalize details
  -> backend validation / live availability lookup
  -> dynamic summary
  -> explicit confirmation
  -> booking service/tool
  -> DB transaction
  -> structured result
  -> friendly response
  -> dashboard reflects committed state
```

## 18.3 Patient Asks Hospital Policy

```text
User question
  -> hospital_information intent
  -> vector search published KB
  -> grounded context
  -> answer with source context
  -> no transactional DB mutation
```

## 18.4 Staff Reviews No-Show Risk

```text
Eligible upcoming appointments
  -> feature builder (historical/pre-outcome data)
  -> versioned preprocessing/model
  -> no-show score
  -> prediction_log
  -> staff risk list
  -> optional reminder action
  -> reminders row + audit
  -> patient reminder visibility
```

## 18.5 Waiting-Time Prediction

```text
Patient check-in / operational trigger
  -> live queue + patients-ahead + recent service features
  -> waiting-time feature builder
  -> versioned model
  -> prediction
  -> operational UI
  -> actual wait later recorded separately
```

# 19. Current Database Characteristics to Preserve

The current Supabase environment already contains several sound foundations and they should be reused rather than replaced solely for architectural neatness.

- All public application tables have RLS enabled.
- Appointments, departments, doctors and availability have relationship indexes appropriate for common joins.
- document_chunks has a vector HNSW index using cosine distance, supporting pgvector retrieval.
- Profile, appointment, admin-request, payment, feedback, reminder and audit tables have supporting indexes on common foreign-key fields.
- updated_at triggers exist on the main mutable public tables using set_updated_at().
- pgvector, pgcrypto, uuid-ossp and standard PostgreSQL extensions are available.
- The RLS policy set already distinguishes patient-owned rows from staff/admin operational access and protects admin-only configuration areas.
The final implementation should work with this architecture. Any schema changes should be motivated by a concrete product requirement, not by a desire to make the seeded ML fact table look like a conventional normalized OLTP schema.

# 20. Definition of Done

The capstone is considered functionally complete when the following integrated behavior is demonstrable in one running application:

- A user can authenticate through email OTP and receives a patient profile linked to the Supabase Auth UUID.
- A patient can view and manage their own appointments and submit administrative requests/feedback within permitted rules.
- The AI assistant can answer grounded hospital-information questions using the KB.
- The AI assistant can complete an appointment booking or admin-request workflow using explicit confirmation and backend tools.
- Dynamic appointment/payment data comes from live database tools, not fabricated RAG text.
- A simulated payment flow supports UPI/card/cash with safe demo semantics and visible status changes.
- Staff can view operational analytics and act on no-show prediction results via reminders.
- Waiting-time prediction is available at an operational lifecycle point where its required features exist.
- Admin can govern users, departments, and knowledge documents and review audit information.
- RLS, backend authorization, request IDs, safe error handling, and important audit/prediction logging are active.
- The final UI reflects database state after mutations without requiring manual database edits.
# 21. Agent Pre-Implementation Checklist

| Check | Pass condition |
| --- | --- |
| Auth context | Current user dependency can return Auth UUID + role safely. |
| Profile linkage | Legitimate user profile exists with user_id == auth.users.id. |
| Role checks | Patient/staff/admin checks exist and are reused. |
| RLS | Policies prevent cross-user access even if API code is bypassed. |
| Appointment service | Single domain function owns booking validation + write. |
| Admin-request service | Single domain function owns request validation + write. |
| Payment service | Simulation never persists real credentials. |
| Agent confirmation | Graph blocks execute_tool until explicit confirmation. |
| RAG | Retriever filters to published knowledge for patient-facing requests. |
| Analytics | Refresh runs against current DB data and lifecycle-safe subsets. |
| No-show ML | Inference features are pre-outcome and intervention-safe. |
| Waiting-time ML | Inference occurs when queue/check-in features are available. |
| Observability | Every request has request_id and important mutations are traceable. |
| Frontend | NULL lifecycle values are omitted cleanly. |
