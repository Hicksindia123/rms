-- =============================================================================================
-- Phase P3 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-62 · DEC-63 (user Q8 + Q25, 2026-11-20).
-- Step 2a: Unboxing = one video per carton + ONE optional "document found in carton".
--
-- 1. Carton document = a gs_gate_documents row with source_step S1_UNBOX and doc_source CARTON
--    (column + step CHECK exist since 20261120000200). It is a type + photo(s) only: the image-only
--    CHECK now covers CARTON rows too. At most ONE CARTON row per GS (any number of files).
-- 2. A CARTON row is allowed on a GS flagged missing_documentation ("No Documents From Party").
--    The flag itself stays as recorded at the gate (BR-03). Legacy S1_UNBOX rows (doc_source NULL)
--    keep their old rules (DD r5-r8 fields, excluded by the flag).
-- 3. Guard G-02 (DEC-63, explicit guard change per CLAUDE.md §c): a GS cannot leave UNBOXING until
--    every carton 1..N has a confirmed unboxing video. Nothing else:
--      - part (b) dropped (Q25): no classified DOC_PHOTO is required;
--      - part (c) dropped (Q8): no APPROVED Missing Document Exception is required, for ALL GSs.
--    Still enforced in the DB (this trigger) and in the service (shared/guards.py); not configurable.
-- 4. The RM Missing Document Exception (DEC-03) is retired: missing_doc_exceptions accepts no new
--    request and no decision (rows stay as history, the table is not dropped).
-- 5. Release of legacy GSs: GSs in UNBOXING that waited for a REQUESTED / REJECTED exception are no
--    longer blocked by it; they complete on the carton videos alone. Reported below (NOTICE).
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Carton document: image only, at most one per GS
-- ---------------------------------------------------------------------------------------------
alter table public.gs_gate_documents drop constraint gs_gate_documents_v4_image_only;
alter table public.gs_gate_documents
  -- DEC-62 (c) + P3: gate v4 party / transport documents and the carton document are a type +
  -- picture only (no number, date or remarks). Legacy rows (doc_source NULL) are not affected.
  add constraint gs_gate_documents_v4_image_only check (
    doc_source is null
    or (doc_no is null and doc_date is null and remarks is null));

create unique index gs_gate_documents_one_carton_doc
  on public.gs_gate_documents (gs_id) where doc_source = 'CARTON';
comment on index public.gs_gate_documents_one_carton_doc is
  'P3 / DEC-62: one optional "document found in carton" per GS (any number of photos).';

-- ---------------------------------------------------------------------------------------------
-- 2. Guard trigger: the "No documents from party" flag (BR-03) excludes party and legacy rows,
--    not the carton document. Everything else is unchanged from 20261120000200.
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
    -- BR-03 / DEC-62 / P3: "No documents from party" excludes party (and legacy) rows. A transport
    -- document and the document found in a carton may still be recorded; the flag stays as
    -- recorded at the gate.
    if v_missing and (new.doc_source is null or new.doc_source = 'PARTY') then
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
      -- NO_DOCUMENT is the GS-level flag (BR-03), never a document row of the new sources.
      if new.doc_source is not null and new.doc_type_code = 'NO_DOCUMENT' then
        raise exception 'DEC-62: "No Documents From Party" is not a document type of a row'
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
                    and (d.doc_source is null or d.doc_source = 'PARTY')) then
    raise exception 'AMD-04: remove the document rows before flagging the GS as "no document"'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_no_document_exclusive() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 3. G-02 (DEC-63): one confirmed video per carton, nothing else.
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_g02_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_missing integer[];
begin
  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;
  if old.status = 'GATE_CREATED' and new.status <> 'UNBOXING' then
    raise exception 'G-02: a GS must pass through UNBOXING before %', new.status using errcode = '23514';
  end if;
  if old.status <> 'UNBOXING' then
    return new;
  end if;

  if not exists (select 1 from public.attachments
                  where gs_id = new.id and kind = 'UNBOXING_VIDEO' and status = 'CONFIRMED') then
    raise exception 'G-02: a confirmed unboxing video is required before leaving UNBOXING'
      using errcode = '23514';
  end if;
  -- AMD-03: one confirmed video per carton (1..carton_count). A single-carton GS accepts a video
  -- without a carton number.
  if new.carton_count > 1 then
    select array_agg(n order by n) into v_missing
      from generate_series(1, new.carton_count) n
     where not exists (select 1 from public.attachments a
                        where a.gs_id = new.id and a.kind = 'UNBOXING_VIDEO'
                          and a.status = 'CONFIRMED' and a.box_no = n);
    if v_missing is not null then
      raise exception 'G-02: a confirmed unboxing video is required for every carton (missing carton %)',
        array_to_string(v_missing, ', ')
        using errcode = '23514';
    end if;
  end if;
  -- DEC-63: no document photo, classification or Missing Document Exception is required
  -- (also when the GS is flagged missing_documentation).
  return new;
end
$$;
revoke all on function rms_private.goods_slips_g02_guard() from public, anon, authenticated;

comment on function rms_private.goods_slips_g02_guard() is
  'G-02 (DEC-63, 2026-11-20): a GS cannot leave UNBOXING until every carton 1..N has a confirmed '
  'unboxing video. Not configurable; Super Admin cannot bypass it.';

-- ---------------------------------------------------------------------------------------------
-- 4. DEC-63: the RM Missing Document Exception is retired. Rows stay as history.
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.missing_doc_exceptions_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'DEC-63: the Missing Document Exception was retired on 2026-11-20; '
                  'unboxing needs only a video per carton (G-02). Existing rows are history.'
    using errcode = '23514';
end
$$;
revoke all on function rms_private.missing_doc_exceptions_guard() from public, anon, authenticated;

comment on table public.missing_doc_exceptions is
  'DEC-03 Missing Document Exception. RETIRED by DEC-63 (2026-11-20): read-only history; no new '
  'request or decision is accepted (trigger missing_doc_exceptions_guard).';

-- ---------------------------------------------------------------------------------------------
-- 5. Release legacy GSs blocked on the exception (report only: the new G-02 no longer checks it).
-- ---------------------------------------------------------------------------------------------
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
                  where e.gs_id = g.id and e.status in ('REQUESTED', 'REJECTED'))
     and not exists (select 1 from public.missing_doc_exceptions e
                      where e.gs_id = g.id and e.status = 'APPROVED');
  raise notice 'DEC-63: % GS(s) in UNBOXING released from the Missing Document Exception (complete on carton videos only): %',
    v_count, coalesce(v_list, '-');
end
$$;
