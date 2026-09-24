-- =====================================================================
-- Migration: doctor clinical workflow
-- File: integrated_hospital/migrations/20260924_doctor_clinical_workflow.sql
--
-- Run MANUALLY in the Supabase SQL editor (or `psql`) for the project the
-- backend points at. Nothing in the application executes this file, and it
-- contains no destructive statements: every statement is idempotent and
-- re-running it is safe.
--
-- What it does:
--   1. Adds appointments.consultation_charge (base fee of a visit) and
--      backfills it, so the invoice can be recomputed as
--          invoice_amount = consultation_charge
--                         + SUM(prescriptions.total_amount)
--                         + SUM(diagnostic_test_orders.total_amount)
--   2. Backfills appointments.invoice_amount only where it is NULL.
--   3. Enables row level security and adds doctor policies:
--        appointments            -> SELECT (own appointments only)
--        prescriptions           -> SELECT (own prescriptions / own appointments)
--        diagnostic_test_orders  -> SELECT (own orders / own appointments)
--        medicines               -> SELECT (read-only catalog)
--        diagnostic_tests        -> SELECT (read-only catalog)
--
-- Notes:
--   * Doctors have NO insert/update/delete policies anywhere. All clinical
--     writes go through the FastAPI /doctor endpoints, which use the service
--     role client and derive patient_id / unit_charge / total_amount /
--     invoice_amount on the server.
--   * private.has_role() and private.current_role() are used as-is and are
--     never modified.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. appointments.consultation_charge
-- ---------------------------------------------------------------------
ALTER TABLE public.appointments
    ADD COLUMN IF NOT EXISTS consultation_charge numeric(10,2);

COMMENT ON COLUMN public.appointments.consultation_charge IS
    'Base consultation fee for the visit. appointments.invoice_amount remains the final amount: consultation_charge + SUM(prescriptions.total_amount) + SUM(diagnostic_test_orders.total_amount).';

-- Backfill every appointment booked before the column existed.
UPDATE public.appointments
SET consultation_charge = 500.00
WHERE consultation_charge IS NULL;

-- Backfill the final invoice only where it was never written; existing
-- values are left untouched.
UPDATE public.appointments a
SET invoice_amount = COALESCE(a.consultation_charge, 500.00)
    + COALESCE((
        SELECT SUM(p.total_amount)
        FROM public.prescriptions p
        WHERE p.appointment_id = a.appointment_id
      ), 0)
    + COALESCE((
        SELECT SUM(o.total_amount)
        FROM public.diagnostic_test_orders o
        WHERE o.appointment_id = a.appointment_id
      ), 0)
WHERE a.invoice_amount IS NULL;

-- ---------------------------------------------------------------------
-- 2. Row level security — enable (no-op when already enabled)
-- ---------------------------------------------------------------------
ALTER TABLE public.appointments            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prescriptions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.diagnostic_test_orders  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medicines               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.diagnostic_tests        ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- 3. Doctor policies (idempotent: each is created only when missing)
-- ---------------------------------------------------------------------

-- Helper expression used below: the doctor_id of the calling user, taken
-- from their own profile row (auth.uid() -> profiles -> doctor_id).
--
--   (SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid())

-- 3a. Appointments: a doctor reads only the visits assigned to them.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename   = 'appointments'
          AND policyname  = 'doctor_select_own_appointments'
    ) THEN
        CREATE POLICY doctor_select_own_appointments
            ON public.appointments
            FOR SELECT
            TO authenticated
            USING (
                private.has_role('doctor')
                AND doctor_id = (
                    SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- 3b. Prescriptions: the prescribing doctor, plus anything recorded against
--     an appointment assigned to them (orders recorded by the desk).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename   = 'prescriptions'
          AND policyname  = 'doctor_select_own_prescriptions'
    ) THEN
        CREATE POLICY doctor_select_own_prescriptions
            ON public.prescriptions
            FOR SELECT
            TO authenticated
            USING (
                private.has_role('doctor')
                AND (
                    doctor_id = (
                        SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid()
                    )
                    OR appointment_id IN (
                        SELECT a.appointment_id
                        FROM public.appointments a
                        WHERE a.doctor_id = (
                            SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid()
                        )
                    )
                )
            );
    END IF;
END $$;

-- 3c. Diagnostic test orders: same rule as prescriptions.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename   = 'diagnostic_test_orders'
          AND policyname  = 'doctor_select_own_diagnostic_orders'
    ) THEN
        CREATE POLICY doctor_select_own_diagnostic_orders
            ON public.diagnostic_test_orders
            FOR SELECT
            TO authenticated
            USING (
                private.has_role('doctor')
                AND (
                    doctor_id = (
                        SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid()
                    )
                    OR appointment_id IN (
                        SELECT a.appointment_id
                        FROM public.appointments a
                        WHERE a.doctor_id = (
                            SELECT p.doctor_id FROM public.profiles p WHERE p.user_id = auth.uid()
                        )
                    )
                )
            );
    END IF;
END $$;

-- 3d. Read-only catalogs for prescribing / ordering. No write policies are
--     added for doctors on any table.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename   = 'medicines'
          AND policyname  = 'doctor_select_medicines'
    ) THEN
        CREATE POLICY doctor_select_medicines
            ON public.medicines
            FOR SELECT
            TO authenticated
            USING (private.has_role('doctor'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename   = 'diagnostic_tests'
          AND policyname  = 'doctor_select_diagnostic_tests'
    ) THEN
        CREATE POLICY doctor_select_diagnostic_tests
            ON public.diagnostic_tests
            FOR SELECT
            TO authenticated
            USING (private.has_role('doctor'));
    END IF;
END $$;

COMMIT;
