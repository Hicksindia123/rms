-- =============================================================================
-- Test File: 20_credit_notes.test.sql
-- P3-06 Credit Notes, RM CN Decision, Accounts Verification & Rate Guards (G-13, G-14, DEC-22)
-- =============================================================================

begin;
select plan(14);

select has_table('public', 'rm_cn_decisions', 'rm_cn_decisions table exists');
select has_table('public', 'rm_cn_decision_lines', 'rm_cn_decision_lines table exists');
select has_table('public', 'credit_notes', 'credit_notes table exists');
select has_table('public', 'credit_note_lines', 'credit_note_lines table exists');
select has_table('public', 'rate_verifications', 'rate_verifications table exists');

select has_trigger('public', 'credit_notes', 'trg_credit_notes_g13', 'G-13 trigger on credit_notes exists');
select has_trigger('public', 'credit_note_lines', 'trg_credit_note_lines_g13', 'G-13 trigger on credit_note_lines exists');
select has_trigger('public', 'credit_notes', 'trg_credit_notes_g14', 'G-14 trigger on credit_notes exists');

-- Test fixtures
set local session_replication_role = replica;

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000e601', 'pgtap-p306@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P306 Test User"}'::jsonb)
on conflict do nothing;

insert into public.profiles (id, full_name) values
  ('00000000-0000-0000-0000-00000000e601', 'P306 Test User')
on conflict do nothing;

insert into public.parties (id, code, name) values
  ('00000000-0000-0000-0000-00000000e602', 'PTY-P306', 'Party P306')
on conflict do nothing;

insert into public.product_categories (id, code, name)
values ('00000000-0000-0000-0000-00000000e610', 'P306_CAT', 'P306 Category')
on conflict do nothing;

insert into public.products (id, code, name, category_id)
values ('00000000-0000-0000-0000-00000000e611', 'P306-PROD', 'P306 Product',
        '00000000-0000-0000-0000-00000000e610')
on conflict do nothing;

insert into public.stock_items (id, item_kind, product_id)
values ('00000000-0000-0000-0000-00000000e612', 'FINISHED_GOOD', '00000000-0000-0000-0000-00000000e611')
on conflict do nothing;

insert into public.stock_lots (id, stock_item_id, condition_class) values
  ('00000000-0000-0000-0000-00000000e620', '00000000-0000-0000-0000-00000000e612', 'FUNCTIONAL_GOOD'),
  ('00000000-0000-0000-0000-00000000e621', '00000000-0000-0000-0000-00000000e612', 'FUNCTIONAL_REPAIRED')
on conflict do nothing;

insert into public.goods_slips (
  id, gs_no, party_id, workflow_version_id, status, delivery_mode_code, courier_name, docket_no, box_count, carton_count, created_by
) values (
  '00000000-0000-0000-0000-00000000e630', 'GS-PGTAP-P306',
  '00000000-0000-0000-0000-00000000e602',
  (select id from public.workflow_versions where status = 'PUBLISHED' limit 1),
  'IN_PROCESS', 'COURIER_PARCEL', 'BlueDart', 'DKT-P306', 1, 1,
  '00000000-0000-0000-0000-00000000e601'
) on conflict do nothing;

insert into public.gs_items (
  id, gs_id, line_no, product_id, category_id, documented_qty, received_qty, created_by
) values (
  '00000000-0000-0000-0000-00000000e631', '00000000-0000-0000-0000-00000000e630',
  1, '00000000-0000-0000-0000-00000000e611', '00000000-0000-0000-0000-00000000e610',
  5, 5, '00000000-0000-0000-0000-00000000e601'
) on conflict do nothing;

set local session_replication_role = origin;

-- 1. Test G-13: Cannot create credit note without an RM ALLOW_CN decision
select throws_matching(
  $$
    insert into public.credit_notes (
      id, gs_id, cn_type_code, status, created_by
    ) values (
      '00000000-0000-0000-0000-00000000e640',
      '00000000-0000-0000-0000-00000000e630',
      'GENERAL_CN', 'DRAFT',
      '00000000-0000-0000-0000-00000000e601'
    )
  $$,
  'G-13.*ALLOW_CN',
  'G-13: Cannot create Credit Note without RM ALLOW_CN decision'
);

-- Now insert RM ALLOW_CN decision for this GS
insert into public.rm_cn_decisions (
  id, gs_id, decision_by, is_current
) values (
  '00000000-0000-0000-0000-00000000e650',
  '00000000-0000-0000-0000-00000000e630',
  '00000000-0000-0000-0000-00000000e601',
  true
);

insert into public.rm_cn_decision_lines (
  decision_id, gs_item_id, decision_code, qty
) values (
  '00000000-0000-0000-0000-00000000e650',
  '00000000-0000-0000-0000-00000000e631',
  'ALLOW_CN', 5
);

-- 2. Test G-13: GST_CN requires gst_portal_code = GST_REFLECTED (P3-08: enforced at every status
--    once the portal result is recorded; a draft before the portal check is allowed)
select throws_matching(
  $$
    insert into public.credit_notes (
      id, gs_id, cn_type_code, gst_portal_code, status, created_by
    ) values (
      '00000000-0000-0000-0000-00000000e641',
      '00000000-0000-0000-0000-00000000e630',
      'GST_CN', 'GST_NOT_REFLECTED', 'DRAFT',
      '00000000-0000-0000-0000-00000000e601'
    )
  $$,
  'G-13.*GST Credit Note requires return to be reflected on GST portal',
  'G-13: GST_CN without GST_REFLECTED is blocked'
);

-- 3. Test G-13: GST_NOT_REFLECTED permits only JV_ONLY
select throws_matching(
  $$
    insert into public.credit_notes (
      id, gs_id, cn_type_code, gst_portal_code, status, created_by
    ) values (
      '00000000-0000-0000-0000-00000000e642',
      '00000000-0000-0000-0000-00000000e630',
      'GENERAL_CN', 'GST_NOT_REFLECTED', 'DRAFT',
      '00000000-0000-0000-0000-00000000e601'
    )
  $$,
  'G-13.*Return not reflected on GST portal permits only JV_ONLY',
  'G-13: Return not reflected permits only JV_ONLY'
);

-- Insert valid JV_ONLY Credit Note
insert into public.credit_notes (
  id, gs_id, cn_type_code, gst_portal_code, status, created_by
) values (
  '00000000-0000-0000-0000-00000000e643',
  '00000000-0000-0000-0000-00000000e630',
  'JV_ONLY', 'GST_NOT_REFLECTED', 'DRAFT',
  '00000000-0000-0000-0000-00000000e601'
);

-- 4. Test G-13: Cumulative quantity check
select throws_matching(
  $$
    insert into public.credit_note_lines (
      credit_note_id, gs_item_id, line_no, qty
    ) values (
      '00000000-0000-0000-0000-00000000e643',
      '00000000-0000-0000-0000-00000000e631',
      1, 10
    )
  $$,
  'G-13.*exceeds allowed qty',
  'G-13: Line quantity exceeding allowed quantity is blocked'
);

-- Insert valid line with qty = 5
insert into public.credit_note_lines (
  id, credit_note_id, gs_item_id, line_no, qty
) values (
  '00000000-0000-0000-0000-00000000e660',
  '00000000-0000-0000-0000-00000000e643',
  '00000000-0000-0000-0000-00000000e631',
  1, 5
);

-- 5. Test G-14: Cannot issue credit note without rate verification
select throws_matching(
  $$
    update public.credit_notes
    set status = 'ISSUED', jv_no = 'JV-2026-001', jv_date = current_date
    where id = '00000000-0000-0000-0000-00000000e643'
  $$,
  'G-14.*without rate verification',
  'G-14: Cannot issue Credit Note without rate verification on each line'
);

-- Add rate verification
insert into public.rate_verifications (
  credit_note_line_id, reference_code, ref_doc_no, ref_doc_date, rate, verified_by
) values (
  '00000000-0000-0000-0000-00000000e660', 'RATE_SALES',
  'INV-HIST-001', current_date - 10, 450.00,
  '00000000-0000-0000-0000-00000000e601'
);

-- Now issue should succeed
update public.credit_notes
set status = 'ISSUED', jv_no = 'JV-2026-001', jv_date = current_date
where id = '00000000-0000-0000-0000-00000000e643';

select is(
  (select status from public.credit_notes where id = '00000000-0000-0000-0000-00000000e643'),
  'ISSUED',
  'Credit Note successfully issued once rate verification is present'
);

select * from finish();
rollback;
