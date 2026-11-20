-- Release 2026-11-20 - Phase P3 (DEC-62, DEC-63; user Q8 + Q25): Unboxing = one video per carton +
-- one optional "document found in carton". The RM Missing Document Exception (DEC-03) is retired.
--
-- Apply to production AFTER migration 20261120000300_p3_unboxing_carton_document_g02.sql and after
-- deploying the backend + frontend of P3. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261120_p3_unboxing.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
--
-- 1. The Replacement Manager no longer decides missing-document exceptions: revoke the role's
--    unboxing.approve grant (it guarded only that decision). The permission itself stays in the
--    catalogue (Super Admin keeps every permission; nothing is dropped).
-- 2. Deactivate the two exception notification rules (no event publishes them any more).
-- 3. There is no journey step of its own for the exception (it lived inside the RM's Approvals
--    tool, which stays for CSR approvals and item corrections), so no journey row changes.
-- 4. Report legacy GSs that were waiting for an exception (released by the migration).
begin;

delete from public.role_permissions rp
 using public.roles r, public.permissions p
 where rp.role_id = r.id and rp.permission_id = p.id
   and r.code = 'REPLACEMENT_MANAGER'
   and p.module_code = 'unboxing' and p.action = 'approve';

update public.notification_rules
   set is_active = false
 where event_type in ('MISSING_DOC_EXCEPTION_REQUESTED', 'MISSING_DOC_EXCEPTION_DECIDED')
   and is_active;

do $$
declare
  v_count integer;
  v_list  text;
begin
  select count(*), string_agg(g.gs_no, ', ' order by g.gs_no)
    into v_count, v_list
    from public.goods_slips g
   where g.status = 'UNBOXING'
     and exists (select 1 from public.missing_doc_exceptions e
                  where e.gs_id = g.id and e.status in ('REQUESTED', 'REJECTED'));
  raise notice 'DEC-63: % GS(s) in UNBOXING had a requested / rejected exception; they now complete on carton videos only: %',
    v_count, coalesce(v_list, '-');
end
$$;

commit;
