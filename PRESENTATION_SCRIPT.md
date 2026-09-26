# Meridian Care Multispecialty Hospital — Presentation Script

### Business-impact edition — features first, technical depth held in reserve

> Prepared against the actual build: `frontend/pages/**`, `integrated_hospital/app/**`, `PROJECT CONTEXT/**`.
>
> **How to use this document**
> - **Parts 1–5** are what you *say and show*. Nothing in them explains how a layer is built.
> - **Appendix A** is what you *say only if asked*. Do not speak it unprompted.
> - **Appendix B/C** are prep and claims guardrails — read before rehearsing, never presented.

---

## Table of contents

1. [Part 1 — The business story](#part-1--the-business-story)
2. [Part 2 — Run of show](#part-2--run-of-show)
3. [Part 3 — Speaker scripts](#part-3--speaker-scripts)
   - [0. Radhika — Opener: the problem + the front door](#0-radhika--opener-the-problem--the-front-door)
   - [1. Ayush — Block 1: AI conversational booking ★](#1-ayush--block-1--ai-conversational-booking-)
   - [2. Radhika — Block 2: The self-service portal](#2-radhika--block-2--the-self-service-portal)
   - [3. Param — Block 3: Intelligence that pays for itself](#3-param--block-3--intelligence-that-pays-for-itself)
   - [4. Sakshi — Block 4: One connected record](#4-sakshi--block-4--one-connected-record)
   - [5. Arif — Block 5: Why you can trust all of it](#5-arif--block-5--why-you-can-trust-all-of-it)
   - [6. Ayush — Closer](#6-ayush--closer)
4. [Part 4 — Transition lines](#part-4--transition-lines)
5. [Part 5 — Closing impact summary](#part-5--closing-impact-summary)
6. [Appendix A — "If asked" technical Q&A](#appendix-a--if-asked-technical-qa)
7. [Appendix B — Demo prep checklist](#appendix-b--demo-prep-checklist)
8. [Appendix C — Claims guardrails + open decisions](#appendix-c--claims-guardrails--open-decisions)

---

# Part 1 — The business story

## 1.1 The problem (spoken once, at the top, ~45 seconds)

> "Today a patient calls reception for a slot. Reception checks a register. The doctor gets a paper list. The manager finds out last month's numbers next month. Nothing is *broken* — it's just disconnected, and every disconnected step costs staff time, lost bookings and patient goodwill.
>
> Meridian Care is our answer: the patient-facing service, the hospital's daily operations, and the intelligence to plan ahead — running as **one connected system**, where an action by one person is instantly correct for everybody else."

## 1.2 Impact scoreboard

This is the spine of the presentation. It appears on screen during the opener and again in the closer, and the segments run in exactly this order.

| # | Feature | Who feels it | Business outcome |
|---|---|---|---|
| 1 | **AI conversational booking** ★ | Patient, front desk | Book, check or cancel by typing a sentence — no forms, no phone call, no training. Available 24/7, so the hospital never loses a booking to an office closure. |
| 2 | **Self-service portal** — booking, payments, feedback, requests | Patient | Every routine transaction is handled by the patient instead of by staff: front-desk load removed on **every single transaction**. |
| 3 | **No-show prediction + risk-ordered reminders** | Front desk, revenue | A fixed outreach budget is aimed at the patients most likely to forget — same effort, more visits kept. |
| 4 | **Waiting-time prediction** | Patient, staff | The patient is told honestly how long they'll wait *before* they commit → expectation managed, complaints down, service quality up at zero cost. |
| 5 | **Next-day bed demand & patient flow forecasts** | Operations manager | Staff and capacity planned a day ahead instead of absorbed as a surprise. |
| 6 | **One connected record** | Everyone | No duplicate entry, no reconciling four versions of the same booking — patient, staff and manager see one truth, in real time. |
| 7 | **Role-scoped access + audit trail** | Administrator | People reach only what their job needs, and every action leaves a trace — privacy demonstrated as a *control*, not a promise. |

**Segments 3, 4 and 5 are presented together in Param's block.**

> ⚠️ **No numbers are invented anywhere in this script.** Outcomes are stated directionally. If the team has real measured figures (calls deflected, no-shows reduced, average wait), insert them in `[brackets]` in this table — otherwise leave the brackets out entirely.

## 1.3 The golden thread

The appointment **Ayush's assistant books in Block 1** is the single object every later speaker picks up:

> Ayush **creates** it → Radhika shows **what the patient can do with it** → Param attaches **a risk score and a forecast** → Sakshi shows **what that one record holds together** → Arif shows **who is allowed to touch it, and the line that proves it** → Ayush closes.

Every transition is a handoff of the *same object*, never a change of topic.

---

# Part 2 — Run of show

## 2.1 Timing budget (~20 minutes)

| # | Speaker | Segment | Time |
|---|---|---|---|
| 0 | Radhika | Opener — the problem + the front door | 2:00 |
| 1 | Ayush | **★ Block 1 — AI conversational booking** | 3:30 |
| 2 | Radhika | Block 2 — The self-service portal | 3:00 |
| 3 | Param | Block 3 — Intelligence that pays for itself | 3:30 |
| 4 | Sakshi | Block 4 — One connected record | 2:30 |
| 5 | Arif | Block 5 — Why you can trust all of it | 2:30 |
| 6 | Ayush | Closer | 1:30 |
| | | Transitions (5 × ~15 s) | ~1:00 |
| | | **Total** | **~19:30** |

**If cut to 15:** drop the `/staff-appointments` sweep from Sakshi, the optional `/analytics` beat from Param, and Radhika's form-booking walkthrough (keep her dashboard tour only). Never cut Ayush's refusal beat or Arif's audit beat — they are the highest-credibility seconds in the deck.

## 2.2 Segment shape (apply to every block)

Every speaker follows the same four beats — in this order:

1. **Show the feature** — one screen, one action.
2. **Name who feels it** — patient / front desk / clinician / manager / administrator.
3. **State the business outcome** — in one sentence, out loud.
4. **Live proof** — 20–40 seconds of the thing actually happening.

## 2.3 Accounts and screens used

| Segment | Signed in as | Screens |
|---|---|---|
| Opener | guest → patient | `/` → `/departments` → `/signin` → patient portal |
| Block 1 | patient | `/assistant` → `/appointments` |
| Block 2 | patient | `/dashboard` → `/appointments` → `/payments` `/history` `/feedback` `/requests` |
| Block 3 | staff (+ patient for the wait preview) | `/predictions` → `/reminders` → `/appointments` |
| Block 4 | patient → staff | `/history` → `/staff-appointments` → `/admin` |
| Block 5 | patient → admin | `/admin` (Access Denied) → `/audit-logs` |
| Closer | admin | `/admin` Overview behind the scoreboard |

**Three browser profiles stay pre-logged-in** (patient, staff, admin) — see Appendix B. Never log out live.

---

# Part 3 — Speaker scripts

## 0. Radhika — Opener: the problem + the front door

**Duration: 2:00**

### Click path

1. `/` — cursor sweeps the hero band → points at the two CTAs.
2. `/departments` — scroll two department cards, hover a doctor card. Say **"no login required."**
3. `/signin` — point at Sign In / Sign Up tabs, then the **8-digit code** line. *Do not complete a live OTP if a session is already active.*
4. Land on the patient portal, ready for Ayush.

### Speaker script

> Good morning. This is **Meridian Care Multispecialty Hospital** — one system for the patient experience, the hospital's daily operations, and the intelligence to plan ahead.
>
> Before I show you anything, here's the problem we're solving: *[the problem statement from §1.1 — 45 seconds]*.
>
> **[Home]** This is where a patient lands. The hospital's tagline, address, care desk and emergency numbers — and two clear actions: sign in, or browse. The navigation is identical on every page and every device, so nobody ever has to relearn the site.
>
> **[Departments]** Before handing over a single detail, a visitor can see all seven departments — General Medicine, Cardiology, Orthopedics, Pediatrics, Dermatology, ENT, Gynecology — and the doctors working in them. **A patient should be able to check whether we have what they need before they become a lead.** No login, no form, no waiting for a callback.
>
> **[Sign In]** Sign-in is passwordless: enter your email and we send an **8-digit code**. Nothing to remember, nothing to leak. Patient accounts self-register; staff and administrator accounts can only be created by an administrator.
>
> So — the front door is open to everyone, and everything behind it is tailored to who you are. From here, everything we show you follows **one appointment**, starting with the single feature that changes the economics of a front desk.
>
> Ayush — the patient's first question is always *"can I just book this?"* Show them what happens when they simply ask.

### Key business value (say it, don't skip it)

> "A hospital that can be browsed before sign-up converts more visitors, and a passwordless door removes the single biggest drop-off point in any patient portal — at the same time removing stored passwords from the hospital's risk."

---

## 1. Ayush — Block 1: AI conversational booking ★

**Duration: 3:30** — *this is the headline segment. Slow down here.*

### Click path

1. Open `/assistant`. **Point at the footer line first** — actions only after explicit confirmation, no medical advice. *Set the boundary before showing the power.*
2. Type: **"I want to book a cardiology appointment."**
3. Follow the menus: department → doctor → date → slot → details.
4. When the summary appears: **stop moving the mouse.** Let the evaluator read it. Say the words *"Nothing has happened yet."* Then type **yes**.
5. → `/appointments` — point at the new booking. **This is the money shot.**
6. Back to `/assistant` → **"What are the visiting hours?"** → point at the answer.
7. → **"I have chest pain, what should I do?"** → show the refusal. Stop here.
8. Hand over on the assistant screen.

### Speaker script

> Thank you, Radhika. Everything a patient used to do required learning something — a form, a menu, a phone number. This removes all three.
>
> **[AI Assistant]** Before anything else, look at the line at the bottom of the screen: **it does not give medical advice, and it only acts after you explicitly confirm.** We put the boundary on screen before we showed you the capability — because in a hospital, where the line sits matters as much as what the tool can do.
>
> In normal use a patient just types. No menus to find, no form to understand.
>
> **[Type: "I want to book a cardiology appointment."]**
>
> Watch what it does. It works out *what kind of request this is* — book, cancel, look up, ask about the hospital — from a fixed, defined set. It doesn't wander. **The system decides what that kind of request is allowed to do**, so a patient can't accidentally reach something they shouldn't.
>
> **[Departments appear]** Those are our real departments, pulled from the hospital right now — it did not invent them.
> **[Doctors]** Real doctors in that department.
> **[Date and slots]** Real availability, at this moment.
> **[Details]** Now it collects what it still needs — name, contact, reason for the visit.
>
> **[Summary appears — pause, hands off the mouse]**
>
> Look carefully: department, doctor, date, time. And look — **nothing has happened yet.** No booking, no record, no charge. It is asking permission.
>
> **[Type yes]** *Now* the appointment exists — through exactly the same validated path a human's click would take, with the same checks, the same permissions and the same audit entry. **The AI gets no shortcut.**
>
> **[Switch to Appointments]** And here it is, in the patient's own list, indistinguishable from one booked through a form. **That's the point: a new front door into the same controlled hospital.**
>
> **[Back to Assistant — "What are the visiting hours?"]**
>
> Different kind of question — and this distinction is what makes a hospital assistant trustworthy.
>
> Some information is **fixed and approved** — visiting hours, departments, how billing works. For that, the assistant gives the hospital's *own documented answer*. If it isn't documented, it says so rather than guessing.
>
> Other information is **live and personal** — *your* appointment, today's free slots, *your* payment status. That can never come from a document. It comes from the live system, at the moment you ask.
>
> Confusing those two is exactly how a chatbot confidently tells a patient the wrong appointment time. We don't allow it.
>
> **["I have chest pain, what should I do?"]**
>
> And this is the most important behaviour on the screen: **it declines.** It books, reschedules, cancels, explains hospital information and raises a request. It does not diagnose, does not prescribe, and does not pretend to be a clinician. Where money is involved it doesn't take payment either — it sends you to the payment screen or to reception.
>
> So: **patient asks → the system understands → real hospital data is gathered → a summary is shown → the patient confirms → the hospital acts.** The assistant never owns the hospital's data; it asks, you confirm, the system executes.
>
> **Business outcome:** every booking that happens in a chat window is a phone call that didn't reach reception, a form that didn't get abandoned, and a patient who booked us at eleven at night instead of tomorrow morning.

### Key business value (say it, don't skip it)

> "Conversational booking removes the learning curve and the opening-hours constraint from scheduling — while the hospital keeps full control: no action without confirmation, no live data invented from documents, no medical advice, no payment handling, and every AI action recorded like any other user's."

---

## 2. Radhika — Block 2: The self-service portal

**Duration: 3:00**

### Click path

1. `/dashboard` — point at the **KPI row** (Appointments · Upcoming · Completed visits · Pending payments), then the **Upcoming Appointments** card for the booking Ayush just made.
2. `/appointments` — run the booking path: **Department → Doctor → Date → Slot → Review**.
   - **Pause at slot selection** and point at the expected waiting time.
   - Complete the booking only if the run is ahead of time (~40 s); otherwise stop at the review screen and hand off.
3. Quick sweep, ~4 seconds each, no interaction: `/payments` → `/history` → `/feedback` → `/requests`.
4. Stop on `/dashboard`.

### Speaker script

> Thank you, Ayush — and notice what just happened: the appointment the assistant booked is **already on my dashboard**. Nothing was re-entered, nothing synced.
>
> **[Dashboard]** This is the patient's home base. One glance: how many appointments, what's next, what's completed, what's still owed — plus their upcoming visits, hospital departments, and anything we've asked them to act on. **All of it without a single phone call.** That's the front desk, self-served.
>
> Not every patient wants to chat, though — some want the form. **[Appointments]** Same job, five clear steps: department, doctor, date, slot, review. Watch this —
>
> **[Slot selection, pause]** — **before they confirm, the system tells them the expected waiting time.** Not after they've driven here. Before they've committed. That's us managing the one expectation that generates the most complaints, at the exact moment the patient can still act on it.
>
> **[Quick sweep]** Payments — pay an outstanding invoice and see every receipt. History — every visit, with its ID. Feedback — one review per visit, read-only afterwards. Requests — raise anything administrative and track it to done.
>
> **Business outcome:** everything a patient used to do over the phone is now self-service. Each of those transactions is one fewer ticket at the front desk — and the desk keeps its time for the patients who actually need a human.

### Key business value (say it, don't skip it)

> "Self-service booking, payment, feedback and requests remove front-desk load on **every single transaction** — and the interface changes with the role, so patients see care, staff see operations and admins see control: nobody wastes time hunting for the screen they need."

---

## 3. Param — Block 3: Intelligence that pays for itself

**Duration: 3:30**

### Click path

1. Switch to staff → `/predictions`.
   - **Do not wait for the page to score anything** — it deliberately scores nothing on load. Point at that caption.
   - Tab **No-Show Scoring** → select 2–3 appointments → **Predict Selected** → hover the **risk column** as results appear.
2. Tab **Department Forecasts** → **Bed Demand** → point at tomorrow's bars → **Patient Flow**.
3. `/reminders` — **not in the staff navbar: type the URL** → point at which visits are listed first.
4. Switch to patient → `/appointments` → hover the **expected waiting time** at slot selection.
5. *(Optional, only if ahead of time)* `/analytics` → No-Show / Waiting Time tabs, one scroll.
6. Stop on `/predictions`.

### Speaker script

> Thank you, Radhika. Everything you've seen so far *reacts*. This layer is about **not having to react**.
>
> One boundary first, because "AI in healthcare" usually means something much riskier than what we built: **this does not diagnose, does not treat, and does not touch a single clinical decision.** It looks at operations.
>
> **[Forecasting → No-Show Scoring]** First: **will this patient actually turn up tomorrow?** Staff select the visits they care about and press the button — **notice nothing is scored until a person asks for it.** We don't run models in the background just because we can.
>
> **[Point at the risk column]** Low, medium, high. That's a business signal, not a medical one. And it changes *what the front desk does next* —
>
> **[Reminders]** — because this list is **ordered by risk.** The reminder that used to go to whoever was easiest to reach now goes to the visit most likely to be missed. **Same outreach budget, aimed where the revenue is.**
>
> **[Department Forecasts]** Beyond individuals, the model looks one day ahead: **how many beds will we need, and how many patients will walk in?** Now the hospital can staff and plan *before* the day starts instead of absorbing the surprise — that's the difference between a roster and a scramble.
>
> **[Patient → Appointments]** Second outcome: **the waiting time.** When a patient picks a slot they see an expected wait; at check-in it's refined with the live queue. A patient told *"about 25 minutes"* complains far less than a patient told *"soon."* **Managing that expectation is free service quality.**
>
> One sentence on integrity, because it's easy to get wrong: **we don't let tomorrow's outcome leak into yesterday's prediction, and we deliberately don't feed "was a reminder sent" as an input — that's something *we* did, not something that happened to the patient.**
>
> **Business outcome:** two focused operational models and two forecasts — one purpose: help the hospital **anticipate instead of apologise**, at no clinical risk.

### Key business value (say it, don't skip it)

> "Targeted reminders turn a fixed outreach budget into kept appointments, honest waiting expectations cut complaints before the patient arrives, and next-day forecasts let the hospital staff one day ahead instead of one day behind."

---

## 4. Sakshi — Block 4: One connected record

**Duration: 2:30**

### Click path

1. Switch to patient → `/history` → **click the appointment Ayush booked**, hover its short ID. Say: *"the system generated this ID — nobody typed it."*
2. Switch to staff → `/staff-appointments` → filter to **Tomorrow / Next 7 days** → **find the same appointment.** *Let the evaluator see the same object twice.*
3. Switch to admin → `/admin` → point at the **Hospital Performance** row and the **Platform Snapshot**.
4. *(Optional, 20 s)* `/management` → Departments / Doctors tabs.
5. Stop on `/admin`.

### Speaker script

> Thank you, Radhika. Let's stay with the appointment the assistant just created — because it's the best way to explain what the data layer is *for*.
>
> **[History]** Here it is. One record: which patient, which department, which doctor, what time, what status — and an ID **the system generated**, so nobody can invent one or collide with one.
>
> Now watch what that single record is worth.
>
> **[Staff → Appointments]** The same appointment, on the staff screen, ready to be checked in. **Nobody re-entered anything.** One write, and every other screen in the hospital is already correct.
>
> That's the principle I want to state plainly: **one appointment record supports the entire hospital.** It feeds the patient's history, the staff's queue, reminders, payments, feedback, requests, the audit trail — and it's the raw material the prediction models you just saw learn from. If each of those kept its own copy, they would disagree within a day.
>
> **[Admin → Overview]** And because all of it lives in one place, this screen can tell the hospital **right now** how many appointments we've run, our completion rate, our average wait and our revenue — plus exactly how many users, patients, doctors and departments we have. **That's a Monday-morning meeting that doesn't need a spreadsheet.**
>
> **Business outcome:** no duplicate entry, no reconciling conflicting reports, no "which number is right." The front desk, the clinician's queue, the finance view and the manager's report are looking at the same truth at the same time.
>
> Arif — Sakshi showed you who can *see* the record. Who is allowed to **change** it — and how would we know?

### Key business value (say it, don't skip it)

> "One source of truth means the front desk, the clinician's queue, the finance view and the manager's report never disagree — eliminating duplicate entry, reconciliation work, and the booking errors that cost a hospital real revenue and real patient trust."

---

## 5. Arif — Block 5: Why you can trust all of it

**Duration: 2:30**

### Click path

1. Switch to patient → type `/admin` in the URL → **Access Denied appears.** Stop on it for 5 seconds.
2. Switch to admin → `/audit-logs` → scroll two rows, hover a request ID, point at the action/entity filters.
3. Stop on `/audit-logs` for the hand-off — or switch to the admin Overview if a backdrop is wanted for the closer.

### Speaker script

> Thank you, Sakshi. Everything you've seen only matters if it can be trusted — so let's test it rather than assert it.
>
> **[Patient → type /admin]** I'm signed in as a patient, and I just asked for the administrator's area. **The door is closed.** And that's the friendly version: hiding a button is not security — the real protection is that the hospital checks my role on **every request, on the server**, whether or not anything on screen tried to stop me.
>
> **Business outcome, stated plainly:** patient data stays patient data. A curious or careless staff account can't browse records outside its job. And when someone asks *"how do you know?"*, the answer isn't a policy document —
>
> **[Audit Logs]** — it's **this screen.** Read-only, newest first: who did what, to which record, with a traceable request ID. **Every action leaves a line.** Nobody quietly changes a booking and leaves no evidence.
>
> And one point that closes the loop on what Ayush showed you: **the assistant has no privileged path.** It books through exactly the checks a human's click goes through, it takes no payment, and its actions appear here like anyone else's. That's also how we can add the *next* interface — a kiosk, a phone line, another AI — **without re-implementing the hospital's rules.** The rules live in one place, and everything passes through them.
>
> **Business outcome:** one validated, authorised, audited control layer means the hospital can trust what's on screen, absorb both malicious and careless bad requests, and keep adding channels without multiplying its risk.

### Key business value (say it, don't skip it)

> "Because every operation passes through one validated, authorised and audited layer — patient, staff or AI — the hospital gets speed without giving up control, and privacy it can actually demonstrate rather than merely claim."

---

## 6. Ayush — Closer

**Duration: 1:30**

*Screen: the impact scoreboard (Part 1) on the slide — or the admin Overview behind it.*

### Speaker script

> Let's put it back together — against the scoreboard you saw at the start.
>
> A patient **asks in plain language** and books at eleven at night → **the front desk never rang.**
> They **self-serve** payments, feedback and requests → **every transaction is one fewer ticket at the counter.**
> The hospital **scores no-shows a day ahead** and aims its reminders at the right patients → **the same budget keeps more visits.**
> Patients are told **how long they'll wait before they commit** → **expectations managed, complaints avoided.**
> Managers see **tomorrow's beds and patient flow today** → **staffed ahead, not ambushed.**
> One record, one truth → **no duplicate entry, no reconciliation, no argument about which number is right.**
> And role-scoped access with a full audit trail → **speed without giving up control.**
>
> Any one of these is a feature. **Together they are one hospital ecosystem** — and that integration, not any single feature, is what Meridian Care is.
>
> One booking, made by speaking, understood by the system, validated by the hospital, stored once, predicted on, visible to the entire hospital instantly — and traceable end to end.
>
> Thank you.

---

# Part 4 — Transition lines

Use these verbatim. They replace every "now I will hand over to…" — each one hands over the *same object*.

| From → To | Line |
|---|---|
| **Opener → Ayush** | "The patient's first question is always *'can I just book this?'* — Ayush, show them what happens when they simply ask." |
| **Ayush → Radhika** | "That appointment is made by talking. Radhika — now show us everything the patient themselves can do with it." |
| **Radhika → Param** | "Everything so far handles today. Param — what can the hospital know *before* it happens?" |
| **Param → Sakshi** | "Every number you just saw came from one place. Sakshi — what is that place, and why does one record hold the whole hospital together?" |
| **Sakshi → Arif** | "Sakshi showed who can *see* the record. Arif — who is allowed to *change* it, and how would we know?" |
| **Arif → Ayush** | "Arif showed the rules nobody bypasses. Ayush — put the whole picture back together." |

**Opening line (Radhika, before the problem statement):**

> "You'll hear five voices today — but you'll only ever be looking at **one hospital**. Everything we show you follows a single appointment, from the moment a patient asks for it to the moment the hospital acts on it."

---

# Part 5 — Closing impact summary

Show this table when the closer runs. It is the whole presentation in one screen.

| The reality hospitals live with | With Meridian Care |
|---|---|
| Patient phones reception; after hours = no booking | Book by typing a sentence, 24/7, in plain language |
| Front desk handles every payment, feedback and request | Patients self-serve; staff handle the exceptions |
| No-show discovered when the chair sits empty | Risk scored a day ahead; reminders aimed at the highest risk |
| "How long will I wait?" → "soon" | Expected wait shown *before* booking, refined at check-in |
| Staff plan the day as it ambushes them | Tomorrow's beds and patient flow known today |
| Four copies of one booking that disagree | One record, correct on every screen, in real time |
| "Who changed this?" → nobody knows | Every action logged, read-only and traceable |
| New channel = re-implement the rules | One control layer every interface passes through |

---

# Appendix A — "If asked" technical Q&A

**Nothing here is spoken unless an evaluator asks. Answer, then stop — do not volunteer the next bullet.**

## A1. Frontend & access (Radhika)

- **Why OTP instead of passwords?** Passwordless 8-digit OTP via `POST /api/v1/auth/request-otp` → `/api/v1/auth/verify-otp`. No stored password to leak. Staff/admin accounts are admin-provisioned only (no self-signup).
- **How is role-based UI enforced?** Every page calls `require_role([...])`; the wrong role routes to a built-in **Access Denied** screen (`frontend/pages/system/access_denied.py`). This is *UX only* — the backend re-checks independently (A3).
- **How are errors handled?** `frontend/app.py` wraps `nav.run()` in try/except; tracebacks never reach the user — they route to a friendly error page.
- **Responsive / accessibility?** Consistent navbar, labelled inputs, inline validation, readable contrast — state these as design principles, not a certification.
- **Where does the waiting time come from?** `POST /api/v1/predictions/waiting-time/booking-preview`, computed at slot selection — not a hard-coded number.
- **Dashboard contents (for accuracy):** KPI row = Appointments · Upcoming · Completed visits · Pending payments; then Upcoming Appointments (with wait forecast), Hospital Departments, reminders/requests.

## A2. Data layer (Sakshi)

- **Which tables matter?** `profiles` (identity + role), `departments` → `doctors` → `doctor_availability`, **`appointments` as the central fact table**, plus `payments`, `reminders`, `feedback`, `admin_requests`, `audit_logs`, and `knowledge_documents` → `document_chunks` for retrieval.
- **How are IDs generated?** UUIDs generated on insert by the application/database layer; the UI only ever displays a shortened form (`short_id()`, first 8 chars) and never invents an ID.
- **How is access controlled?** Supabase Postgres **Row Level Security**; queries run under the caller's own JWT (`get_authenticated_supabase_client`), so the database enforces access even if the API were bypassed.
- **Why no ORM?** Deliberate — a direct Supabase client keeps queries explicit and RLS visible.
- **Consistency?** Typed service-layer errors (`SlotUnavailableError`, `InvalidOperationError`) rather than silent partial writes. `NULL` means *"this stage hasn't happened yet"*, not missing data — a still-booked future appointment legitimately has check-in, outcome and forecast fields empty.
- **Privacy wording?** Say *"role-scoped access + RLS + full audit trail, aligned with healthcare privacy principles."* **Never claim HIPAA compliance** (Appendix C).
- **Schema reference:** `PROJECT CONTEXT/AI_Hospital_Complete_Data_Schema_and_Seed_Spec.docx.md`.

## A3. Backend (Arif)

- **The actual flow:** `frontend/api/client.py` (`APIClient`, adds `Authorization: Bearer`, 90 s agent timeout) → FastAPI router under `/api/v1` → Pydantic schema (`integrated_hospital/app/schema/`) + domain validators → service layer → Supabase.
- **Key endpoints:** `POST /api/v1/patient/appointments`, `PATCH .../{id}/reschedule`, `POST .../{id}/cancel`, `POST /api/v1/staff/appointments/{id}/check-in`, `POST /api/v1/agent/chat`, `GET|POST /api/v1/predictions/no-show-*`, `GET /api/v1/admin/audit-logs`.
- **Authorization:** `get_current_user` validates the JWT → profile must be `status=active` → `require_admin / require_staff / require_patient / require_doctor`. **Identity always comes from the token, never the request body.**
- **Error handling:** `X-Request-ID` middleware on every request; errors return `{success:false, error:{code,message}, request_id}` — which is why every on-screen failure has an ID the team can trace.
- **Validation examples:** vague times like "morning" are rejected; appointment categories are alias-normalised to five canonical values; slot availability is re-checked server-side at write time (`SlotUnavailableError`).
- **AI integration:** `POST /api/v1/agent/chat` — the agent's tools call the *same* service functions the UI uses. **No privileged path.**
- **Optional 10-second engineering proof:** `http://127.0.0.1:8000/docs` — the FastAPI endpoint list. Only if an evaluator signals technical interest.

## A4. ML (Param)

- **Model 1 — no-show:** ~21 input columns (lead time, appointment hour/weekday/month, past attendance and cancellation counts, past no-show rate, slot capacity/booked/utilisation, average payment delay; categoricals: new patient, payment required, appointment type, booking channel, department, payment status at booking). F1-optimised threshold ≈ 0.2; bands high > 0.6, medium > 0.3.
- **Model 2 — waiting time:** ~14 features — queue length at check-in, patients ahead, doctor experience, department staffing, slot utilisation, trailing 24-hour average wait/service time. A separate **booking-preview** variant (no queue columns) is used before check-in exists.
- **No leakage:** `reminder_sent` / `reminder_hours_before` are **deliberately excluded** (intervention variables — `integrated_hospital/app/services/prediction_service.py`). Waiting-time inference is gated on `actual_checkin_time` and returns `prediction_status="insufficient_data"` rather than inventing a number.
- **Batching & audit:** scoring is capped at **10 appointments per action** (`MAX_NO_SHOW_BATCH`), eligibility is a ±tolerance window around **T+24 h**, re-score interval **6 h**, and every run writes a `prediction_logs` row with a model version — lineage via `dataset_versions → model_versions → prediction_logs`.
- **Extra forecasts:** bed demand (13 features) and patient flow (11 features) for next-day planning. ⚠ See Appendix C, decision 1.
- **Serving:** `GET /api/v1/predictions/no-show-eligible`, `POST /api/v1/predictions/no-show-batch`, `POST /api/v1/predictions/waiting-time/booking-preview`, `POST /api/v1/internal/jobs/no-show-predictions` (staff-only).
- **Threshold loading:** `get_no_show_threshold()` loads the F1-optimised threshold saved with the artifact; falls back to 0.5 only if the file is missing (logged as an error, not silent).

## A5. AI agent (Ayush)

- **Engine:** LangGraph `StateGraph` with a checkpointer (`integrated_hospital/app/agent/agent.py`): `START → understand_intent → {retrieve_knowledge | collect_details | discover_data | generate_response} → validate_transaction → show_summary → confirmation → execute_tool → generate_response → END`.
- **Closed intent set** (`integrated_hospital/app/agent/intents.py`): `general_conversation, hospital_information, appointment_booking, appointment_lookup, appointment_reschedule, appointment_cancellation, administrative_request, analytics_recommendation, billing_information, unsafe_clinical_request`. The LLM *proposes* an intent; `INTENT_ROUTING` **deterministically** derives `needs_rag` / `needs_transaction`, so the model cannot contradict the routing. Unknown intent falls back to a clarifying question.
- **How hallucination is prevented:** tools are `discover_departments / discover_doctors / discover_availability / discover_patient_appointments` — **no raw SQL**; the model can never invent an ID, doctor or slot because they come from tool results. The system prompt forbids claiming success unless the tool result says so.
- **Confirmation is structural:** no mutation executes unless `confirmed=True`; missing details trigger an interrupt; menus are answered by number or name.
- **Guardrails:** `unsafe_clinical_request` short-circuits to a guarded response with **no retrieval and no tools**; conversation capped at 12 turns; thread IDs namespaced `user-<uuid>-*` so there is **no cross-user session resume**; LLM failure returns an in-band friendly message, not a 500.
- **Retrieval specifics:** pgvector `match_knowledge_documents` over `knowledge_documents` / `document_chunks`, top-4, similarity threshold ≈ 0.40, keyword fallback if embeddings are unavailable; ingestion via `scripts/ingest_knowledge_base.py`.
- **Escape hatch:** `detect_intent_escape()` lets a user break out of a pending question — "cancel my appointment" mid-booking works instead of being trapped.
- **Payments:** the AI never processes payment. It routes to `/payments` (card/UPI/cash form workflow) or reception.
- **Suggestion chips available on `/assistant`:** Book an appointment · My appointments · Departments · Billing help · Raise a request · Visiting hours.

---

# Appendix B — Demo prep checklist (day before)

- [ ] **Book the golden-thread appointment ~24 hours out** (a slot tomorrow, if availability allows) so the same appointment is eligible for no-show scoring later. If nothing suitable is open, seed one.
- [ ] **Seed at least 2–3 appointments inside the T+24 h ± tolerance window** that are still `booked` — otherwise Param's No-Show tab shows an empty state.
- [ ] **Seed a checked-in visit** so the patient dashboard shows a live predicted wait (otherwise that card is absent).
- [ ] **Seed a completed appointment** so History, Feedback and Payments have content.
- [ ] **Pre-login three sessions in three browser profiles**: patient, staff, admin. Switching accounts live costs 30–45 seconds each time.
- [ ] **Reminders is not in the staff navbar** (`frontend/app.py`, staff `role_nav`) — navigate to `/reminders` by URL, or add `s_reminders` to `role_nav` before the demo.
- [ ] **Confirm LLM keys work** — `.env` has `LLM_*` and `EMBEDDING_MODEL`; test the assistant once end-to-end. If the LLM is down the assistant answers in-band and retrieval degrades to keyword search.
- [ ] **Bookings use a 20-day window** — pick a date with live availability for both the AI booking and Radhika's form path.
- [ ] **Run the Access Denied beat once as a patient** to confirm the redirect still lands on `pages/system/access_denied.py`.
- [ ] **Keep `:8000/docs` open in a background tab** in case Arif wants the 10-second engineering proof.
- [ ] **Rehearse the pause**: the summary screen and the refusal screen are the two moments that must hold for ~5 seconds each.

---

# Appendix C — Claims guardrails + open decisions

## ⚠ Decisions needed before rehearsal

1. **"Two models" vs. the actual build.** The brief says two (no-show, waiting-time). The repo also ships **bed-demand** and **patient-flow** forecasts, visible on the Forecasting tabs an evaluator can click. Choose one:
   - **(a)** Say *"two core models — no-show and waiting-time — plus two next-day operational forecasts"* (recommended; matches what's on screen), or
   - **(b)** Hide the Department Forecasts tab before the demo.

   Claiming "only two" while a third and fourth are on screen is the most likely question to ambush you.

2. **Trained model artifacts may be missing.** `integrated_hospital/app/ml/models/` contains only `__init__.py` — the `.pkl` files are gitignored. Inference then falls back to `rule_based_v1` / `heuristic_v1`, and **the Forecasting table prints that string in its "Model" column**. Either supply real artifacts before the demo, or have Param say: *"if a trained artifact isn't loaded, the service degrades to a documented rule-based fallback rather than failing silently — which is itself a deployment decision."* Saying nothing risks an evaluator reading the column.

3. **HIPAA.** The earlier script cited HIPAA; it cannot be evidenced. Use instead: *"aligned with healthcare privacy principles — minimum-necessary access, role scoping, audit logging"* — all three demonstrable on the Audit Logs screen.

## 🗣 Wording rules (all speakers)

- **Never** say "HIPAA compliant", "certified", or quote a standard we can't evidence.
- **Never** claim a percentage or ROI figure that isn't in the team's own measurements (§1.2 brackets are the only place numbers go).
- ML is always framed as **"operational predictions, not medical diagnosis."**
- AI is always framed as **"asks, you confirm, the system executes"** — never "the AI booked it for you" without the confirmation beat.
- Privacy is always framed as **"demonstrated control"**, never "guaranteed security."
- If asked something unknown: *"That's not something I can evidence today — we'll take it offline."* Never improvise a claim.
