-- Release 2026-11-17 - DEC-52: drop the "Missing documentation warning acknowledged" checkbox from the
-- gate inward form (S1_GATE_INWARD v3). Idempotent; safe to re-run. Apply once to production after
-- deploying the backend that no longer requires the acknowledgement:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261117_gate_no_doc_ack.sql
-- Same block as in supabase/seed.sql (DATABASE_MIGRATION_GUIDE.md section 7.3).
begin;
do $$
declare
  v_def_id   uuid;
  v_pub      record;
  v_ver_id   uuid;
  v_snapshot jsonb;
begin
  select id into v_def_id from public.form_definitions where code = 'S1_GATE_INWARD';
  select v.id, v.version_no, v.snapshot into v_pub
    from public.form_versions v where v.form_definition_id = v_def_id and v.status = 'PUBLISHED';
  if v_pub.id is null
     or not jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "carton_count")')
     or not jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "missing_doc_warning_acknowledged")') then
    return;
  end if;

  insert into public.form_versions (form_definition_id, version_no, status)
  values (v_def_id, (select max(version_no) + 1 from public.form_versions where form_definition_id = v_def_id), 'DRAFT')
  returning id into v_ver_id;

  insert into public.form_fields (form_version_id, field_key, label, control_type, option_set_id,
                                  master_ref_type, is_required, visible_when, required_when, validation,
                                  default_value, sort_order, section, help_text, is_core, is_system_locked)
  select v_ver_id, f.field_key, f.label, f.control_type, f.option_set_id,
         f.master_ref_type, f.is_required, f.visible_when, f.required_when, f.validation,
         f.default_value, f.sort_order, f.section, f.help_text, f.is_core, f.is_system_locked
    from public.form_fields f
   where f.form_version_id = v_pub.id
     and f.field_key <> 'missing_doc_warning_acknowledged';

  select jsonb_build_object(
    'form_code', 'S1_GATE_INWARD',
    'name', coalesce(v_pub.snapshot ->> 'name', 'Gate Inward & GS Creation'),
    'step_code', coalesce(v_pub.snapshot ->> 'step_code', 'S1_GATE'),
    'version_no', (select version_no from public.form_versions where id = v_ver_id),
    'version_notes', 'DEC-52: no separate missing-documentation acknowledgement at the gate',
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
