-- =============================================================================================
-- Phase P3 follow-up (user answer 2026-11-20, Q27): a document found in a carton clears the
-- "No Documents From Party" tag recorded at the gate (goods_slips.missing_documentation, BR-03).
--
-- * The unboxing service clears the flag in the same transaction that saves the CARTON document
--   row, and stamps when / by whom. Removing that carton document while the GS is still UNBOXING
--   restores the flag (nothing from the party again). The change is audited (G-17).
-- * goods_slips_no_document_flag (DD r9, deprecated gate_document_code column): a legacy GS whose
--   gate document was NO_DOCUMENT may now have the flag cleared, but only through this path
--   (cleared_at set).
-- * Integrity: the flag and the stamp never coexist; the stamp needs a CARTON row while the GS is
--   UNBOXING (checked by the trigger below, on the GS row and on the document row).
-- =============================================================================================

alter table public.goods_slips
  add column missing_documentation_cleared_at timestamptz,
  add column missing_documentation_cleared_by uuid references public.profiles (id) on delete restrict,
  add constraint goods_slips_no_document_cleared check (
    missing_documentation_cleared_at is null
    or (not missing_documentation and missing_documentation_cleared_by is not null));

create index goods_slips_no_document_cleared_by_idx
  on public.goods_slips (missing_documentation_cleared_by)
  where missing_documentation_cleared_by is not null;

comment on column public.goods_slips.missing_documentation_cleared_at is
  'Q27 (2026-11-20): the gate recorded "No Documents From Party" and a document found in a carton '
  'cleared it at unboxing. NULL = the flag is as recorded at the gate.';

alter table public.goods_slips drop constraint goods_slips_no_document_flag;
alter table public.goods_slips
  add constraint goods_slips_no_document_flag check (
    gate_document_code is distinct from 'NO_DOCUMENT'
    or missing_documentation
    or missing_documentation_cleared_at is not null);

-- The stamp may only be set while UNBOXING and only when the GS has its carton document.
create or replace function rms_private.goods_slips_no_document_cleared_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.missing_documentation_cleared_at is not null
     and old.missing_documentation_cleared_at is null then
    if new.status <> 'UNBOXING' then
      raise exception 'Q27: the "no document" tag can only be cleared during unboxing (status %)', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_gate_documents d
                    where d.gs_id = new.id and d.doc_source = 'CARTON') then
      raise exception 'Q27: the "no document" tag is cleared only by a document found in a carton'
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_no_document_cleared_guard() from public, anon, authenticated;

create trigger goods_slips_no_document_cleared_guard
  before update of missing_documentation_cleared_at on public.goods_slips
  for each row execute function rms_private.goods_slips_no_document_cleared_guard();
