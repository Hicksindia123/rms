-- Release 2026-11-25 - DEC-75: store analysis = Allowed / Not Allowed, Allowed pieces split into
-- "Send New Pieces to Party" / "Send Repaired Pieces to Party"; pieces sent to Management per item +
-- qty with a proposed action (Send New Pieces / Issue CN).
--
-- Apply to production AFTER migration 20261125000200_dec75_allowed_and_management_proposals.sql and
-- after deploying the DEC-75 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261125_dec75_allowed_management.sql
-- Same configuration as supabase/seed.sql.
begin;

-- Labels of the Allowed actions (codes unchanged, G-18; an admin may relabel later).
update public.item_field_library l
   set label = v.label
  from (values ('SEND_NEW', 'Send New', 'Send New Pieces to Party'),
               ('SEND_NEW', 'Dispatch New Piece', 'Send New Pieces to Party'),
               ('SEND_REPAIRED', 'Send Repaired', 'Send Repaired Pieces to Party'),
               ('SEND_REPAIRED', 'Dispatch Repaired Piece', 'Send Repaired Pieces to Party'))
       as v(code, old_label, label)
 where l.field_group = 'ACTION' and l.code = v.code and l.label = v.old_label;

-- The DEC-74 store option is replaced by the per-piece request (already off after the migration).
update public.item_field_library
   set is_active = false
 where field_group = 'ACTION' and code = 'ISSUE_CN_REQUEST' and is_active;

-- My Work hint of the Analysis step (only while it is the P9 default).
update public.journey_steps
   set hint = 'Goods of your Intermediate Store back from departments (or with no work): mark Allowed or Not Allowed, choose new or repaired pieces, and send pieces to Management when needed'
 where code = 'STORE_ANALYSIS'
   and hint = 'Goods of your Intermediate Store back from departments (or with no work): decide Dispatch New, Dispatch Repaired or Not Allowed';

-- Portal refresh: brand colour of the sign-in screen (only while it is still the old default).
update public.system_settings
   set value = '"#2a47f0"'::jsonb
 where key = 'branding_primary_color' and value = '"#0f172a"'::jsonb;

-- Report: goods slips still carrying Issue CN Request pieces (Management decides them as before).
select g.gs_no, sum(a.qty) as cn_request_qty
  from public.rm_item_actions a
  join public.gs_items gi on gi.id = a.gs_item_id
  join public.goods_slips g on g.id = gi.gs_id
 where a.is_current and a.action_code = 'ISSUE_CN_REQUEST'
 group by g.gs_no;

commit;
