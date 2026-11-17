-- Release 2026-11-17 - DEC-53: Counting & Categorisation merged into one step.
-- The migration 20261117000200_merge_counting_categorisation.sql (guards + journey label) ships
-- with `supabase db push`; this snippet applies the matching seed change to an existing database:
-- the Inward Verifier menu loses its separate "Categorisation" entry (the "Counting &
-- Categorisation" entry's queue now also lists slips the RM sent back). Idempotent; safe to re-run.
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261117_merge_counting_categorisation.sql
-- Same change as in supabase/seed.sql (DATABASE_MIGRATION_GUIDE.md section 7.3).
begin;
delete from public.role_journey_steps rjs
 using public.roles r, public.journey_steps s
 where rjs.role_id = r.id
   and rjs.journey_step_id = s.id
   and r.code = 'INWARD_VERIFIER'
   and s.code = 'CATEGORISATION';
commit;
