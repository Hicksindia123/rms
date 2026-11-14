-- Change plan 2026-11-12 · Phase 3 — Carton Opening & Counting (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md
-- AMD-03, AMD-04, AMD-05, AMD-08; BR-07; G-01, G-02, G-03).
--
-- Status list confirmed by the user on 2026-11-13 ("keep codes, add one"): UNBOXING is labelled
-- Carton Opening and ITEMIZATION is labelled Counting (labels in the GS_STATUS option set, seed.sql;
-- codes unchanged). One new status: CATEGORISATION, between Counting and the CSR / RO routing.
--
-- 1. goods_slips.status accepts CATEGORISATION.
-- 2. G-03 (+ G-01): a GS leaves ITEMIZATION (Counting) only to CATEGORISATION and only with >= 1
--    counted line; the GS-wise category routing (CSR -> CSR_APPROVAL_PENDING, RO -> INSPECTION) now
--    starts from CATEGORISATION. Same body as 20261103000300 otherwise.
-- 3. Carton-opening document rows (gs_gate_documents.source_step = 'S1_UNBOX', AMD-04): their files
--    are added / removed while the GS is UNBOXING; gate rows keep the Phase 2 rules.
-- 4. IC-01 integrity view: CATEGORISATION is a pre-categorisation status (nothing stocked yet).
--
-- gs_items needs no change: lines are editable in GATE_CREATED / UNBOXING / ITEMIZATION and frozen
-- from CATEGORISATION on (rms_private.gs_items_guard, P2-04), which is what "submit counting" means.

-- ===========================================================================
-- 1. Status list
-- ===========================================================================
do $$
declare
  c record;
begin
  for c in
    select conname from pg_constraint
     where conrelid = 'public.goods_slips'::regclass and contype = 'c'
       and pg_get_constraintdef(oid) like '%''GATE_CREATED''%'
       and pg_get_constraintdef(oid) like '%''AWAITING_NOTIFICATION''%'
  loop
    execute format('alter table public.goods_slips drop constraint %I', c.conname);
  end loop;
end
$$;

alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION',
    'CLOSED', 'CANCELLED'));

-- ===========================================================================
-- 2. G-03: Counting -> Categorisation -> CSR / RO routing
-- ===========================================================================
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
begin
  -- original_category_code records the Step-3 choice and is kept for good (BR-08).
  if old.original_category_code is not null
     and new.original_category_code is distinct from old.original_category_code then
    raise exception 'G-03: the original category of a GS cannot change' using errcode = '23514';
  end if;

  select decision_code into v_decision
    from public.csr_approvals where gs_id = new.id and is_current;

  -- Category changes after Step-3: CSR → RO only by a current CSR_REJECTED_TO_RO decision;
  -- RO → CSR only when an admin reopened that decision (back to CSR_APPROVAL_PENDING).
  if old.category_code is not null and new.category_code is distinct from old.category_code then
    -- (null-safe comparisons: a missing decision must never let the change through)
    if not coalesce((old.category_code = 'CSR' and new.category_code is not distinct from 'RO'
                     and v_decision is not distinct from 'CSR_REJECTED_TO_RO')
                    or (old.category_code = 'RO' and new.category_code is not distinct from 'CSR'
                        and new.original_category_code is not distinct from 'CSR'
                        and v_decision is null
                        and new.status is not distinct from 'CSR_APPROVAL_PENDING'), false) then
      raise exception 'G-03: category % → % needs a matching Replacement Manager decision',
        old.category_code, coalesce(new.category_code, 'none') using errcode = '23514';
    end if;
  end if;

  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;

  -- AMD-08 / BR-07: Counting (ITEMIZATION) is submitted to CATEGORISATION with >= 1 counted line.
  if old.status = 'ITEMIZATION' then
    if new.status <> 'CATEGORISATION' then
      raise exception 'G-03: counting is submitted to CATEGORISATION before categorisation (not %)', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: counting cannot be submitted without item lines' using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CATEGORISATION (BR-07, DD r17–r18): a GS-wise category on ≥1 counted line.
  if old.status = 'CATEGORISATION' then
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave CATEGORISATION without a category' using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
    end if;
    if new.category_code = 'CSR' and new.status <> 'CSR_APPROVAL_PENDING' then
      raise exception 'G-03: a Complete Sales Return must go to CSR_APPROVAL_PENDING (not %)', new.status
        using errcode = '23514';
    end if;
    if new.category_code = 'RO' and new.status <> 'INSPECTION' then
      raise exception 'G-03: Replacement Only goes to INSPECTION (not %)', new.status using errcode = '23514';
    end if;
  end if;

  -- Nothing but a submitted count reaches CATEGORISATION.
  if new.status = 'CATEGORISATION' then
    raise exception 'G-03: only a GS in counting (ITEMIZATION) moves to CATEGORISATION (from %)', old.status
      using errcode = '23514';
  end if;

  if new.status = 'CSR_APPROVAL_PENDING' then
    if new.category_code is distinct from 'CSR' or v_decision is not null then
      raise exception 'G-03: CSR_APPROVAL_PENDING needs category CSR and no current decision'
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CSR_APPROVAL_PENDING (BR-08, DD r19–r20): only through the recorded decision.
  if old.status = 'CSR_APPROVAL_PENDING' then
    if v_decision is null then
      raise exception 'G-03: a Complete Sales Return cannot advance without the Replacement Manager''s decision'
        using errcode = '23514';
    end if;
    if v_decision = 'CSR_APPROVED' and (new.status <> 'IN_PROCESS'
                                         or new.category_code is distinct from 'CSR') then
      raise exception 'G-03: an approved CSR goes to IN_PROCESS as CSR (not %)', new.status using errcode = '23514';
    end if;
    if v_decision = 'CSR_REJECTED_TO_RO' and (new.status <> 'INSPECTION'
                                               or new.category_code is distinct from 'RO') then
      raise exception 'G-03: a rejected CSR is converted to RO and goes to INSPECTION (not %)', new.status
        using errcode = '23514';
    end if;
  end if;

  -- No CSR GS (nor one that was CSR) reaches inspection, handover or Stage-6 without a decision.
  if new.status in ('INSPECTION', 'RM_REVIEW', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION',
                    'AWAITING_NOTIFICATION', 'CLOSED')
     and 'CSR' in (new.category_code, new.original_category_code) then
    if (new.category_code = 'CSR' and v_decision is distinct from 'CSR_APPROVED')
       or (new.category_code = 'RO' and v_decision is distinct from 'CSR_REJECTED_TO_RO') then
      raise exception 'G-03: status % needs the Replacement Manager''s CSR decision', new.status
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_g03_guard() from public, anon, authenticated;

-- ===========================================================================
-- 3. GATE_DOC files of carton-opening document rows (AMD-04). Same body as 20261113000100, with
--    the stage of the linked row deciding when files may change.
-- ===========================================================================
create or replace function rms_private.attachments_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status text;
  v_row       public.attachments;
  v_stage     text;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status into v_gs_status from public.goods_slips where id = v_row.gs_id;

  if tg_op = 'UPDATE' then
    if new.gs_id <> old.gs_id or new.kind <> old.kind or new.bucket <> old.bucket
       or new.object_path <> old.object_path
       or new.gate_document_id is distinct from old.gate_document_id then
      raise exception 'An attachment''s GS, kind, bucket, object path and document cannot change'
        using errcode = '23514';
    end if;
    if old.status = 'CONFIRMED' and new.status <> 'CONFIRMED' then
      raise exception 'A confirmed attachment cannot return to %', new.status using errcode = '23514';
    end if;
  end if;

  if v_row.kind in ('UNBOXING_VIDEO', 'DOC_PHOTO', 'PARCEL_PHOTO') then
    -- Step-2 evidence is captured only while the GS is being unboxed.
    if (tg_op = 'INSERT' or (tg_op = 'UPDATE' and new.status = 'CONFIRMED' and old.status <> 'CONFIRMED'))
       and v_gs_status is distinct from 'UNBOXING' then
      raise exception 'Unboxing evidence can only be added while the GS is UNBOXING (status %)', v_gs_status
        using errcode = '23514';
    end if;
    -- G-02: confirmed evidence stays once the GS has left UNBOXING (a cascade from a deleted GS
    -- finds no GS row and is allowed).
    if tg_op = 'DELETE' and old.status = 'CONFIRMED' and v_gs_status is not null
       and v_gs_status not in ('GATE_CREATED', 'UNBOXING') then
      raise exception 'G-02: confirmed unboxing evidence cannot be deleted after unboxing (status %)', v_gs_status
        using errcode = '23514';
    end if;
  elsif v_row.kind = 'GATE_DOC' then
    -- NULL stage = the document row itself is being deleted (cascade); its own guard decided.
    select d.source_step into v_stage from public.gs_gate_documents d where d.id = v_row.gate_document_id;
    if tg_op = 'INSERT' or (tg_op = 'UPDATE' and new.status = 'CONFIRMED' and old.status <> 'CONFIRMED') then
      if (v_stage = 'S1_UNBOX' and v_gs_status is distinct from 'UNBOXING')
         or (v_stage is distinct from 'S1_UNBOX' and v_gs_status not in ('GATE_CREATED', 'UNBOXING')) then
        raise exception 'AMD-04: files of this document can no longer be added (status %)', v_gs_status
          using errcode = '23514';
      end if;
    end if;
    if tg_op = 'DELETE' and old.status = 'CONFIRMED' and v_gs_status is not null and v_stage is not null
       and ((v_stage = 'S1_UNBOX' and v_gs_status <> 'UNBOXING')
            or (v_stage <> 'S1_UNBOX' and v_gs_status <> 'GATE_CREATED')) then
      raise exception 'AMD-04: a confirmed document file cannot be deleted at this stage (status %)', v_gs_status
        using errcode = '23514';
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end
$$;
revoke all on function rms_private.attachments_guard() from public, anon, authenticated;

-- ===========================================================================
-- 4. IC-01: CATEGORISATION has nothing stocked yet (inward happens at categorisation, DEC-28).
-- ===========================================================================
do $$
declare
  v_def text := pg_get_viewdef('rms_reports.stock_reconciliation_exceptions'::regclass, true);
  v_new text;
begin
  v_new := replace(v_def, '''ITEMIZATION''::text,', '''ITEMIZATION''::text, ''CATEGORISATION''::text,');
  if v_new = v_def then
    raise exception 'IC-01 view: pre-categorisation status list not found (definition changed?)';
  end if;
  execute 'create or replace view rms_reports.stock_reconciliation_exceptions as ' || v_new;
end
$$;
