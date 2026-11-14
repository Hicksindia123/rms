-- P2-01 · Operational schema for inward & generic inventory ledger (master plan §8.4, §8.5, prompt P2-01)
-- Enforces:
-- 1. Goods slips & inward/inspection operational tables
-- 2. Inventory ledger (stock_items, stock_lots, stock_movements, stock_balances)
-- 3. Guarded single movement function rms_private.rms_move_stock with G-04, G-05, G-08, G-12, G-16
-- 4. Reclassification function rms_private.rms_reclassify_lot
-- 5. Location class freeze trigger on inventory_locations

-- ===========================================================================
-- 1. Inward & Inspection Operational Tables (§8.4)
-- ===========================================================================

create table public.goods_slips (
  id                      uuid primary key default gen_random_uuid(),
  gs_no                   text not null unique check (btrim(gs_no) <> ''),
  workflow_version_id     uuid not null references public.workflow_versions (id) on delete restrict,
  party_id                uuid references public.parties (id) on delete restrict,
  state_id                uuid references public.states (id) on delete restrict,
  station_id              uuid references public.stations (id) on delete restrict,
  delivery_mode_code      text not null check (delivery_mode_code in ('COURIER_PARCEL','DIRECT_VEHICLE','DIRECT_PERSON','OTHER')),
  courier_name            text,
  docket_no               text,
  vehicle_no              text,
  transporter_id          uuid references public.transporters (id) on delete restrict,
  rep_name                text,
  rep_contact             text,
  box_count               integer not null check (box_count > 0),
  gate_document_code      text check (gate_document_code in ('CHALLAN','INVOICE','LR_BILITY','DELIVERY_NOTE','NO_DOCUMENT','OTHER')),
  gate_doc_no             text,
  gate_doc_date           date,
  gate_doc_remarks        text,
  missing_documentation   boolean not null default false,
  category_code           text check (category_code in ('CSR','RO') or category_code is null),
  original_category_code  text check (original_category_code in ('CSR','RO') or original_category_code is null),
  status                  text not null default 'GATE_CREATED' check (status in (
                            'GATE_CREATED','UNBOXING','ITEMIZATION','CSR_APPROVAL_PENDING',
                            'INSPECTION','RM_REVIEW','IN_PROCESS','COMMERCIAL_RESOLUTION',
                            'AWAITING_NOTIFICATION','CLOSED','CANCELLED'
                          )),
  has_open_pendency       boolean not null default false,
  has_discrepancy         boolean not null default false,
  has_hazard              boolean not null default false,
  has_rejections          boolean not null default false,
  closed_at               timestamptz,
  closure_type            text check (closure_type in ('CSR_CLOSED','RO_CLOSED') or closure_type is null),
  created_at              timestamptz not null default now(),
  created_by              uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at              timestamptz not null default now(),

  -- Delivery mode conditional validations
  check (delivery_mode_code <> 'COURIER_PARCEL' or (courier_name is not null and docket_no is not null)),
  check (delivery_mode_code <> 'DIRECT_VEHICLE' or (vehicle_no is not null and transporter_id is not null)),
  check (delivery_mode_code <> 'DIRECT_PERSON'  or (rep_name is not null and rep_contact is not null)),

  -- Gate document conditional validation
  check (gate_document_code is null or gate_document_code = 'NO_DOCUMENT' or gate_doc_no is not null)
);

create index goods_slips_party_id_idx on public.goods_slips (party_id);
create index goods_slips_party_created_idx on public.goods_slips (party_id, created_at desc);
create index goods_slips_workflow_version_idx on public.goods_slips (workflow_version_id);
create index goods_slips_state_idx on public.goods_slips (state_id);
create index goods_slips_station_idx on public.goods_slips (station_id);
create index goods_slips_transporter_idx on public.goods_slips (transporter_id);
create index goods_slips_status_idx on public.goods_slips (status);
create index goods_slips_created_by_idx on public.goods_slips (created_by);
create index goods_slips_gs_no_trgm_idx on public.goods_slips using gin (gs_no extensions.gin_trgm_ops);

-- Status history
create table public.gs_status_history (
  id           uuid primary key default gen_random_uuid(),
  gs_id        uuid not null references public.goods_slips (id) on delete cascade,
  from_status  text,
  to_status    text not null,
  step_code    text not null,
  reason       text,
  "by"         uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  "at"         timestamptz not null default now()
);

create index gs_status_history_gs_idx on public.gs_status_history (gs_id);
create index gs_status_history_by_idx on public.gs_status_history ("by");
create index gs_status_history_gs_at_idx on public.gs_status_history (gs_id, "at" desc);

-- Attachments
create table public.attachments (
  id            uuid primary key default gen_random_uuid(),
  gs_id         uuid not null references public.goods_slips (id) on delete cascade,
  entity_type   text,
  entity_id     uuid,
  kind          text not null check (kind in ('UNBOXING_VIDEO','DOC_PHOTO','PARCEL_PHOTO','NOTIFICATION_PROOF','OTHER')),
  bucket        text not null check (btrim(bucket) <> ''),
  object_path   text not null unique check (btrim(object_path) <> ''),
  mime_type     text not null,
  size_bytes    bigint not null check (size_bytes >= 0),
  box_no        integer check (box_no is null or box_no > 0),
  status        text not null default 'PENDING_UPLOAD' check (status in ('PENDING_UPLOAD','CONFIRMED','REJECTED')),
  uploaded_by   uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  confirmed_at  timestamptz,
  created_at    timestamptz not null default now()
);

create index attachments_gs_idx on public.attachments (gs_id);
create index attachments_entity_idx on public.attachments (entity_type, entity_id);
create index attachments_uploaded_by_idx on public.attachments (uploaded_by);

-- Classified documents
create table public.gs_documents (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete cascade,
  attachment_id        uuid references public.attachments (id) on delete set null,
  classification_code  text not null check (btrim(classification_code) <> ''),
  doc_no               text,
  doc_date             date,
  amount               numeric(12, 2) check (amount is null or amount >= 0),
  buyer_gstin          text,
  seller_gstin         text,
  party_claim_text     text,
  qty_matched          boolean,
  verified_by          uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  verified_at          timestamptz,
  created_at           timestamptz not null default now()
);

create index gs_documents_gs_idx on public.gs_documents (gs_id);
create index gs_documents_attachment_idx on public.gs_documents (attachment_id);
create index gs_documents_verified_by_idx on public.gs_documents (verified_by);

-- Goods slip items
create table public.gs_items (
  id              uuid primary key default gen_random_uuid(),
  gs_id           uuid not null references public.goods_slips (id) on delete cascade,
  line_no         integer not null check (line_no > 0),
  product_id      uuid not null references public.products (id) on delete restrict,
  category_id     uuid not null references public.product_categories (id) on delete restrict,
  documented_qty  integer not null default 0 check (documented_qty >= 0),
  received_qty    integer not null default 0 check (received_qty >= 0),
  short_qty       integer generated always as (greatest(documented_qty - received_qty, 0)) stored,
  excess_qty      integer generated always as (greatest(received_qty - documented_qty, 0)) stored,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  updated_at      timestamptz not null default now(),
  unique (gs_id, line_no)
);

create index gs_items_gs_idx on public.gs_items (gs_id);
create index gs_items_product_idx on public.gs_items (product_id);
create index gs_items_category_idx on public.gs_items (category_id);
create index gs_items_created_by_idx on public.gs_items (created_by);

-- CSR Approvals
create table public.csr_approvals (
  id             uuid primary key default gen_random_uuid(),
  gs_id          uuid not null references public.goods_slips (id) on delete cascade,
  decision_code  text not null check (decision_code in ('CSR_APPROVED','CSR_REJECTED_TO_RO')),
  remarks        text,
  is_current     boolean not null default true,
  decided_by     uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  decided_at     timestamptz not null default now()
);

create index csr_approvals_gs_idx on public.csr_approvals (gs_id);
create index csr_approvals_decided_by_idx on public.csr_approvals (decided_by);

-- Inspections
create table public.inspections (
  id                      uuid primary key default gen_random_uuid(),
  gs_item_id              uuid not null unique references public.gs_items (id) on delete cascade,
  form_version_id         uuid references public.form_versions (id) on delete restrict,
  full_opening_confirmed  boolean not null default false,
  status                  text not null default 'DRAFT' check (status in ('DRAFT','FINAL')),
  inspected_by            uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  inspected_at            timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create index inspections_gs_item_idx on public.inspections (gs_item_id);
create index inspections_form_version_idx on public.inspections (form_version_id);
create index inspections_inspected_by_idx on public.inspections (inspected_by);

-- Inspection allocations
create table public.inspection_allocations (
  id                        uuid primary key default gen_random_uuid(),
  inspection_id             uuid not null references public.inspections (id) on delete cascade,
  condition_code            text not null check (btrim(condition_code) <> ''),
  option_item_id            uuid references public.option_items (id) on delete set null,
  qty                       integer not null check (qty > 0),
  allowed_status_snapshot   text,
  system_behavior_snapshot  text,
  label_snapshot            text,
  created_at                timestamptz not null default now(),
  unique (inspection_id, condition_code)
);

create index inspection_allocations_inspection_idx on public.inspection_allocations (inspection_id);
create index inspection_allocations_option_item_idx on public.inspection_allocations (option_item_id);

-- Extraction records
create table public.extraction_records (
  id              uuid primary key default gen_random_uuid(),
  gs_item_id      uuid not null unique references public.gs_items (id) on delete cascade,
  primary_type    text not null check (primary_type in ('PACKAGING_EXTRACTED','CONTAINER_EXTRACTED')),
  packaging_qty   integer not null default 0 check (packaging_qty >= 0),
  container_qty   integer not null default 0 check (container_qty >= 0),
  reconciled      boolean not null default false,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete set null
);

create index extraction_records_gs_item_idx on public.extraction_records (gs_item_id);

-- Container audit days & lines
create table public.container_audit_days (
  id            uuid primary key default gen_random_uuid(),
  audit_date    date not null unique,
  confirmed     boolean not null default false,
  confirmed_by  uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  confirmed_at  timestamptz,
  remarks       text,
  created_at    timestamptz not null default now()
);

create index container_audit_days_confirmed_by_idx on public.container_audit_days (confirmed_by);

create table public.container_audit_lines (
  id                      uuid primary key default gen_random_uuid(),
  audit_day_id            uuid not null references public.container_audit_days (id) on delete cascade,
  container_id            uuid not null references public.storage_containers (id) on delete restrict,
  counted_qty             integer not null default 0 check (counted_qty >= 0),
  sellable_packaging_qty  integer not null default 0 check (sellable_packaging_qty >= 0),
  remarks                 text,
  unique (audit_day_id, container_id)
);

create index container_audit_lines_day_idx on public.container_audit_lines (audit_day_id);
create index container_audit_lines_container_idx on public.container_audit_lines (container_id);

-- Rejections (forward reference to stock_movements resolved below)
create table public.rejections (
  id                   uuid primary key default gen_random_uuid(),
  gs_item_id           uuid not null references public.gs_items (id) on delete cascade,
  condition_code       text not null check (btrim(condition_code) <> ''),
  qty                  integer not null check (qty > 0),
  rejection_reason_id  uuid references public.rejection_reasons (id) on delete set null,
  disposition          text not null check (disposition in ('HOLD_PARTY_RETURN','HAZARD_QUARANTINE','TO_SPARE_PARTS','RECORDED_REJECT')),
  hazard               boolean not null default false,
  stock_movement_id    uuid,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete set null
);

create index rejections_gs_item_idx on public.rejections (gs_item_id);
create index rejections_reason_idx on public.rejections (rejection_reason_id);

-- RM Item Actions
create table public.rm_item_actions (
  id           uuid primary key default gen_random_uuid(),
  gs_item_id   uuid not null references public.gs_items (id) on delete cascade,
  revision_no  integer not null default 1 check (revision_no >= 1),
  action_code  text not null check (action_code in ('SEND_NEW','SEND_REPAIRED','ISSUE_CN','NOT_ALLOWED','PENDING_BP')),
  qty          integer not null check (qty > 0),
  is_current   boolean not null default true,
  reason       text,
  decided_by   uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  decided_at   timestamptz not null default now()
);

create index rm_item_actions_gs_item_idx on public.rm_item_actions (gs_item_id);
create index rm_item_actions_decided_by_idx on public.rm_item_actions (decided_by);

-- Pendencies
create table public.pendencies (
  id               uuid primary key default gen_random_uuid(),
  gs_id            uuid not null references public.goods_slips (id) on delete cascade,
  gs_item_id       uuid references public.gs_items (id) on delete cascade,
  qty              integer not null check (qty > 0),
  reason           text not null check (btrim(reason) <> ''),
  sent_to          text,
  blocks_gs        boolean not null default true,
  status           text not null default 'OPEN' check (status in ('OPEN','CLEARED')),
  opened_by        uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  opened_at        timestamptz not null default now(),
  cleared_by       uuid references public.profiles (id) on delete set null,
  cleared_at       timestamptz,
  clearance_notes  text
);

create index pendencies_gs_idx on public.pendencies (gs_id);
create index pendencies_gs_item_idx on public.pendencies (gs_item_id);
create index pendencies_opened_by_idx on public.pendencies (opened_by);
create index pendencies_cleared_by_idx on public.pendencies (cleared_by);
create index pendencies_status_idx on public.pendencies (status);

-- Workflow tasks
create table public.workflow_tasks (
  id                uuid primary key default gen_random_uuid(),
  gs_id             uuid not null references public.goods_slips (id) on delete cascade,
  step_code         text not null check (btrim(step_code) <> ''),
  assigned_role_id  uuid references public.roles (id) on delete set null,
  assigned_user_id  uuid references public.profiles (id) on delete set null,
  status            text not null default 'OPEN' check (status in ('OPEN','DONE','CANCELLED')),
  due_at            timestamptz,
  escalated_at      timestamptz,
  created_at        timestamptz not null default now(),
  completed_at      timestamptz
);

create index workflow_tasks_gs_idx on public.workflow_tasks (gs_id);
create index workflow_tasks_assigned_role_idx on public.workflow_tasks (assigned_role_id);
create index workflow_tasks_assigned_user_idx on public.workflow_tasks (assigned_user_id);
create index workflow_tasks_status_idx on public.workflow_tasks (status);

-- ===========================================================================
-- 2. Generic Inventory Ledger Tables (§8.5)
-- ===========================================================================

create table public.stock_items (
  id               uuid primary key default gen_random_uuid(),
  item_kind        text not null check (item_kind in ('FINISHED_GOOD','SPARE_PART','BATTERY','PACKAGING')),
  product_id       uuid references public.products (id) on delete restrict,
  part_type        text check (part_type in ('TIP','BODY','WIRE','PCB') or part_type is null),
  battery_type_id  uuid references public.battery_types (id) on delete restrict,
  pcb_model_id     uuid references public.pcb_models (id) on delete restrict,
  pcb_supplier_id  uuid references public.pcb_suppliers (id) on delete restrict,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete set null,

  check (part_type <> 'PCB' or (pcb_model_id is not null and pcb_supplier_id is not null)),
  check (item_kind <> 'FINISHED_GOOD' or product_id is not null),
  check (item_kind <> 'BATTERY' or battery_type_id is not null)
);

create index stock_items_product_idx on public.stock_items (product_id);
create index stock_items_battery_type_idx on public.stock_items (battery_type_id);
create index stock_items_pcb_model_idx on public.stock_items (pcb_model_id);
create index stock_items_pcb_supplier_idx on public.stock_items (pcb_supplier_id);
create index stock_items_kind_idx on public.stock_items (item_kind);

create table public.stock_lots (
  id                    uuid primary key default gen_random_uuid(),
  stock_item_id         uuid not null references public.stock_items (id) on delete restrict,
  gs_id                 uuid not null references public.goods_slips (id) on delete cascade,
  gs_item_id            uuid references public.gs_items (id) on delete cascade,
  condition_class       text not null check (condition_class in (
                          'AS_RECEIVED','NOT_ALLOWED','HAZARD','FUNCTIONAL_GOOD',
                          'FUNCTIONAL_REPAIRED','NON_GOOD','NON_SELLABLE','SALVAGED','SCRAP'
                        )),
  source_condition_code text,
  container_id          uuid references public.storage_containers (id) on delete set null,
  partition_id          uuid references public.container_partitions (id) on delete set null,
  is_pending            boolean not null default false,
  created_at            timestamptz not null default now(),
  created_by            uuid default rms_private.current_actor() references public.profiles (id) on delete set null
);

create index stock_lots_item_idx on public.stock_lots (stock_item_id);
create index stock_lots_gs_idx on public.stock_lots (gs_id);
create index stock_lots_gs_item_idx on public.stock_lots (gs_item_id);
create index stock_lots_container_idx on public.stock_lots (container_id);
create index stock_lots_partition_idx on public.stock_lots (partition_id);
create index stock_lots_condition_idx on public.stock_lots (condition_class);

create table public.stock_movements (
  id                uuid primary key default gen_random_uuid(),
  movement_type     text not null check (movement_type in (
                      'INWARD','TRANSFER_OUT','TRANSFER_IN','RECLASSIFY',
                      'CONSUME','RECEIPT','ADJUST','DISMANTLE_IN','DISMANTLE_OUT',
                      'ISSUE','DISPATCH','CREDIT','DISPOSE'
                    )),
  lot_id            uuid not null references public.stock_lots (id) on delete restrict,
  from_location_id  uuid references public.inventory_locations (id) on delete restrict,
  to_location_id    uuid references public.inventory_locations (id) on delete restrict,
  qty               integer not null check (qty > 0),
  reference_type    text,
  reference_id      uuid,
  idempotency_key   text not null unique check (btrim(idempotency_key) <> ''),
  reason            text,
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  created_at        timestamptz not null default now()
);

create index stock_movements_lot_idx on public.stock_movements (lot_id);
create index stock_movements_from_loc_idx on public.stock_movements (from_location_id);
create index stock_movements_to_loc_idx on public.stock_movements (to_location_id);
create index stock_movements_created_at_idx on public.stock_movements (created_at desc);
create index stock_movements_ref_idx on public.stock_movements (reference_type, reference_id);

-- Link rejections.stock_movement_id
alter table public.rejections
  add constraint rejections_stock_movement_fk
  foreign key (stock_movement_id) references public.stock_movements (id) on delete set null;

create index rejections_movement_idx on public.rejections (stock_movement_id);

-- Enforce insert-only on stock_movements
create or replace function rms_private.stock_movements_immutable()
returns trigger
language plpgsql
as $$
begin
  raise exception 'stock_movements is insert-only; updates and deletes are prohibited' using errcode = 'P0001';
end;
$$;

create trigger stock_movements_no_update_delete
before update or delete on public.stock_movements
for each row execute function rms_private.stock_movements_immutable();

-- Balances table
create table public.stock_balances (
  lot_id       uuid not null references public.stock_lots (id) on delete cascade,
  location_id  uuid not null references public.inventory_locations (id) on delete restrict,
  qty          integer not null check (qty >= 0),
  updated_at   timestamptz not null default now(),
  primary key (lot_id, location_id)
);

create index stock_balances_location_idx on public.stock_balances (location_id);

-- Custody transfers
create table public.custody_transfers (
  id                   uuid primary key default gen_random_uuid(),
  transfer_no          text not null unique check (btrim(transfer_no) <> ''),
  from_location_id     uuid not null references public.inventory_locations (id) on delete restrict,
  to_location_id       uuid not null references public.inventory_locations (id) on delete restrict,
  transit_location_id  uuid references public.inventory_locations (id) on delete restrict,
  mode_code            text not null default 'PHYSICAL_AND_DIGITAL',
  status               text not null default 'INITIATED' check (status in ('INITIATED','ACCEPTED','DISCREPANCY','RECONCILED','CANCELLED')),
  initiated_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  initiated_at         timestamptz not null default now(),
  accepted_by          uuid references public.profiles (id) on delete set null,
  accepted_at          timestamptz,
  acceptance_code      text,
  discrepancy_notes    text,
  created_at           timestamptz not null default now()
);

create index custody_transfers_from_idx on public.custody_transfers (from_location_id);
create index custody_transfers_to_idx on public.custody_transfers (to_location_id);
create index custody_transfers_transit_idx on public.custody_transfers (transit_location_id);
create index custody_transfers_initiated_by_idx on public.custody_transfers (initiated_by);
create index custody_transfers_accepted_by_idx on public.custody_transfers (accepted_by);
create index custody_transfers_status_idx on public.custody_transfers (status);

create table public.custody_transfer_lines (
  id            uuid primary key default gen_random_uuid(),
  transfer_id   uuid not null references public.custody_transfers (id) on delete cascade,
  lot_id        uuid not null references public.stock_lots (id) on delete restrict,
  qty_sent      integer not null check (qty_sent > 0),
  qty_counted   integer not null default 0 check (qty_counted >= 0),
  qty_accepted  integer not null default 0 check (qty_accepted >= 0)
);

create index custody_transfer_lines_transfer_idx on public.custody_transfer_lines (transfer_id);
create index custody_transfer_lines_lot_idx on public.custody_transfer_lines (lot_id);

-- Packaging replacements
create table public.packaging_replacements (
  id       uuid primary key default gen_random_uuid(),
  lot_id   uuid not null references public.stock_lots (id) on delete cascade,
  qty      integer not null check (qty > 0),
  remarks  text,
  "by"     uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  "at"     timestamptz not null default now()
);

create index packaging_replacements_lot_idx on public.packaging_replacements (lot_id);
create index packaging_replacements_by_idx on public.packaging_replacements ("by");

-- ===========================================================================
-- 3. Stock Movement Function (rms_private.rms_move_stock)
-- ===========================================================================

create or replace function rms_private.rms_move_stock(
  p_lot         uuid,
  p_from        uuid,
  p_to          uuid,
  p_qty         integer,
  p_type        text,
  p_ref_type    text,
  p_ref_id      uuid,
  p_idem_key    text,
  p_actor       uuid default null,
  p_reason      text default null
) returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_existing_id     uuid;
  v_existing_lot    uuid;
  v_existing_from   uuid;
  v_existing_to     uuid;
  v_existing_qty    integer;
  v_existing_type   text;
  v_lot             record;
  v_to_loc          record;
  v_current_balance integer;
  v_movement_id     uuid;
begin
  -- 1. Idempotency Check
  if p_idem_key is not null and btrim(p_idem_key) <> '' then
    select id, lot_id, from_location_id, to_location_id, qty, movement_type
      into v_existing_id, v_existing_lot, v_existing_from, v_existing_to, v_existing_qty, v_existing_type
      from public.stock_movements
     where idempotency_key = p_idem_key;

    if found then
      if v_existing_lot = p_lot
         and v_existing_from is not distinct from p_from
         and v_existing_to is not distinct from p_to
         and v_existing_qty = p_qty
         and v_existing_type = p_type then
        return v_existing_id;
      else
        raise exception 'G-16: Idempotency conflict for stock movement key %', p_idem_key using errcode = 'P0001';
      end if;
    end if;
  else
    raise exception 'G-16: Idempotency key is required for stock movements' using errcode = 'P0001';
  end if;

  -- 2. Basic Parameter Validation
  if p_lot is null then
    raise exception 'Lot ID cannot be null' using errcode = 'P0001';
  end if;

  if p_qty is null or p_qty <= 0 then
    raise exception 'G-16: Movement quantity must be greater than zero' using errcode = 'P0001';
  end if;

  if p_from is null and p_to is null then
    raise exception 'Source and destination locations cannot both be null' using errcode = 'P0001';
  end if;

  if p_from is not null and p_to is not null and p_from = p_to then
    raise exception 'Source and destination locations cannot be the same' using errcode = 'P0001';
  end if;

  if p_from is null and p_type not in ('INWARD','RECEIPT','ADJUST','RECLASSIFY') then
    raise exception 'Source location is required for movement type %', p_type using errcode = 'P0001';
  end if;

  if p_to is null and p_type not in ('CONSUME','DISPOSE','DISPATCH','ADJUST','RECLASSIFY') then
    raise exception 'Destination location is required for movement type %', p_type using errcode = 'P0001';
  end if;

  -- 3. Fetch lot details
  select * into v_lot from public.stock_lots where id = p_lot;
  if not found then
    raise exception 'Lot % not found', p_lot using errcode = 'P0001';
  end if;

  -- 4. Apply System Guards on Destination Location
  if p_to is not null then
    select * into v_to_loc from public.inventory_locations where id = p_to;
    if not found then
      raise exception 'Destination location % not found', p_to using errcode = 'P0001';
    end if;

    -- Guard G-04: lot.condition_class IN (NOT_ALLOWED, HAZARD, NON_GOOD, NON_SELLABLE, SCRAP)
    -- cannot move to location_class in (FUNCTIONAL, MAIN_STORE, DISPATCHED)
    if v_lot.condition_class in ('NOT_ALLOWED','HAZARD','NON_GOOD','NON_SELLABLE','SCRAP')
       and v_to_loc.location_class in ('FUNCTIONAL','MAIN_STORE','DISPATCHED') then
      raise exception 'G-04: Lot condition % cannot move to % location', v_lot.condition_class, v_to_loc.location_class using errcode = 'P0001';
    end if;

    -- Guard G-05: HAZARD lots can only go to HAZARD_QUARANTINE or SCRAP_DISPOSED
    if v_lot.condition_class = 'HAZARD'
       and v_to_loc.location_class not in ('HAZARD_QUARANTINE','SCRAP_DISPOSED') then
      raise exception 'G-05: HAZARD lots can only move to HAZARD_QUARANTINE or SCRAP_DISPOSED (target was %)', v_to_loc.location_class using errcode = 'P0001';
    end if;

    -- Guard G-12: FUNCTIONAL locations accept only AS_RECEIVED (allowed conditions), FUNCTIONAL_GOOD and FUNCTIONAL_REPAIRED lots
    if v_to_loc.location_class = 'FUNCTIONAL'
       and v_lot.condition_class not in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED') then
      raise exception 'G-12: FUNCTIONAL locations accept only AS_RECEIVED, FUNCTIONAL_GOOD and FUNCTIONAL_REPAIRED lots (attempted %)', v_lot.condition_class using errcode = 'P0001';
    end if;

    -- Guard G-08: lots with is_pending=true cannot move to TRANSIT/FUNCTIONAL
    if v_lot.is_pending = true
       and v_to_loc.location_class in ('TRANSIT','FUNCTIONAL') then
      raise exception 'G-08: Lots marked Pending (BP) cannot move to TRANSIT or FUNCTIONAL locations' using errcode = 'P0001';
    end if;
  end if;

  -- 5. Deduct from Source Balance (with row-level lock)
  if p_from is not null then
    select qty into v_current_balance
      from public.stock_balances
     where lot_id = p_lot and location_id = p_from
       for update;

    if not found or v_current_balance < p_qty then
      raise exception 'G-16: Insufficient stock balance for lot % at location % (available %, requested %)', p_lot, p_from, coalesce(v_current_balance, 0), p_qty using errcode = 'P0001';
    end if;

    update public.stock_balances
       set qty = qty - p_qty,
           updated_at = now()
     where lot_id = p_lot and location_id = p_from;
  end if;

  -- 6. Credit Destination Balance
  if p_to is not null then
    insert into public.stock_balances (lot_id, location_id, qty, updated_at)
    values (p_lot, p_to, p_qty, now())
    on conflict (lot_id, location_id)
    do update set qty = public.stock_balances.qty + excluded.qty, updated_at = now();
  end if;

  -- 7. Insert Movement Record
  insert into public.stock_movements (
    lot_id, from_location_id, to_location_id, qty, movement_type,
    reference_type, reference_id, idempotency_key, reason, created_by, created_at
  ) values (
    p_lot, p_from, p_to, p_qty, p_type,
    p_ref_type, p_ref_id, p_idem_key, p_reason, coalesce(p_actor, rms_private.current_actor()), now()
  ) returning id into v_movement_id;

  return v_movement_id;
end;
$$;

-- ===========================================================================
-- 4. Reclassify Lot Function (rms_private.rms_reclassify_lot)
-- ===========================================================================

create or replace function rms_private.rms_reclassify_lot(
  p_source_lot  uuid,
  p_target_lot  uuid,
  p_location    uuid,
  p_qty         integer,
  p_ref_type    text,
  p_ref_id      uuid,
  p_idem_key    text,
  p_actor       uuid default null,
  p_reason      text default null
) returns uuid[]
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_target_lot record;
  v_loc        record;
  v_m1         uuid;
  v_m2         uuid;
begin
  if p_source_lot is null or p_target_lot is null then
    raise exception 'Source and target lot IDs cannot be null' using errcode = 'P0001';
  end if;

  if p_source_lot = p_target_lot then
    raise exception 'Source and target lot cannot be the same' using errcode = 'P0001';
  end if;

  if p_location is null then
    raise exception 'Location ID cannot be null for reclassification' using errcode = 'P0001';
  end if;

  if p_qty is null or p_qty <= 0 then
    raise exception 'G-16: Reclassification quantity must be greater than zero' using errcode = 'P0001';
  end if;

  -- Fetch target lot and location
  select * into v_target_lot from public.stock_lots where id = p_target_lot;
  if not found then
    raise exception 'Target lot % not found', p_target_lot using errcode = 'P0001';
  end if;

  select * into v_loc from public.inventory_locations where id = p_location;
  if not found then
    raise exception 'Location % not found', p_location using errcode = 'P0001';
  end if;

  -- Apply guards on target lot condition in this location
  if v_target_lot.condition_class in ('NOT_ALLOWED','HAZARD','NON_GOOD','NON_SELLABLE','SCRAP')
     and v_loc.location_class in ('FUNCTIONAL','MAIN_STORE','DISPATCHED') then
    raise exception 'G-04: Cannot reclassify to condition % in % location', v_target_lot.condition_class, v_loc.location_class using errcode = 'P0001';
  end if;

  if v_target_lot.condition_class = 'HAZARD'
     and v_loc.location_class not in ('HAZARD_QUARANTINE','SCRAP_DISPOSED') then
    raise exception 'G-05: HAZARD lots can only exist in HAZARD_QUARANTINE or SCRAP_DISPOSED' using errcode = 'P0001';
  end if;

  if v_loc.location_class = 'FUNCTIONAL'
     and v_target_lot.condition_class not in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED') then
    raise exception 'G-12: FUNCTIONAL locations accept only AS_RECEIVED, FUNCTIONAL_GOOD and FUNCTIONAL_REPAIRED lots' using errcode = 'P0001';
  end if;

  if v_target_lot.is_pending = true
     and v_loc.location_class in ('TRANSIT','FUNCTIONAL') then
    raise exception 'G-08: Lots marked Pending (BP) cannot move to TRANSIT or FUNCTIONAL locations' using errcode = 'P0001';
  end if;

  -- Movement 1: Out of source lot
  v_m1 := rms_private.rms_move_stock(
    p_lot => p_source_lot,
    p_from => p_location,
    p_to => null,
    p_qty => p_qty,
    p_type => 'RECLASSIFY',
    p_ref_type => p_ref_type,
    p_ref_id => p_ref_id,
    p_idem_key => p_idem_key || ':OUT',
    p_actor => p_actor,
    p_reason => coalesce(p_reason, 'Reclassify out to lot ' || p_target_lot::text)
  );

  -- Movement 2: Into target lot
  v_m2 := rms_private.rms_move_stock(
    p_lot => p_target_lot,
    p_from => null,
    p_to => p_location,
    p_qty => p_qty,
    p_type => 'RECLASSIFY',
    p_ref_type => p_ref_type,
    p_ref_id => p_ref_id,
    p_idem_key => p_idem_key || ':IN',
    p_actor => p_actor,
    p_reason => coalesce(p_reason, 'Reclassify in from lot ' || p_source_lot::text)
  );

  return array[v_m1, v_m2];
end;
$$;

-- ===========================================================================
-- 5. Location Class Freeze Trigger on inventory_locations
-- ===========================================================================

create or replace function rms_private.check_inventory_location_class_change()
returns trigger
language plpgsql
as $$
begin
  if old.location_class is distinct from new.location_class then
    if exists (
      select 1 from public.stock_balances
      where location_id = old.id and qty > 0
    ) then
      raise exception 'Cannot change location_class for location % while positive stock balance exists', old.id using errcode = 'P0001';
    end if;
  end if;
  return new;
end;
$$;

create trigger inventory_location_class_immutable_with_balance
before update on public.inventory_locations
for each row execute function rms_private.check_inventory_location_class_change();

-- ===========================================================================
-- 6. RLS on All New Operational and Ledger Tables
-- ===========================================================================

alter table public.goods_slips enable row level security;
alter table public.gs_status_history enable row level security;
alter table public.attachments enable row level security;
alter table public.gs_documents enable row level security;
alter table public.gs_items enable row level security;
alter table public.csr_approvals enable row level security;
alter table public.inspections enable row level security;
alter table public.inspection_allocations enable row level security;
alter table public.extraction_records enable row level security;
alter table public.container_audit_days enable row level security;
alter table public.container_audit_lines enable row level security;
alter table public.rejections enable row level security;
alter table public.rm_item_actions enable row level security;
alter table public.pendencies enable row level security;
alter table public.workflow_tasks enable row level security;
alter table public.stock_items enable row level security;
alter table public.stock_lots enable row level security;
alter table public.stock_movements enable row level security;
alter table public.stock_balances enable row level security;
alter table public.custody_transfers enable row level security;
alter table public.custody_transfer_lines enable row level security;
alter table public.packaging_replacements enable row level security;

-- Realtime task inbox policy for authenticated users on workflow_tasks
create policy workflow_tasks_select_own on public.workflow_tasks
for select to authenticated
using (
  assigned_user_id = auth.uid()
  or exists (
    select 1 from public.user_roles ur
    where ur.user_id = auth.uid() and ur.role_id = workflow_tasks.assigned_role_id
  )
);

-- Attach standard triggers (updated_at + audit_row)
select rms_private.attach_standard_triggers('public.goods_slips');
select rms_private.attach_standard_triggers('public.gs_status_history');
select rms_private.attach_standard_triggers('public.attachments');
select rms_private.attach_standard_triggers('public.gs_documents');
select rms_private.attach_standard_triggers('public.gs_items');
select rms_private.attach_standard_triggers('public.csr_approvals');
select rms_private.attach_standard_triggers('public.inspections');
select rms_private.attach_standard_triggers('public.inspection_allocations');
select rms_private.attach_standard_triggers('public.extraction_records');
select rms_private.attach_standard_triggers('public.container_audit_days');
select rms_private.attach_standard_triggers('public.container_audit_lines');
select rms_private.attach_standard_triggers('public.rejections');
select rms_private.attach_standard_triggers('public.rm_item_actions');
select rms_private.attach_standard_triggers('public.pendencies');
select rms_private.attach_standard_triggers('public.workflow_tasks');
select rms_private.attach_standard_triggers('public.stock_items');
select rms_private.attach_standard_triggers('public.stock_lots');
select rms_private.attach_standard_triggers('public.stock_movements');
select rms_private.attach_standard_triggers('public.stock_balances');
select rms_private.attach_standard_triggers('public.custody_transfers');
select rms_private.attach_standard_triggers('public.custody_transfer_lines');
select rms_private.attach_standard_triggers('public.packaging_replacements');

-- Grant permissions to rms_api role
grant select, insert, update, delete on
  public.goods_slips,
  public.gs_status_history,
  public.attachments,
  public.gs_documents,
  public.gs_items,
  public.csr_approvals,
  public.inspections,
  public.inspection_allocations,
  public.extraction_records,
  public.container_audit_days,
  public.container_audit_lines,
  public.rejections,
  public.rm_item_actions,
  public.pendencies,
  public.workflow_tasks,
  public.stock_items,
  public.stock_lots,
  public.stock_movements,
  public.stock_balances,
  public.custody_transfers,
  public.custody_transfer_lines,
  public.packaging_replacements
to rms_api;

revoke update, delete, truncate on public.stock_movements from rms_api, public, authenticated, anon;

-- Revoke execute from public/anon/authenticated on rms_private functions per G-17/RLS security model
revoke all on function rms_private.rms_move_stock(uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text) from public, authenticated, anon;
revoke all on function rms_private.rms_reclassify_lot(uuid, uuid, uuid, integer, text, uuid, text, uuid, text) from public, authenticated, anon;
revoke all on function rms_private.stock_movements_immutable() from public, authenticated, anon;
revoke all on function rms_private.check_inventory_location_class_change() from public, authenticated, anon;

grant execute on function rms_private.rms_move_stock(uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text) to rms_api;
grant execute on function rms_private.rms_reclassify_lot(uuid, uuid, uuid, integer, text, uuid, text, uuid, text) to rms_api;
