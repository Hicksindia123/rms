-- Change plan 2026-11-12, Phase 10 fix-forward: the trigger function added by
-- 20261114000300_ph10_role_journeys.sql must not be executable by anon / authenticated
-- (same rule as every rms_private function; supabase/tests/01_schema.test.sql test 13).
revoke all on function rms_private.journey_steps_code_immutable() from public, anon, authenticated;
