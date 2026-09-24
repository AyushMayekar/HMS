# AI-Enabled Hospital Management System
## Runtime Workflow & Implementation Guide

**Companion document for:**
1. The Project Blueprint
2. Meridian Care Seed Data — Context, Column Reference & Data Workflow
3. This implementation workflow guide

**Purpose:** Define how the live product should turn the seeded data model and lifecycle rules into an actual working hospital-management application. This document focuses on runtime behavior, automation, derived values, ML timing, staff actions, and backend responsibilities.

---

## 1. Why This Document Exists

The `appointments` table is intentionally denormalized and contains fields that become available at different moments in the appointment lifecycle. That is correct for the seed/training dataset, but the live product must not treat all 64 appointment columns as booking-time inputs.

The implementation rule is:

> **Humans record real-world events. The database stores facts. Backend services calculate derived values. Scheduled jobs trigger time-based processing. ML models run only when their required features actually exist.**

The application must therefore evolve an appointment through its lifecycle instead of trying to populate every field at creation time.

---

## 2. Core Runtime Principle

For every piece of data, determine which of these categories it belongs to:

### A. User-provided information
Information the patient or staff member intentionally supplies.

Examples:
- department preference
- requested date/time
- appointment type
- feedback rating/comment
- administrative request description
- payment method / simulated payment input

### B. Event data
Facts that only become known because a real operational event happened.

Examples:
- patient checked in
- consultation started
- consultation ended
- payment completed
- request resolved

### C. Derived data
Values the backend should calculate from authoritative database state.

Examples:
- past appointment count
- past no-show rate
- slot utilization
- patients ahead in queue
- queue length
- average wait time
- recent service time
- arrivals in the last 24 hours
- department appointment count

### D. Time-triggered processing
Actions that should happen because a scheduled condition has become true.

Examples:
- run no-show prediction approximately 24 hours before appointment
- create/log ML predictions
- refresh analytics when staff requests current results
- finalize historical labels when outcomes become known

### E. Historical outcomes / labels
Values that only become valid after the appointment or related event is resolved.

Examples:
- no-show target
- waiting-time target
- billing-delay target
- satisfaction target
- next-day forecast labels

---

## 3. Appointment Lifecycle

The canonical runtime lifecycle is:

```text
BOOKING
   |
   v
Appointment created
   |
   v
~24h before appointment
   |
   v
No-show prediction
   |
   v
Optional reminder intervention
   |
   v
Appointment day
   |
   v
Check-in
   |
   v
Queue values calculated
   |
   v
Waiting-time prediction
   |
   v
Consultation starts
   |
   v
Consultation ends
   |
   v
Resolution
   |
   +-------------------+
   |                   |
   v                   v
Payment            Feedback
   |                   |
   +---------+---------+
             |
             v
Historical labels / analytics / future training data
```

An appointment can therefore legitimately have many `NULL` values early in its lifecycle.

---

## 4. What Happens at Booking

The patient can book through either:

- normal application UI, or
- the LangGraph AI assistant.

The AI assistant may collect and normalize user intent, but it must not directly write to Supabase or decide trusted internal identifiers.

### 4.1 Inputs the booking flow may need

Depending on the booking use case:

- authenticated patient identity
- department
- requested doctor, if any
- appointment date
- appointment time/slot
- appointment type
- booking channel

The authenticated patient identity must come from the Supabase JWT/session, not from a user-entered `patient_id`.

### 4.2 Backend responsibilities

The backend must:

1. authenticate the request
2. resolve the current patient from the JWT
3. validate department/doctor/slot
4. verify doctor and department are active
5. verify requested availability
6. resolve internal UUIDs from trusted database records
7. calculate patient-history features from prior appointments
8. read/calculate current slot capacity information
9. determine payment requirements and invoice information when applicable
10. create the appointment transactionally
11. update bookable slot state safely
12. create the required audit event
13. return a clean API response

### 4.3 Booking-time appointment fields

The booking operation should populate only values that are actually known at booking time, such as:

- identity references
- department/doctor
- appointment context
- schedule fields
- patient-history features as of booking
- slot/capacity features
- booking channel
- payment-at-booking information
- `appointment_status = 'booked'`
- audit timestamps

Lifecycle/outcome fields that have not happened yet remain `NULL`.

---

## 5. Patient History Must Be Calculated by the Backend

The frontend and LLM must not supply historical ML features such as:

- `past_appointment_count`
- `past_completed_count`
- `past_no_show_count`
- `past_cancellation_count`
- `past_no_show_rate`
- `past_avg_wait_minutes`
- `past_avg_payment_delay_days`

These values should be calculated from historical rows for the authenticated patient.

The calculation must respect the appointment's temporal boundary:

> Only information that existed before the appointment being scored/created may be used as a historical feature.

This avoids accidentally using future outcomes to construct a past feature.

---

## 6. Slot and Department Context Must Also Be Automatic

Staff/admin should not manually enter routine scheduling metrics.

### 6.1 Slot capacity

Read from `doctor_availability`.

### 6.2 Booked count

Read from the availability record or calculate from authoritative appointment state, depending on the final consistency strategy.

### 6.3 Slot utilization

For example:

```text
slot_utilization_pct = booked_count / slot_capacity * 100
```

The exact implementation should handle zero capacity safely.

### 6.4 Department scheduled count

Can be calculated by counting relevant appointments for the department/date from the live database.

### 6.5 Active doctors/staff

Can be derived from `doctors` and `profiles` using their active/status and role fields.

The live application should not require humans to maintain these numeric values manually.

---

## 7. AI Booking Workflow

The LangGraph agent remains responsible for conversation orchestration, not database authority.

Canonical flow:

```text
User message
   |
   v
Intent classification
   |
   +--> hospital information --> RAG
   |
   +--> transactional request --> collect details
                                  |
                                  v
                             validate details
                                  |
                                  v
                             show summary
                                  |
                             explicit YES
                                  |
                                  v
                              backend tool
                                  |
                                  v
                              Supabase
                                  |
                                  v
                         friendly final response
```

For appointment booking:

- LLM may understand `"Cardiology tomorrow afternoon"`.
- Backend resolves Cardiology to the real `department_id`.
- Backend resolves doctor/availability.
- Backend performs business validation.
- The user confirms the final summary.
- Only after confirmation does the booking tool execute.

The LLM must never receive unrestricted SQL access.

---

## 8. RAG vs Database Tools

This distinction must remain explicit throughout implementation.

### Use RAG for static/approved hospital knowledge

Examples:

- visiting hours
- appointment procedure
- cancellation policy
- refund procedure
- department information
- administrative requirements
- AI safety policy
- billing/visiting procedures

Flow:

```text
User question
   |
   v
Embedding
   |
   v
Vector similarity search
   |
   v
`document_chunks`
   |
   v
Grounded context
   |
   v
LLM response
```

The existing knowledge base has published documents with chunks and embeddings stored in Supabase.

### Use tools/database queries for dynamic or personal data

Examples:

- current appointment availability
- patient's appointments
- patient's payment status
- patient's admin requests
- current queue state
- current reminders
- current hospital operational metrics

Rule:

> **Static fact = RAG. Current/personal/transactional fact = backend tool/database.**

Do not use RAG as a substitute for live database state.

---

## 9. How the No-Show Model Should Run

The no-show model should not depend on staff remembering to run it manually.

### 9.1 Automated scheduler

Use a recurring scheduler, such as Supabase Cron, to trigger a backend job periodically (for example every 15 minutes).

Conceptual flow:

```text
Supabase Cron
   |
   | every ~15 minutes
   v
/internal/jobs/no-show-predictions
   |
   v
Find eligible upcoming appointments
   |
   v
Build pre-outcome feature vector
   |
   v
Load versioned no-show model
   |
   v
Predict
   |
   v
Write `prediction_logs`
```

The exact deployment mechanism can change, but the behavior must remain automatic and idempotent.

### 9.2 Eligibility rule

A robust eligibility rule should be window-based rather than depending on an exact timestamp.

Conceptually:

```sql
scheduled_start > NOW()
AND scheduled_start <= NOW() + INTERVAL '24 hours'
AND appointment_status = 'booked'
```

The implementation should also ensure the same appointment is not scored repeatedly unless an intentional re-scoring policy exists.

A scheduler running every 15 minutes therefore does not need to hit an exact `24:00:00` boundary.

### 9.3 No-show feature rule

Only features available before the no-show prediction should be used.

Examples include:

- appointment context
- schedule/lead-time features
- patient history
- legitimate pre-outcome booking information

Never use:

- `actual_checkin_time`
- `actual_service_start`
- `actual_service_end`
- `actual_wait_minutes`
- satisfaction/feedback information
- any other post-outcome information

### 9.4 `reminder_sent` must not be a no-show prediction feature

`reminder_sent` is an intervention outcome, not an input to decide whether to send the intervention.

Correct sequence:

```text
No-show model
   |
   v
Risk identified
   |
   v
Staff/system chooses reminder
   |
   v
Reminder sent
```

Incorrect sequence:

```text
Reminder already sent
   |
   v
Model uses reminder_sent
   |
   v
No-show prediction
```

That would create leakage and undermine the intended operational meaning of the model.

---

## 10. How Staff Interacts With No-Show Predictions

Staff should not enter the ML features manually.

They receive an operational view such as:

```text
Upcoming appointments

Patient    Time       Risk
---------------------------
Rahul      10:00     High
Priya      11:30     Low
Amit       14:00     High
```

A staff member can trigger:

```text
[ Send Reminder ]
```

The reminder action should:

1. verify authorization
2. create the `reminders` row
3. update appropriate reminder state on the appointment if that field is retained
4. create an audit log entry
5. return a safe success/failure response

The model itself only predicts risk; it does not directly grant permission or perform arbitrary actions.

---

## 11. What Happens at Check-In

Check-in is a genuine operational event and should be performed by authorized staff.

The UI can simply provide:

```text
[ Check In ]
```

When clicked:

```text
POST /appointments/{appointment_id}/check-in
```

The backend should:

1. authenticate staff/admin
2. verify appointment is eligible for check-in
3. record the current check-in time
4. calculate queue state
5. calculate patients ahead
6. calculate recent operational features needed by the waiting-time model
7. run the waiting-time model
8. store the prediction in `prediction_logs`
9. return the predicted wait and relevant queue information
10. write an audit event where appropriate

Staff should not manually type the number of people ahead.

---

## 12. How `patients_ahead_at_checkin` Is Calculated

This value should be derived from the live queue/database state at the instant of check-in.

One possible definition is:

> Patients ahead = eligible patients in the same operational queue who checked in before the current patient and have not yet started service.

Example:

```text
09:55  Patient A checks in
10:02  Patient B checks in
10:07  Patient C checks in   <-- current patient
```

If A and B are still waiting and have not started service:

```text
patients_ahead_at_checkin = 2
```

The exact queue definition must be documented and then kept identical between training and inference.

### Important

Do not ask staff:

> "How many people are ahead?"

Ask staff only to record the event:

> "Patient checked in."

The backend derives the queue statistic.

---

## 13. How `queue_length_at_checkin` Is Calculated

Define a consistent operational rule, for example:

```text
queue_length_at_checkin
= count of currently checked-in patients who
  are still waiting for service in the relevant queue
```

Whether the current patient is included is a product/feature-definition decision. Once chosen, the same definition must be used in:

- seed/training preparation
- feature builder
- inference
- analytics
- documentation

The important requirement is consistency, not manual entry.

---

## 14. Automatic Waiting-Time Feature Calculation

At check-in, the backend can derive recent operational values from completed/observed visits.

Examples:

### Average wait in the last 24 hours

Calculate from valid completed/check-in records in the relevant time window.

Conceptually:

```text
AVG(actual_service_start - actual_checkin_time)
```

### Average service time in the last 24 hours

```text
AVG(actual_service_end - actual_service_start)
```

### Arrivals in the last 24 hours

Count valid check-ins in the relevant department/time window.

### Completed in the last 24 hours

Count completed appointments in the relevant period.

The feature builder must ignore records where the required lifecycle fields are still `NULL`.

---

## 15. Waiting-Time Prediction Lifecycle

The intended runtime sequence is:

```text
Staff clicks Check In
        |
        v
Record actual_checkin_time
        |
        v
Calculate:
  queue length
  patients ahead
  recent wait
  recent service time
  arrivals
  completed
  other approved features
        |
        v
Waiting-time model
        |
        v
prediction_logs
        |
        v
Return estimated wait
```

This is preferable to running the waiting-time model at booking when queue-dependent features do not yet exist.

---

## 16. During the Consultation

Staff/system should record the real operational events:

```text
[ Start Consultation ]
[ End Consultation ]
```

The backend records:

- `actual_service_start`
- `actual_service_end`

Then `actual_wait_minutes` can be derived from:

```text
actual_service_start - actual_checkin_time
```

Do not ask staff to calculate this manually.

---

## 17. Appointment Resolution

At the end of the lifecycle, the appointment should resolve to an appropriate terminal/operational state such as:

- `completed`
- `no_show`
- `cancelled`

### Completed appointment

Populate valid visit outcome data:

- check-in/service timestamps
- waiting information
- payment information where relevant
- later feedback when submitted

### No-show

No check-in/service events occurred, therefore corresponding fields remain `NULL`.

### Cancelled

If the patient cancelled before a visit occurred, visit-specific fields remain `NULL`.

This is correct lifecycle behavior, not incomplete data.

---

## 18. Payment Workflow

Payments are simulated and must remain clearly separate from real-world payment processing.

Conceptual flow:

```text
Appointment requires payment
        |
        v
Invoice / payment requirement shown
        |
        v
Patient chooses simulated method
  UPI / Card / Cash
        |
        v
Backend simulates outcome
 success / failed / pending
        |
        v
`payments` row updated
        |
        v
Audit trail where appropriate
```

The system must not store real payment credentials.

Values such as billing delay should be derived from payment timestamps/status rather than manually entered into the appointment.

---

## 19. Feedback Workflow

Feedback is a patient action after the visit.

Example:

```text
Appointment completed
        |
        v
Patient dashboard
        |
        v
Rate visit / add comment
        |
        v
`feedback` row
        |
        v
Appointment satisfaction value updated when appropriate
```

Staff should not manually enter the patient's satisfaction score.

---

## 20. Admin Request Workflow

Administrative requests may come from:

- patient UI
- AI assistant
- staff
- admin

Categories include existing configured categories such as:

- refund
- appointment issue
- account issue
- admin requirement
- general support

AI-assisted requests should use the same lifecycle pattern as appointment transactions:

```text
Intent
  |
  v
Collect required details
  |
  v
Validate
  |
  v
Show dynamic summary
  |
  v
Explicit confirmation
  |
  v
Backend tool
  |
  v
`admin_requests`
```

The AI must not approve or guarantee a refund merely because a knowledge-base document describes the refund process.

The KB describes policy/procedure; backend/admin workflow determines the actual request state.

---

## 21. What Staff/Admin Should and Should Not Enter

### Staff/admin should perform real operational actions

Examples:

```text
Check In
Start Consultation
End Consultation
Send Reminder
Resolve Admin Request
Process Simulated Refund/Administrative Action
```

### Staff/admin should not manually populate derived ML/analytics fields

Do not create manual forms asking them to enter:

```text
past_no_show_rate
past_appointment_count
slot_utilization_pct
patients_ahead_at_checkin
queue_length_at_checkin
avg_wait_last_24h
avg_service_time_last_24h
arrivals_last_24h
completed_last_24h
actual_wait_minutes
```

Those are system calculations.

---

## 22. Fields That Cannot Be Correctly Derived From the Current Schema Alone

Some operational concepts in the seeded appointment table do not have a dedicated live event/source table in the current schema.

The major example is live bed operations:

- `occupied_beds`
- `total_beds`
- `admissions_last_24h`
- `discharges_last_24h`

Appointment data alone is not a reliable source of truth for these values.

Two acceptable approaches exist:

### Option A — Analytics/training fixture approach

Keep these primarily as historical/synthetic values for the seeded dataset and analytics demonstrations.

### Option B — Add an operational bed module

Introduce a small source-of-truth structure for bed/admission/discharge events and calculate those metrics from it.

Do **not** ask staff to manually copy bed metrics into every appointment row.

Unless the product requirements explicitly need live bed operations, do not expand the schema unnecessarily just to populate unused columns.

---

## 23. Live Analytics Workflow

Staff/admin analytics should use current database state.

Canonical flow:

```text
Staff clicks Refresh
        |
        v
Backend fetches current relevant data
        |
        v
Convert/select DataFrame inputs
        |
        v
Analytics/forecast function
        |
        v
KPIs / tables / charts / operational findings
        |
        v
Return current results to dashboard
```

The analytics layer must select appropriate non-NULL subsets for each calculation.

Do not treat every `appointments` field as simultaneously available.

---

## 24. Feature Builder Rules

The feature builder is one of the most important implementation boundaries in the project.

For each model, it must define exactly what was known at prediction time.

### No-show model

Feature builder input point:

```text
Approximately 24 hours before appointment
```

Only use pre-outcome information.

### Waiting-time model

Feature builder input point:

```text
At patient check-in
```

Queue and recent operational information may now be included.

### Shared requirement

Training and inference must use the same:

- feature names
- transformations
- encodings
- missing-value handling
- semantics/definitions

Use saved/versioned preprocessing pipelines where appropriate rather than duplicating transformations manually.

---

## 25. ML/MLOps Runtime Sequence

For production-like behavior:

### Training

```text
Historical eligible records
        |
        v
Dataset snapshot
        |
        v
dataset_versions
        |
        v
Feature builder
        |
        v
Model training
        |
        v
Versioned model artifact
        |
        v
model_versions
```

### Inference

```text
Eligible live appointment
        |
        v
Correct feature builder
        |
        v
Versioned model
        |
        v
Prediction
        |
        v
prediction_logs
```

Do not populate `model_versions` or `prediction_logs` with fake metrics/history. These tables are populated by real model training and real inference.

---

## 26. Scheduler Reliability Requirements

The no-show scheduler should be safe to run repeatedly.

### Idempotency

If the scheduler runs every 15 minutes, it must not generate unlimited duplicate predictions for the same appointment unless a deliberate re-scoring strategy says so.

A useful pattern is:

```text
appointment_id
+ model_version
+ prediction purpose/type
+ prediction time/window
```

with application logic to determine whether a fresh prediction is needed.

### Failure handling

If the job encounters one bad appointment:

- log the failure
- continue processing other eligible appointments
- do not expose internal stack traces to patients/staff

### Observability

Use the project's request IDs/logging conventions and include enough context to identify:

- job run
- appointment ID
- model version
- prediction type
- success/failure

---

## 27. Recommended Backend Endpoints

The exact route names can follow the existing API contracts, but the runtime responsibilities should look approximately like this.

### Appointment

```text
POST   /api/v1/appointments
GET    /api/v1/appointments/{appointment_id}
PATCH  /api/v1/appointments/{appointment_id}
POST   /api/v1/appointments/{appointment_id}/cancel
POST   /api/v1/appointments/{appointment_id}/check-in
POST   /api/v1/appointments/{appointment_id}/service-start
POST   /api/v1/appointments/{appointment_id}/service-end
```

### ML internal job

```text
POST /internal/jobs/no-show-predictions
```

This endpoint should be protected so it is not an ordinary public application route.

### Staff operations

Examples may include endpoints/actions for:

```text
GET  upcoming high-risk appointments
POST send reminder
```

### Payment

Use dedicated payment endpoints matching the existing API contract and keep the simulation isolated.

---

## 28. Authorization Rules

For protected operations:

```text
Frontend
   |
   v
Supabase JWT
   |
   v
FastAPI authentication
   |
   v
Authenticated user / role
   |
   v
Backend authorization
   |
   v
Database operation
```

Never accept a trusted patient/user identity from the request body when it can be derived from the JWT.

Backend authorization and Supabase RLS should complement one another.

Examples:

- patient may manage their own appointments within allowed operations
- staff may perform operational actions within scope
- admin may perform administrative/governance actions
- patient cannot read another patient's information
- patient cannot assign themselves staff/admin role
- AI tools must execute using the authenticated user context

---

## 29. Dynamic AI Summary Rule

The AI assistant's confirmation summary must be generated from the fields relevant to the current transaction.

Do not assume every transaction has the same fixed set of summary fields.

For appointment booking, show the meaningful booking information that has been resolved/validated.

For an admin request, show the category, description, linked appointment/payment when relevant, and any other applicable fields.

For missing/optional fields:

- omit fields that are not applicable
- do not display `None`
- do not invent values
- do not force unrelated fields into the summary

---

## 30. End-to-End Example: AI Appointment Booking

```text
1. Patient logs in with email OTP.
2. Supabase creates/validates Auth session.
3. Frontend calls AI endpoint with authenticated session.
4. LangGraph classifies the request as appointment booking.
5. Agent collects missing information.
6. Backend validates department/doctor/slot availability.
7. Backend resolves internal IDs.
8. Backend calculates booking-time patient-history features.
9. Agent shows a dynamic confirmation summary.
10. Patient explicitly confirms.
11. Backend booking tool executes.
12. Appointment is inserted as `booked`.
13. Capacity/booked-count state is updated safely.
14. Audit event is recorded.
15. Patient receives confirmation.
16. Frontend reflects the new appointment.
```

---

## 31. End-to-End Example: Automated No-Show Workflow

```text
1. Appointment is booked for tomorrow.
2. Scheduler runs every ~15 minutes.
3. Appointment enters the 24-hour prediction window.
4. Job checks whether an appropriate prediction already exists.
5. Backend builds the pre-outcome no-show feature vector.
6. Versioned no-show model runs.
7. Prediction is logged to `prediction_logs`.
8. Staff dashboard shows prediction/risk.
9. Staff may click Send Reminder.
10. Reminder is written to `reminders` and appropriate appointment reminder state is updated.
11. Audit trail records the operational action.
```

---

## 32. End-to-End Example: Check-In + Waiting-Time Prediction

```text
1. Patient arrives.
2. Authorized staff clicks Check In.
3. Backend records `actual_checkin_time`.
4. Backend queries the live queue.
5. Backend calculates patients ahead.
6. Backend calculates queue length.
7. Backend calculates recent operational features.
8. Waiting-time feature builder constructs the inference vector.
9. Waiting-time model runs.
10. Prediction is written to `prediction_logs`.
11. Backend returns estimated wait.
12. Staff UI shows estimated wait / queue state.
13. Staff starts consultation later.
14. Backend records actual service start/end.
15. Actual wait is derived and becomes historical information.
```

---

## 33. End-to-End Example: Completed Visit

```text
Booking
  ↓
No-show prediction
  ↓
Check-in
  ↓
Waiting prediction
  ↓
Service start
  ↓
Service end
  ↓
Payment if required
  ↓
Feedback if submitted
  ↓
Appointment finalized
  ↓
Historical features/labels become available for future analytics/training
```

The appointment row accumulates lifecycle facts over time. It is not expected to contain all values from the beginning.

---

## 34. What the AI Coding Agent Must Implement

The coding agent should treat the existing Blueprint and seed-data document as architectural authority and use this document to implement runtime behavior.

### Must implement

- authenticated appointment booking
- backend-derived patient history features
- live availability validation
- safe appointment creation/update lifecycle
- explicit AI transaction confirmation
- RAG for static knowledge
- DB/tools for dynamic/personal data
- automated no-show prediction job
- idempotent prediction processing
- prediction logging
- staff risk/reminder workflow
- staff check-in workflow
- automatic queue/patients-ahead calculation
- waiting-time prediction at check-in
- service start/end event recording
- automatic wait calculation
- payment simulation workflow
- feedback workflow
- admin request workflow
- audit logging
- appropriate authorization/RLS
- graceful errors and request-ID logging

### Must not implement

- staff manually entering ML feature columns
- LLM unrestricted SQL access
- LLM directly writing arbitrary Supabase rows
- using `reminder_sent` as a no-show prediction feature
- using post-outcome fields for no-show inference
- pretending future outcomes are known
- requiring all 64 appointment columns at booking
- using RAG for live availability or personal appointment data
- storing real payment credentials
- fake model metrics or fake prediction history
- trusting `patient_id` from a client request when JWT identity is available

---

## 35. What Should Be Derived vs Manually Entered

| Value / Event | Source | Runtime behavior |
|---|---|---|
| Patient identity | Supabase Auth | derive from JWT |
| Department | patient/AI | validate + resolve ID |
| Doctor | patient/AI/backend | validate + resolve ID |
| Date/time | patient/AI | validate against availability |
| Booking channel | backend | set automatically |
| Booked timestamp | backend | `NOW()` |
| Patient history | appointments history | calculate automatically |
| Slot capacity | doctor availability | read automatically |
| Slot booked count | availability/appointments | calculate/update automatically |
| Slot utilization | capacity data | calculate automatically |
| Department scheduled count | appointments | calculate automatically |
| No-show prediction time | scheduler | automatic |
| No-show prediction | ML model | automatic |
| Reminder | staff/system action | operational event |
| Check-in | staff | event button |
| Patients ahead | queue state | calculate automatically |
| Queue length | queue state | calculate automatically |
| Recent wait | historical visits | calculate automatically |
| Recent service time | historical visits | calculate automatically |
| Service start | staff/system | event button |
| Service end | staff/system | event button |
| Actual wait | timestamps | calculate automatically |
| Payment result | simulated payment workflow | automatic from transaction |
| Satisfaction | patient | submit feedback |
| Outcome status | lifecycle logic/staff | finalize based on events |
| ML targets | historical outcome | finalize automatically |
| Audit record | backend | automatic |

---

## 36. Implementation Philosophy

This is intentionally not an over-engineered hospital ERP.

The capstone should demonstrate a coherent, functioning product where the following pieces work together:

```text
Authentication
      +
Authorization/RLS
      +
Appointment operations
      +
AI agent
      +
RAG
      +
Tool calling
      +
Simulated payments
      +
No-show ML
      +
Waiting-time ML
      +
Operational analytics
      +
MLOps logging
      +
Audit logging
```

The implementation should prefer simple deterministic backend logic over introducing extra infrastructure that is not required by the Blueprint.

---

## 37. Final Mental Model for the Coding Agent

The coding agent should keep this model in mind while implementing:

```text
                  WHO KNOWS WHAT, WHEN?

PATIENT / AI
   |
   | supplies request
   v
BACKEND
   |
   | validates + derives trusted values
   v
DATABASE
   |
   | stores evolving appointment facts
   v
SCHEDULER
   |
   | triggers time-based ML
   v
NO-SHOW MODEL
   |
   v
STAFF INTERVENTION
   |
   v
CHECK-IN EVENT
   |
   v
BACKEND CALCULATES QUEUE
   |
   v
WAITING-TIME MODEL
   |
   v
VISIT EVENTS
   |
   v
PAYMENT / FEEDBACK / RESOLUTION
   |
   v
HISTORICAL DATA
   |
   v
ANALYTICS + FUTURE TRAINING
```

### Golden rule

> **Do not ask a human to enter something the system can derive from authoritative data. Do not let the system pretend to know something that only becomes available after a real-world event.**

That rule resolves the apparent timeline complexity in the seed dataset and provides the intended runtime architecture for the live product.
