"""
Focused tests for the doctor clinical workflow and the shared billing rule.

These tests run fully offline: the service layer is backed by an in-memory
PostgREST-compatible fake (no network, no Supabase) and the auth dependency
is exercised directly with fabricated AuthContext objects.

Covered critical paths (kept deliberately small):
  1. require_doctor accepts a linked doctor profile / rejects everything else
  2. doctor profile resolves profiles -> doctors -> departments
  3. a doctor only ever sees appointments assigned to them
  4. start service is rejected before check-in
  5. start service records the wait and the in-service status
  6. prescriptions / orders are gated by the service state
  7. prescription charges are derived server-side and refresh the invoice
  8. invoice = consultation + medicines + diagnostics (doctor view)
  9. the payment amount always comes from invoice_amount (never the client)
 10. patient appointment detail exposes records, doctor, department and bill
 11. staff check-in workflow is untouched (check-in ≠ start service)
 12. end service completes the visit exactly once

Usage:
    python -m pytest integrated_hospital/tests/test_doctor_workflow.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # integrated_hospital/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies.auth import AuthContext, require_doctor          # noqa: E402
from app.schema.patient import CreatePaymentRequest                    # noqa: E402
from app.services import audit_service                                 # noqa: E402
from app.services import billing_service                               # noqa: E402
from app.services import doctor_clinical_service as dcs                # noqa: E402
from app.services import patient_appointment_service as pas            # noqa: E402
from app.services import patient_payment_service as pps                # noqa: E402
from app.services import staff_appointment_service as sas              # noqa: E402
from app.utils.exceptions import ForbiddenError, InvalidOperationError  # noqa: E402


# ============================================================
# In-memory PostgREST-compatible fake
# ============================================================
class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _lt(left, right) -> bool:
    try:
        return left < right
    except TypeError:
        return str(left) < str(right)


class _Query:
    """Minimal chainable query builder covering the operators the
    service layer uses: select/insert/update, eq/neq/in_/lt/gte,
    not_.is_, order, range, count."""

    def __init__(self, client, table):
        self._client = client
        self._table = table
        self._op = "select"
        self._payload = None
        self._preds = []
        self._nulls = []
        self._orders = []
        self._range = None
        self._count = False
        self._single = False
        self._negate_next = False

    # -- chain helpers -------------------------------------------------
    def select(self, columns="*", count=None):
        self._count = count == "exact"
        return self

    def eq(self, col, val):
        self._preds.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._preds.append(("neq", col, val))
        return self

    def in_(self, col, vals):
        self._preds.append(("in", col, list(vals)))
        return self

    def lt(self, col, val):
        self._preds.append(("lt", col, val))
        return self

    def lte(self, col, val):
        self._preds.append(("lte", col, val))
        return self

    def gt(self, col, val):
        self._preds.append(("gt", col, val))
        return self

    def gte(self, col, val):
        self._preds.append(("gte", col, val))
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def is_(self, col, val):
        want_null = (val == "null")
        if self._negate_next:
            want_null = not want_null
        self._negate_next = False
        self._nulls.append((col, want_null))
        return self

    def order(self, col, desc=False):
        self._orders.append((col, desc))
        return self

    def range(self, lo, hi):
        self._range = (int(lo), int(hi))
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    # -- matching / execution -----------------------------------------
    @staticmethod
    def _is_null(cell) -> bool:
        return cell is None or cell == ""

    def _matches(self, row) -> bool:
        for op, col, val in self._preds:
            cell = row.get(col)
            if op == "eq":
                if cell != val and str(cell) != str(val):
                    return False
            elif op == "neq":
                if cell == val or str(cell) == str(val):
                    return False
            elif op == "in":
                if cell not in val:
                    return False
            elif cell is None:
                return False
            elif op == "lt" and not _lt(cell, val):
                return False
            elif op == "lte" and not (cell == val or _lt(cell, val)):
                return False
            elif op == "gt" and not _lt(val, cell):
                return False
            elif op == "gte" and not (cell == val or _lt(val, cell)):
                return False

        for col, want_null in self._nulls:
            if self._is_null(row.get(col)) != want_null:
                return False
        return True

    def _rows(self):
        return self._client.tables.setdefault(self._table, [])

    def execute(self):
        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for payload in payloads:
                stored = dict(payload)
                self._rows().append(stored)
                inserted.append(dict(stored))
            return _Result(inserted if not self._single else inserted[0])

        matched = [r for r in self._rows() if self._matches(r)]

        if self._op == "update":
            updated = []
            for row in matched:
                row.update(self._payload)
                updated.append(dict(row))
            return _Result(updated if not self._single else (updated[0] if updated else None))

        for col, desc in reversed(self._orders):
            matched = sorted(
                matched,
                key=lambda r: (r.get(col) is None, str(r.get(col) or "")),
                reverse=desc,
            )

        count = len(matched)
        if self._range is not None:
            lo, hi = self._range
            matched = matched[lo:hi + 1]

        data = [dict(r) for r in matched]
        if self._single:
            data = data[0] if data else None
        return _Result(data, count if self._count else None)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self, name)


# ============================================================
# Fixtures
# ============================================================
DOCTOR_ID = "doc-1"
OTHER_DOCTOR_ID = "doc-2"
PATIENT_ID = "user-patient"
OTHER_PATIENT_ID = "user-patient-2"

SERVICES_WITH_CLIENT = (billing_service, dcs, pas, pps, sas, audit_service)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_tables() -> dict:
    """Seed data covering both doctors, two patients and the lifecycle."""
    now = _now()

    profiles = [
        {
            "user_id": "user-doctor",
            "role": "doctor",
            "doctor_id": DOCTOR_ID,
            "status": "active",
            "full_name": "Asha Rao",
            "email": "asha.rao@example.com",
        },
        {
            "user_id": "user-doctor-2",
            "role": "doctor",
            "doctor_id": OTHER_DOCTOR_ID,
            "status": "active",
            "full_name": "Ben Iyer",
            "email": "ben.iyer@example.com",
        },
        {
            "user_id": PATIENT_ID,
            "role": "patient",
            "doctor_id": None,
            "status": "active",
            "full_name": "Priya Patient",
            "email": "priya@example.com",
        },
        {
            "user_id": OTHER_PATIENT_ID,
            "role": "patient",
            "doctor_id": None,
            "status": "active",
            "full_name": "Ravi Patient",
            "email": "ravi@example.com",
        },
        {"user_id": "user-staff", "role": "staff", "status": "active", "full_name": "Desk Staff"},
    ]

    doctors = [
        {
            "doctor_id": DOCTOR_ID,
            "full_name": "Asha Rao",
            "specialization": "Cardiology",
            "department_id": "dept-1",
            "status": "active",
            "experience_years": 12,
        },
        {
            "doctor_id": OTHER_DOCTOR_ID,
            "full_name": "Ben Iyer",
            "specialization": "Neurology",
            "department_id": "dept-1",
            "status": "active",
            "experience_years": 8,
        },
    ]

    departments = [
        {"department_id": "dept-1", "name": "Cardiology", "status": "active"},
    ]

    def appointment(appt_id, doctor_id, patient_id, **over):
        base = {
            "appointment_id": appt_id,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "department_id": "dept-1",
            "department_name": "Cardiology",
            "appointment_status": "booked",
            "scheduled_start": (now + timedelta(days=1)).isoformat(),
            "scheduled_end": (now + timedelta(days=1, minutes=30)).isoformat(),
            "booked_at": (now - timedelta(days=2)).isoformat(),
            "actual_checkin_time": None,
            "actual_service_start": None,
            "actual_service_end": None,
            "actual_wait_minutes": None,
            "consultation_charge": 500.0,
            "invoice_amount": 500.0,
            "payment_status_at_booking": "pending",
            "reason": "Follow-up",
            "created_at": (now - timedelta(days=2)).isoformat(),
            "updated_at": (now - timedelta(days=2)).isoformat(),
        }
        base.update(over)
        return base

    appointments = [
        # Assigned to our doctor, not checked in yet.
        appointment("appt-booked", DOCTOR_ID, PATIENT_ID),
        # Assigned, checked in 10 minutes ago — ready to start service.
        appointment(
            "appt-waiting",
            DOCTOR_ID,
            PATIENT_ID,
            actual_checkin_time=(now - timedelta(minutes=10)).isoformat(),
        ),
        # Assigned, consultation already running.
        appointment(
            "appt-in-service",
            DOCTOR_ID,
            PATIENT_ID,
            appointment_status="in_consultation",
            actual_checkin_time=(now - timedelta(minutes=20)).isoformat(),
            actual_service_start=(now - timedelta(minutes=5)).isoformat(),
        ),
        # Belongs to the other doctor — must stay invisible.
        appointment("appt-other-doctor", OTHER_DOCTOR_ID, PATIENT_ID),
        # Other patient's visit with our doctor.
        appointment("appt-other-patient", DOCTOR_ID, OTHER_PATIENT_ID),
        # Finished visit.
        appointment(
            "appt-completed",
            DOCTOR_ID,
            PATIENT_ID,
            appointment_status="completed",
            actual_checkin_time=(now - timedelta(hours=2)).isoformat(),
            actual_service_start=(now - timedelta(hours=1, minutes=50)).isoformat(),
            actual_service_end=(now - timedelta(hours=1, minutes=20)).isoformat(),
            actual_wait_minutes=10.0,
        ),
    ]

    medicines = [
        {"medicine_id": "med-1", "name": "Amoxicillin 500mg", "charge": 120.5,
         "currency": "INR", "status": "active"},
        {"medicine_id": "med-retired", "name": "Retired Drug", "charge": 40.0,
         "currency": "INR", "status": "retired"},
    ]

    diagnostic_tests = [
        {"test_id": "test-1", "name": "ECG", "charge": 900.0,
         "currency": "INR", "status": "active"},
        {"test_id": "test-retired", "name": "Retired Panel", "charge": 300.0,
         "currency": "INR", "status": "retired"},
    ]

    slot_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    doctor_availability = [
        {
            "availability_id": "slot-1",
            "doctor_id": DOCTOR_ID,
            "department_id": "dept-1",
            "slot_date": slot_date,
            "start_time": "10:30:00",
            "end_time": "11:00:00",
            "status": "available",
            "slot_capacity": 3,
            "booked_count": 0,
        },
    ]

    return {
        "profiles": profiles,
        "doctors": doctors,
        "departments": departments,
        "appointments": appointments,
        "doctor_availability": doctor_availability,
        "medicines": medicines,
        "diagnostic_tests": diagnostic_tests,
        "prescriptions": [],
        "diagnostic_test_orders": [],
        "payments": [],
        "audit_logs": [],
    }


@pytest.fixture
def db():
    return build_tables()


@pytest.fixture
def client(db, monkeypatch):
    fake = FakeSupabase(db)
    for module in SERVICES_WITH_CLIENT:
        monkeypatch.setattr(module, "get_supabase_admin_client", lambda fake=fake: fake)
    # Check-in must never depend on the ML model inside these tests.
    monkeypatch.setattr(
        sas, "predict_waiting_time",
        lambda appointment_id: {"prediction_status": "failed", "prediction": {}},
    )
    # Deterministic payment outcome so assertions can be exact.
    monkeypatch.setattr(
        pps, "simulate_payment_outcome",
        lambda: {"status": "success", "transaction_reference": "SIM-SUCCESS-TEST"},
    )
    return fake


def _appointment(db, appointment_id: str) -> dict:
    for row in db["appointments"]:
        if row["appointment_id"] == appointment_id:
            return row
    raise AssertionError(f"appointment {appointment_id} not found")


def _start_service(appointment_id: str, appointment: dict) -> None:
    """Helper: move an appointment into the in-service state."""
    appointment["actual_checkin_time"] = appointment["actual_checkin_time"] or (
        _now() - timedelta(minutes=10)
    ).isoformat()
    if not appointment.get("actual_service_start"):
        dcs.start_doctor_service(
            doctor_id=DOCTOR_ID,
            appointment_id=appointment_id,
            actor_id="user-doctor",
            actor_role="doctor",
        )


# ============================================================
# 1. Auth gate
# ============================================================
def test_require_doctor_only_admits_linked_doctors():
    doctor = AuthContext(
        user=object(), access_token="t",
        profile={"role": "doctor", "doctor_id": DOCTOR_ID, "status": "active"},
    )
    assert require_doctor(doctor) is doctor

    with pytest.raises(HTTPException) as exc:
        require_doctor(AuthContext(
            user=object(), access_token="t",
            profile={"role": "patient", "status": "active"},
        ))
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        require_doctor(AuthContext(
            user=object(), access_token="t",
            profile={"role": "doctor", "doctor_id": None, "status": "active"},
        ))
    assert exc.value.status_code == 403


# ============================================================
# 2. Profile chain
# ============================================================
def test_doctor_profile_resolves_doctor_and_department(client, db):
    profile = next(p for p in db["profiles"] if p["doctor_id"] == DOCTOR_ID)

    data = dcs.get_doctor_profile(profile=profile)

    assert data["profile"] is profile
    assert data["doctor"]["doctor_id"] == DOCTOR_ID
    assert data["department"]["name"] == "Cardiology"


# ============================================================
# 3. Ownership scoping
# ============================================================
def test_doctor_only_sees_their_own_assignments(client, db):
    result = dcs.list_doctor_appointments(doctor_id=DOCTOR_ID, limit=50)
    ids = {a["appointment_id"] for a in result["appointments"]}

    assert "appt-booked" in ids
    assert "appt-in-service" in ids
    assert "appt-other-doctor" not in ids
    assert result["total"] == len(ids)

    with pytest.raises(ForbiddenError):
        dcs.get_doctor_appointment(
            doctor_id=DOCTOR_ID, appointment_id="appt-other-doctor"
        )


# ============================================================
# 4. Start service requires a check-in
# ============================================================
def test_start_service_is_rejected_before_check_in(client, db):
    with pytest.raises(InvalidOperationError) as exc:
        dcs.start_doctor_service(
            doctor_id=DOCTOR_ID,
            appointment_id="appt-booked",
            actor_id="user-doctor",
            actor_role="doctor",
        )
    assert "check-in" in str(exc.value).lower()
    assert _appointment(db, "appt-booked")["appointment_status"] == "booked"


# ============================================================
# 5. Start service records wait + in-service status
# ============================================================
def test_start_service_records_wait_and_status(client, db):
    result = dcs.start_doctor_service(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-waiting",
        actor_id="user-doctor",
        actor_role="doctor",
    )

    assert result["appointment_status"] == "in_consultation"
    assert result["actual_service_start"]
    wait = float(result["actual_wait_minutes"])
    assert 9.0 <= wait <= 12.0  # checked in ~10 minutes ago

    # Starting twice is refused.
    with pytest.raises(InvalidOperationError):
        dcs.start_doctor_service(
            doctor_id=DOCTOR_ID,
            appointment_id="appt-waiting",
            actor_id="user-doctor",
            actor_role="doctor",
        )


# ============================================================
# 6. Clinical orders are gated by the service state
# ============================================================
def test_clinical_orders_are_gated_by_service_state(client, db):
    kwargs = dict(
        doctor_id=DOCTOR_ID,
        medicine_id="med-1",
        quantity=1,
        dosage="1 tablet",
        frequency="Twice daily",
        duration_days=5,
        actor_id="user-doctor",
        actor_role="doctor",
    )

    # Not checked in yet.
    with pytest.raises(InvalidOperationError) as exc:
        dcs.create_prescription(appointment_id="appt-booked", **kwargs)
    assert "checked in" in str(exc.value).lower()

    # Checked in, but the consultation has not started.
    with pytest.raises(InvalidOperationError) as exc:
        dcs.create_prescription(appointment_id="appt-waiting", **kwargs)
    assert "service has not started" in str(exc.value).lower()

    # Visit already finished.
    with pytest.raises(InvalidOperationError):
        dcs.create_prescription(appointment_id="appt-completed", **kwargs)

    # Someone else's appointment is a permission error, not a state error.
    with pytest.raises(ForbiddenError):
        dcs.create_prescription(appointment_id="appt-other-doctor", **kwargs)

    # Nothing was written for any of the refused attempts.
    assert db["prescriptions"] == []
    assert _appointment(db, "appt-booked")["invoice_amount"] == 500.0


# ============================================================
# 7. Server-derived prescription charges + invoice refresh
# ============================================================
def test_prescription_charges_are_derived_server_side(client, db):
    _start_service("appt-in-service", _appointment(db, "appt-in-service"))

    result = dcs.create_prescription(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-in-service",
        medicine_id="med-1",
        quantity=2,
        dosage="1 capsule",
        frequency="Twice daily",
        duration_days=7,
        instructions="After food",
        actor_id="user-doctor",
        actor_role="doctor",
    )

    prescription = result["prescription"]
    # patient / doctor / charge come from the appointment + catalog only.
    assert prescription["patient_id"] == PATIENT_ID
    assert prescription["doctor_id"] == DOCTOR_ID
    assert prescription["unit_charge"] == 120.5
    assert prescription["total_amount"] == 241.0

    stored = _appointment(db, "appt-in-service")
    assert stored["consultation_charge"] == 500.0
    assert stored["invoice_amount"] == 741.0  # 500 + 241

    assert any(
        row.get("action") == "create_prescription" for row in db["audit_logs"]
    ), "prescription creation must be audited"


# ============================================================
# 8. Billing formula (doctor view)
# ============================================================
def test_invoice_is_consultation_plus_medicines_plus_diagnostics(client, db):
    _start_service("appt-in-service", _appointment(db, "appt-in-service"))

    dcs.create_prescription(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-in-service",
        medicine_id="med-1",
        quantity=2,
        dosage="1 capsule",
        frequency="Twice daily",
        duration_days=7,
        actor_id="user-doctor",
        actor_role="doctor",
    )
    dcs.create_diagnostic_order(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-in-service",
        test_id="test-1",
        quantity=2,
        priority="routine",
        actor_id="user-doctor",
        actor_role="doctor",
    )

    detail = dcs.get_doctor_appointment(
        doctor_id=DOCTOR_ID, appointment_id="appt-in-service"
    )
    bill = detail["billing_summary"]

    assert bill["consultation_charge"] == 500.0
    assert bill["medicine_total"] == 241.0
    assert bill["diagnostic_total"] == 1800.0
    assert bill["final_total"] == 2541.0
    assert bill["currency"] == "INR"

    assert _appointment(db, "appt-in-service")["invoice_amount"] == 2541.0
    assert len(detail["prescriptions"]) == 1
    assert len(detail["diagnostic_test_orders"]) == 1
    assert detail["prescriptions"][0]["medicine_name"] == "Amoxicillin 500mg"
    assert detail["diagnostic_test_orders"][0]["test_name"] == "ECG"


# ============================================================
# 9. Payment amount comes from the invoice, never the client
# ============================================================
def test_payment_amount_is_read_from_invoice_amount(client, db):
    stored = _appointment(db, "appt-in-service")
    stored["invoice_amount"] = 2541.0

    payment = pps.create_payment(
        patient_id=PATIENT_ID,
        appointment_id="appt-in-service",
        payment_method="upi",
    )

    assert payment["amount"] == 2541.0
    assert payment["status"] == "success"

    # The request schema simply has no amount field to trust.
    request = CreatePaymentRequest(
        appointment_id="appt-in-service", amount=1.0, payment_method="card"
    )
    assert not hasattr(request, "amount")

    # Fallback: appointments booked before invoice_amount existed.
    legacy = _appointment(db, "appt-other-patient")
    legacy["invoice_amount"] = None
    legacy["consultation_charge"] = 650.0

    payment = pps.create_payment(
        patient_id=OTHER_PATIENT_ID,
        appointment_id="appt-other-patient",
        payment_method="cash",
    )
    assert payment["amount"] == 650.0


# ============================================================
# 10. Patient appointment detail
# ============================================================
def test_patient_appointment_detail_exposes_records_and_bill(client, db):
    _start_service("appt-in-service", _appointment(db, "appt-in-service"))
    dcs.create_prescription(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-in-service",
        medicine_id="med-1",
        quantity=1,
        dosage="1 tablet",
        frequency="Once daily",
        duration_days=3,
        actor_id="user-doctor",
        actor_role="doctor",
    )

    detail = pas.get_patient_appointment(
        patient_id=PATIENT_ID, appointment_id="appt-in-service"
    )

    assert detail["doctor"]["full_name"] == "Asha Rao"
    assert detail["department"]["name"] == "Cardiology"
    assert len(detail["prescriptions"]) == 1
    assert detail["diagnostic_test_orders"] == []
    assert detail["billing_summary"]["final_total"] == 620.5  # 500 + 120.5

    # Patient scoping is unchanged: another patient's visit is refused.
    with pytest.raises(ForbiddenError):
        pas.get_patient_appointment(
            patient_id=OTHER_PATIENT_ID, appointment_id="appt-in-service"
        )


# ============================================================
# 11. Staff check-in workflow is untouched
# ============================================================
def test_staff_check_in_stays_separate_from_doctor_service(client, db):
    checked_in = sas.check_in_appointment(
        appointment_id="appt-booked",
        actor_id="user-staff",
        actor_role="staff",
    )

    assert checked_in["actual_checkin_time"]
    # Check-in alone never starts the consultation or changes the status.
    assert checked_in["appointment_status"] == "booked"
    assert not checked_in.get("actual_service_start")
    assert int(checked_in["patients_ahead_at_checkin"]) >= 0

    # A finished visit cannot be checked in again.
    with pytest.raises(InvalidOperationError):
        sas.check_in_appointment(
            appointment_id="appt-completed",
            actor_id="user-staff",
            actor_role="staff",
        )


# ============================================================
# 12. End service
# ============================================================
def test_end_service_completes_the_visit_exactly_once(client, db):
    # Service never started for this visit.
    with pytest.raises(InvalidOperationError):
        dcs.end_doctor_service(
            doctor_id=DOCTOR_ID,
            appointment_id="appt-booked",
            actor_id="user-doctor",
            actor_role="doctor",
        )

    _start_service("appt-waiting", _appointment(db, "appt-waiting"))
    ended = dcs.end_doctor_service(
        doctor_id=DOCTOR_ID,
        appointment_id="appt-waiting",
        actor_id="user-doctor",
        actor_role="doctor",
    )

    assert ended["appointment_status"] == "completed"
    assert ended["actual_service_end"]

    with pytest.raises(InvalidOperationError):
        dcs.end_doctor_service(
            doctor_id=DOCTOR_ID,
            appointment_id="appt-waiting",
            actor_id="user-doctor",
            actor_role="doctor",
        )
