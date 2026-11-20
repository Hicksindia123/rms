-- Release 2026-11-20 - Phase P2 / DEC-62: gate form S1_GATE_INWARD v4 + option changes.
-- Needs migration 20261120000200_p2_gate_v4_documents.sql first. Idempotent; safe to re-run.
-- Apply once to production after deploying the backend that understands gate v4:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261120_gate_v4.sql
-- Same block as in supabase/seed.sql (DATABASE_MIGRATION_GUIDE.md section 7.3).
begin;
-- -----------------------------------------------------------------------------
-- DEC-62 (Phase P2, 2026-11-20): gate form S1_GATE_INWARD v4 + option changes.
-- Option labels (codes unchanged, rule e): Received Through = Courier / Transport / By Hand; party
-- documents = Invoice / GST Debit Note / Hand Written Slip / No Documents From Party. DELIVERY_CHALLAN,
-- LR_BILITY, DELIVERY_NOTE, OTHER and COURIER_SLIP are deactivated in GATE_DOCUMENT (never deleted;
-- existing rows keep them). The transport document list is the new option set GATE_TRANSPORT_DOCUMENT
-- (COURIER_SLIP); rows carry gs_gate_documents.doc_source = TRANSPORT.
-- v4 = the published v3 fields minus vehicle_no (Q5), relabelled, + transport_document. Return Type and
-- Gate Entry Date / No. stay (Q23, Q24). v3 is RETIRED (G-18: v3 GSs keep their pinned version).
-- Idempotent: the form block runs only while the published version has no transport_document field.
-- -----------------------------------------------------------------------------
update public.option_items oi set label = v.label, rule_text = v.rule_text, updated_at = now()
  from (values
    ('DELIVERY_MODE', 'COURIER_PARCEL', 'Courier', 'Record courier name and docket number'),
    ('DELIVERY_MODE', 'DIRECT_TRUCK', 'Transport', 'Record the transport name'),
    ('DELIVERY_MODE', 'SELF_PARTY_REP', 'By Hand', 'Record contact name and contact number'),
    ('GATE_DOCUMENT', 'DEBIT_NOTE', 'GST Debit Note', 'Attach a photo or PDF of the GST debit note'),
    ('GATE_DOCUMENT', 'INVOICE', 'Invoice', 'Attach a photo or PDF of the invoice'),
    ('GATE_DOCUMENT', 'HANDWRITTEN_SLIP', 'Hand Written Slip', 'Attach a photo of the hand written slip'),
    ('GATE_DOCUMENT', 'NO_DOCUMENT', 'No Documents From Party', 'Flag consignment as missing documentation')
  ) as v(set_code, code, label, rule_text)
  join public.option_sets os on os.code = v.set_code
 where oi.option_set_id = os.id and oi.code = v.code
   and (oi.label is distinct from v.label or oi.rule_text is distinct from v.rule_text);

update public.option_items oi
   set required_fields = '["transporter_name"]'::jsonb, updated_at = now()
  from public.option_sets os
 where os.id = oi.option_set_id and os.code = 'DELIVERY_MODE' and oi.code = 'DIRECT_TRUCK'
   and oi.required_fields is distinct from '["transporter_name"]'::jsonb;

update public.option_items oi set is_active = false, updated_at = now()
  from public.option_sets os
 where os.id = oi.option_set_id and os.code = 'GATE_DOCUMENT'
   and oi.code in ('DELIVERY_CHALLAN', 'LR_BILITY', 'DELIVERY_NOTE', 'OTHER', 'COURIER_SLIP')
   and oi.is_active;

insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
values ('GATE_TRANSPORT_DOCUMENT', 'Documents From Transport',
        'Stage-1 · Step-1 · Goods Slip (GS) Creation · Gate User (Offline) · document handed over by the courier / transport',
        'dropdown', 'STATIC', null, 'DEC-62', true)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'COURIER_SLIP', 'Courier Slip', 'YES', 'Attach a photo of the courier slip',
       'Attach to Inward Entry', 'Physical document received', null, '[]'::jsonb, 10, 'DEC-62'
  from public.option_sets os where os.code = 'GATE_TRANSPORT_DOCUMENT'
on conflict (option_set_id, code) do nothing;

do $$
declare
  v_def_id   uuid;
  v_pub      record;
  v_ver_id   uuid;
  v_snapshot jsonb;
  v_td       uuid := (select id from public.option_sets where code = 'GATE_TRANSPORT_DOCUMENT');
begin
  select id into v_def_id from public.form_definitions where code = 'S1_GATE_INWARD';
  select v.id, v.version_no, v.snapshot into v_pub
    from public.form_versions v where v.form_definition_id = v_def_id and v.status = 'PUBLISHED';
  if v_pub.id is null
     or not jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "carton_count")')
     or jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "transport_document")') then
    return;
  end if;

  insert into public.form_versions (form_definition_id, version_no, status)
  values (v_def_id, (select max(version_no) + 1 from public.form_versions where form_definition_id = v_def_id), 'DRAFT')
  returning id into v_ver_id;

  insert into public.form_fields (form_version_id, field_key, label, control_type, option_set_id,
                                  master_ref_type, is_required, visible_when, required_when, validation,
                                  default_value, sort_order, section, help_text, is_core, is_system_locked)
  select v_ver_id, f.field_key,
         case f.field_key
           when 'party_name' then 'Party'
           when 'carton_count' then 'Cartons'
           when 'delivery_mode' then 'Received Through'
           when 'courier_name' then 'Courier Name'
           when 'docket_no' then 'Docket No.'
           when 'transporter_name' then 'Transport Name'
           when 'rep_name' then 'Contact Name'
           when 'rep_contact' then 'Contact Number'
           when 'no_document' then 'No Documents From Party'
           else f.label end,
         f.control_type, f.option_set_id, f.master_ref_type, f.is_required, f.visible_when,
         f.required_when, f.validation, f.default_value, f.sort_order,
         case f.field_key
           when 'delivery_mode' then 'Received Through'
           when 'courier_name' then 'Received Through'
           when 'docket_no' then 'Received Through'
           when 'transporter_name' then 'Received Through'
           when 'rep_name' then 'Received Through'
           when 'rep_contact' then 'Received Through'
           when 'no_document' then 'Documents From Party'
           else f.section end,
         case f.field_key
           when 'carton_count' then 'Number of cartons received (whole number, 1 or more)'
           when 'rep_contact' then 'Mobile number of the person who brought the goods'
           when 'no_document' then 'Optional. Add each document with a photo or PDF, or choose "No Documents From Party".'
           else f.help_text end,
         f.is_core, f.is_system_locked
    from public.form_fields f
   where f.form_version_id = v_pub.id
     and f.field_key <> 'vehicle_no';   -- Q5: Transport Name only

  insert into public.form_fields (form_version_id, field_key, label, control_type, option_set_id,
                                  is_required, visible_when, required_when, validation, default_value,
                                  sort_order, section, help_text, is_core)
  values (v_ver_id, 'transport_document', 'Documents From Transport', 'dropdown', v_td, false, null, null,
          null, null, 130, null,
          'Optional. The courier slip handed over with the goods, with a photo.', true);

  select jsonb_build_object(
    'form_code', 'S1_GATE_INWARD',
    'name', coalesce(v_pub.snapshot ->> 'name', 'Gate Inward & GS Creation'),
    'step_code', coalesce(v_pub.snapshot ->> 'step_code', 'S1_GATE'),
    'version_no', (select version_no from public.form_versions where id = v_ver_id),
    'version_notes', 'DEC-62: Received Through (Courier / Transport / By Hand), party + transport documents (image only), no vehicle no.',
    'fields', coalesce(jsonb_agg(
      to_jsonb(fld) || jsonb_build_object(
        'option_items', coalesce((
          select jsonb_agg(jsonb_build_object(
                   'code', oi.code, 'label', oi.label, 'allowed_status', oi.allowed_status,
                   'rule_text', oi.rule_text, 'next_action_text', oi.next_action_text,
                   'remarks', oi.remarks, 'system_behavior', oi.system_behavior,
                   'sort_order', oi.sort_order, 'is_active', oi.is_active)
                 order by oi.sort_order asc, oi.code asc)
            from public.option_items oi where oi.option_set_id = fld.option_set_id
        ), '[]'::jsonb)
      ) order by fld.sort_order asc, fld.field_key asc
    ), '[]'::jsonb)
  ) into v_snapshot
  from public.form_fields fld
  where fld.form_version_id = v_ver_id;

  update public.form_versions set status = 'RETIRED' where id = v_pub.id;
  update public.form_versions
     set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
   where id = v_ver_id;
end $$;
commit;
