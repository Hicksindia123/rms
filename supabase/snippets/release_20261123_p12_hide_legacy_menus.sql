-- Release 2026-11-23 - Phase P12 clean-up (DEC-72): hide the last menus that only serve legacy
-- goods slips, each once no legacy goods slip needs it, and drop the two legacy widgets from the
-- RM / RE dashboards. Rows are kept (Admin -> Role Journeys can
-- switch a step back on).
--   FINAL_ACTIONS  RM "Final Actions" (DEC-57 rounds); the Intermediate Stores analyse now (DEC-69).
--   APPROVALS      RM "Approvals": Complete Sales Return approval + item line corrections
--                  (CSR_APPROVAL_PENDING / INSPECTION). A Sales Return now parks in
--                  SALES_RETURN_HOLD (DEC-64).
--   INSPECTION     RE "Inspection & Grading" (INSPECTION); unreachable since the categorisation
--                  lock (DEC-64).
--
-- Apply to production AFTER release_20261123_p11_accounts_replacement_slip.sql. Idempotent; safe to
-- re-run. A menu whose legacy queue is not empty stays and the snippet only reports; run it again
-- once those goods slips have moved on.
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261123_p12_hide_legacy_menus.sql
begin;

do $$
declare
  v_final      integer;
  v_approvals  integer;
  v_inspection integer;
begin
  -- Same scope as the FINAL_ACTIONS queue (journeys repository): legacy goods slips held at the old
  -- Intermediate Store, or with a legacy round still to re-action.
  select count(*) into v_final from public.goods_slips g
   where g.status = 'HELD_AT_INTERMEDIATE_STORE'
      or (g.status in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')
          and not rms_private.gs_on_store_flow(g.id)
          and exists (select 1 from public.rm_item_actions a
                        join public.gs_items gi on gi.id = a.gs_item_id
                       where gi.gs_id = g.id and a.is_current and a.action_code = 'PENDING_BP'));
  select (select count(*) from public.goods_slips where status = 'CSR_APPROVAL_PENDING')
       + (select count(*) from public.gs_item_corrections where status = 'REQUESTED')
    into v_approvals;
  select count(*) into v_inspection from public.goods_slips where status = 'INSPECTION';

  if v_final = 0 then
    update public.journey_steps set is_active = false where code = 'FINAL_ACTIONS' and is_active;
    raise notice 'DEC-72: FINAL_ACTIONS hidden';
  else
    raise notice 'DEC-72: FINAL_ACTIONS kept: % legacy goods slip(s); re-run when 0', v_final;
  end if;
  if v_approvals = 0 then
    update public.journey_steps set is_active = false where code = 'APPROVALS' and is_active;
    raise notice 'DEC-72: APPROVALS hidden';
  else
    raise notice 'DEC-72: APPROVALS kept: % pending CSR approval(s) / correction(s); re-run when 0',
      v_approvals;
  end if;
  if v_inspection = 0 then
    update public.journey_steps set is_active = false where code = 'INSPECTION' and is_active;
    raise notice 'DEC-72: INSPECTION hidden';
  else
    raise notice 'DEC-72: INSPECTION kept: % goods slip(s) in INSPECTION; re-run when 0', v_inspection;
  end if;
end
$$;

-- DEC-72: the Replacement Manager / Replacement Executive dashboards drop the two legacy widgets
-- (the widgets stay in the catalogue; other admin layout edits are kept).
update public.role_dashboard_layouts l
   set widgets = coalesce((select jsonb_agg(x order by o)
                             from jsonb_array_elements(l.widgets) with ordinality as w(x, o)
                            where x->>'code' not in ('CSR_APPROVALS_PENDING', 'INSPECTIONS_PENDING')),
                          '[]'::jsonb)
  from public.roles r
 where r.id = l.role_id
   and r.code in ('REPLACEMENT_MANAGER', 'INWARD_VERIFIER')
   and exists (select 1 from jsonb_array_elements(l.widgets) x
                where x->>'code' in ('CSR_APPROVALS_PENDING', 'INSPECTIONS_PENDING'));

commit;
