-- =============================================================================================
-- Phase P2 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-62 · gate form S1_GATE_INWARD v4.
--
-- 1. gs_gate_documents.doc_source (PARTY | TRANSPORT | CARTON). NULL = a row captured before gate
--    form v4 (gate v1–v3 or carton opening before P3): those rows keep the DD r5–r8 field rules.
--    CARTON is used from P3. A row's source never changes.
-- 2. The DD r5–r8 CHECKs (Invoice / Debit Note / Delivery Challan need doc no. + date, Handwritten
--    Slip needs remarks) now apply to legacy rows only (doc_source IS NULL). v4 PARTY / TRANSPORT rows
--    are image only: they may not carry doc no., date or remarks (DEC-62 c). Existing rows are untouched.
-- 3. Document types per source: PARTY / CARTON / legacy rows use option set GATE_DOCUMENT, TRANSPORT
--    rows use option set GATE_TRANSPORT_DOCUMENT (seeded in seed.sql + the release snippet).
-- 4. "No documents from party" (goods_slips.missing_documentation, BR-03 / DEC-03) excludes party and
--    legacy rows only. A transport document (courier slip) may exist on a GS without party documents.
-- 5. goods_slips_truck_fields (DD r3): Transport needs a transporter (master or name); the vehicle
--    number is no longer required by the DB (gate v4 has no vehicle field, Q5). GSs pinned to gate
--    v1–v3 are still validated against their own form version (required_when vehicle_no, G-18).
--
-- Option labels, the new option set and the v4 form version are configuration: seed.sql and
-- supabase/snippets/release_20261120_gate_v4.sql (phase prompts §0 rule 3), not this migration.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Document source
-- ---------------------------------------------------------------------------------------------
alter table public.gs_gate_documents
  add column doc_source text
    constraint gs_gate_documents_doc_source_check check (doc_source in ('PARTY', 'TRANSPORT', 'CARTON')),
  -- PARTY / TRANSPORT rows are captured at the gate, CARTON rows at carton opening (P3).
  add constraint gs_gate_documents_source_step_match check (
    doc_source is null
    or (doc_source in ('PARTY', 'TRANSPORT') and source_step = 'S1_GATE')
    or (doc_source = 'CARTON' and source_step = 'S1_UNBOX'));

comment on column public.gs_gate_documents.doc_source is
  'DEC-62: who sent the document. PARTY / TRANSPORT (gate form v4), CARTON (carton opening, P3). '
  'NULL = captured before gate form v4; such rows keep the DD r5-r8 number/date/remarks rules.';

create index gs_gate_documents_gs_source_idx on public.gs_gate_documents (gs_id, doc_source);

-- ---------------------------------------------------------------------------------------------
-- 2. DD r5–r8 for legacy rows only; v4 party / transport rows are image only (DEC-62 c)
-- ---------------------------------------------------------------------------------------------
alter table public.gs_gate_documents
  drop constraint gs_gate_documents_formal_fields,
  drop constraint gs_gate_documents_slip_fields;

alter table public.gs_gate_documents
  -- DD r5–r7 (legacy rows): Invoice / Debit Note / Delivery Challan → number + date
  add constraint gs_gate_documents_formal_fields check (
    doc_source is not null
    or doc_type_code not in ('INVOICE', 'DEBIT_NOTE', 'DELIVERY_CHALLAN')
    or (coalesce(btrim(doc_no), '') <> '' and doc_date is not null)),
  -- DD r8 (legacy rows): Handwritten Slip → slip details / remarks
  add constraint gs_gate_documents_slip_fields check (
    doc_source is not null
    or doc_type_code <> 'HANDWRITTEN_SLIP'
    or coalesce(btrim(remarks), '') <> ''),
  -- DEC-62 (c): gate v4 documents are a type + picture only.
  add constraint gs_gate_documents_v4_image_only check (
    doc_source is null
    or doc_source not in ('PARTY', 'TRANSPORT')
    or (doc_no is null and doc_date is null and remarks is null));

-- ---------------------------------------------------------------------------------------------
-- 3 + 4. Guard trigger: source is immutable, type per source, "no party documents" excludes only
--        party / legacy rows. Everything else is unchanged from 20261113000100.
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.gs_gate_documents_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row     public.gs_gate_documents;
  v_status  text;
  v_missing boolean;
  v_set     text;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select g.status, g.missing_documentation into v_status, v_missing
    from public.goods_slips g where g.id = v_row.gs_id;
  if v_status is null then
    return case when tg_op = 'DELETE' then old else new end;   -- cascade from a deleted GS
  end if;

  if tg_op = 'UPDATE' and (new.gs_id <> old.gs_id or new.source_step <> old.source_step) then
    raise exception 'AMD-04: a gate document cannot move to another GS or step' using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' and new.doc_source is distinct from old.doc_source then
    raise exception 'DEC-62: the source of a gate document (party / transport / carton) cannot change'
      using errcode = '23514';
  end if;
  -- Gate rows are captured and corrected only while the GS is at the gate (as gate details are).
  if v_row.source_step = 'S1_GATE' and v_status <> 'GATE_CREATED' then
    raise exception 'AMD-04: gate documents can only change while the GS is at the gate (status %)', v_status
      using errcode = '23514';
  end if;
  if v_row.source_step = 'S1_UNBOX' and v_status <> 'UNBOXING' then
    raise exception 'AMD-04: carton-opening documents can only change while the GS is UNBOXING (status %)', v_status
      using errcode = '23514';
  end if;

  if tg_op <> 'DELETE' then
    -- DEC-03 / BR-03 / DEC-62: "No documents from party" is a GS-level flag; it excludes party
    -- (and legacy) rows. A transport document (courier slip) may still be recorded.
    if v_missing and (new.doc_source is null or new.doc_source in ('PARTY', 'CARTON')) then
      raise exception 'AMD-04: a GS flagged "no document" cannot have document rows' using errcode = '23514';
    end if;
    if tg_op = 'INSERT' or new.doc_type_code is distinct from old.doc_type_code then
      v_set := case when new.doc_source = 'TRANSPORT' then 'GATE_TRANSPORT_DOCUMENT' else 'GATE_DOCUMENT' end;
      if not exists (
        select 1 from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = v_set and oi.code = new.doc_type_code and oi.is_active
      ) then
        raise exception 'AMD-04: unknown or inactive gate document type % (option set %, DEC-62)', new.doc_type_code, v_set
          using errcode = '23514';
      end if;
    end if;
    if new.doc_date is not null and (tg_op = 'INSERT' or new.doc_date is distinct from old.doc_date)
       and new.doc_date > rms_private.business_today() then
      raise exception 'AMD-04: the document date % is in the future', new.doc_date using errcode = '23514';
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end
$$;
revoke all on function rms_private.gs_gate_documents_guard() from public, anon, authenticated;

-- The reverse direction: flagging "no document" while party / legacy rows exist.
create or replace function rms_private.goods_slips_no_document_exclusive()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.missing_documentation and not coalesce(old.missing_documentation, false)
     and exists (select 1 from public.gs_gate_documents d
                  where d.gs_id = new.id
                    and (d.doc_source is null or d.doc_source in ('PARTY', 'CARTON'))) then
    raise exception 'AMD-04: remove the document rows before flagging the GS as "no document"'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_no_document_exclusive() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 5. DD r3 / DEC-62 (a), Q5: Transport = transporter only; the vehicle number is optional.
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_truck_fields;
alter table public.goods_slips
  add constraint goods_slips_truck_fields check (
    delivery_mode_code <> 'DIRECT_TRUCK'
    or transporter_id is not null
    or coalesce(btrim(transporter_name), '') <> '');
