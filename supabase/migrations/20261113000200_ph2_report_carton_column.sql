-- Change plan 2026-11-12 · Phase 2 (AMD-03 / AMD-04): report R-03 shows `carton_count` instead of
-- `box_count`, and R-03 / R-04 show the gate document rows (`gate_documents`) instead of the single
-- `gate_document_code` / `gate_doc_no`. Saved column choices keep working under the new keys
-- (unknown keys would otherwise be dropped silently by the reports API).
update public.report_column_prefs
   set columns = (
         select jsonb_agg(
                  case e #>> '{}'
                    when 'box_count' then to_jsonb('carton_count'::text)
                    when 'gate_document_code' then to_jsonb('gate_documents'::text)
                    else e
                  end order by ord)
           from jsonb_array_elements(columns) with ordinality as t(e, ord))
 where report_code in ('R-03', 'R-04')
   and (columns ? 'box_count' or columns ? 'gate_document_code');

update public.report_column_prefs
   set columns = (select coalesce(jsonb_agg(e order by ord), '[]'::jsonb)
                    from jsonb_array_elements(columns) with ordinality as t(e, ord)
                   where e #>> '{}' <> 'gate_doc_no')
 where report_code = 'R-03' and columns ? 'gate_doc_no'
   and jsonb_array_length(columns) > 1;

update public.report_definitions
   set column_labels = (column_labels - 'box_count' - 'gate_document_code' - 'gate_doc_no')
       || case when column_labels ? 'box_count'
               then jsonb_build_object('carton_count', column_labels -> 'box_count') else '{}'::jsonb end
 where code in ('R-03', 'R-04')
   and (column_labels ? 'box_count' or column_labels ? 'gate_document_code' or column_labels ? 'gate_doc_no');
