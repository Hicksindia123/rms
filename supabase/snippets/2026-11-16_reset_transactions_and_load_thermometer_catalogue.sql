-- =============================================================================
-- ONE-OFF PRODUCTION DATA RESET (2026-11-16). Run once in the Supabase SQL editor.
--
--   1. Removes every Goods Slip (GS) and all transaction data created by user actions:
--      GS items, counts, inspections, RM reviews, AC slips, dispatches, credit notes, stock lots,
--      stock movements and balances, custody transfers, notifications, party emails, attachment
--      records, print logs, idempotency keys and number-series counters (GS numbers restart).
--   2. Removes every product and every product sub-category.
--   3. Loads the 19-item thermometer catalogue (items CSV, 2026-11-16).
--
-- KEPT: users, roles, permissions, parties, transporters, states/stations, locations, containers,
-- technicians, forms, workflows, option lists, item field profiles (category level), settings,
-- branding. Also KEPT: audit_log, config_change_log, user_activity and system_guard_events
-- (append-only ledgers; audit_log and config_change_log refuse deletion by design).
--
-- Category mapping (user decision 2026-11-16): the business rules are per CATEGORY (DEC-15/DEC-18
-- DMT battery + dismantling, G-05 hazard, G-06/BR-14 full opening, condition lists), so each CSV
-- sub-category maps to the rule category it belongs to. The category codes stay the same (logic
-- keys off codes). Only the labels change. Each category gets a sub-category "Thermometer".
--     CSV "Digital Thermometer"   -> DMT            (label "Digital Thermometer")
--     CSV "Prismatic Thermometer" -> PRISMATIC      (label "Prismatic Thermometer")
--     CSV "Enclosed Scale"        -> ENCLOSED_OVAL  (label "Enclosed Scale")
--
-- Files in Storage are NOT removed by this script (Supabase blocks SQL deletes on storage.objects;
-- removing the rows would orphan the files). Empty the rms-documents and rms-videos buckets in the
-- dashboard instead. Do NOT empty rms-branding (it holds the logo).
--
-- Everything runs in one transaction: any error rolls the whole script back.
-- =============================================================================

begin;

-- ---------------------------------------------------------------------------
-- 1. Transactions. TRUNCATE ... CASCADE also empties every table that references these
--    (all GS / stock / workflow children). Verified against the schema: no configuration table
--    references a transaction table.
-- ---------------------------------------------------------------------------
truncate table
  public.goods_slips,
  public.stock_items,
  public.dismantle_batches,
  public.container_audit_days,
  public.custody_transfers,
  public.technician_batches,
  public.store_issues,
  public.notification_events,
  public.notifications,
  public.attachments,
  public.credit_notes,
  public.form_responses,
  public.print_logs,
  public.number_series_counters,
  rms_private.idempotency_keys
cascade;

-- ---------------------------------------------------------------------------
-- 2. Products and sub-categories (category-level item field profiles are kept).
-- ---------------------------------------------------------------------------
delete from public.item_field_assignments where scope_type in ('PRODUCT', 'SUBCATEGORY');
delete from public.products;
delete from public.product_subcategories;

-- ---------------------------------------------------------------------------
-- 3. Category labels + "Thermometer" sub-category under each thermometer category.
-- ---------------------------------------------------------------------------
do $$
begin
  if (select count(*) from public.product_categories
       where code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL')) <> 3 then
    raise exception 'Expected categories DMT, PRISMATIC and ENCLOSED_OVAL to exist; aborting';
  end if;
end $$;

update public.product_categories c
   set name = v.name, is_active = true, updated_at = now()
  from (values
    ('DMT',           'Digital Thermometer'),
    ('PRISMATIC',     'Prismatic Thermometer'),
    ('ENCLOSED_OVAL', 'Enclosed Scale')
  ) as v(code, name)
 where c.code = v.code;

insert into public.product_subcategories (category_id, code, name, is_active)
select c.id, 'THERMOMETER', 'Thermometer', true
  from public.product_categories c
 where c.code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL');

-- ---------------------------------------------------------------------------
-- 4. Products (names verbatim from the CSV).
-- ---------------------------------------------------------------------------
insert into public.products (code, name, category_id, subcategory_id, uom, is_active)
select v.code, v.name, c.id, s.id, 'PCS', true
  from (values
    ('ITM-00001', 'ECO XL Mercury Free Thermometer',                    'ENCLOSED_OVAL'),
    ('ITM-00002', 'O-01 Oval Thermometers',                             'ENCLOSED_OVAL'),
    ('ITM-00003', 'DMT-102 Digital (With Beeper Alarm)',                'DMT'),
    ('ITM-00004', 'DMT-106A Candy Digital Thermometer (Bucket)',        'DMT'),
    ('ITM-00005', 'MT-401R Digital FastRead',                           'DMT'),
    ('ITM-00006', 'DMT-423 Flexible Digital Thermometer',               'DMT'),
    ('ITM-00007', 'DMT-437 Baby Digital Thermometer',                   'DMT'),
    ('ITM-00008', 'DT-10 Digital Thermometer',                          'DMT'),
    ('ITM-00009', 'DMT-425T Akutem Digital Thermometer',                'DMT'),
    ('ITM-00010', 'MT-201 Oval Digital Thermometer',                    'DMT'),
    ('ITM-00011', 'DT-12 Digital Thermometer',                          'DMT'),
    ('ITM-00012', 'NT-INFRA Infrared Non-Contact Thermometer',          'DMT'),
    ('ITM-00013', 'A-01 Akutem Prismatic Thermometer',                  'PRISMATIC'),
    ('ITM-00014', 'A-02 Dumark (Blister Pack) Prismatic Thermometer',   'PRISMATIC'),
    ('ITM-00015', 'A-03 Optima (Inblister Pack) Prismatic Thermometer', 'PRISMATIC'),
    ('ITM-00016', 'A-05 Rectal (Blister Pack) Prismatic Thermometer',   'PRISMATIC'),
    ('ITM-00017', 'A-06 Veterinary (Blister Pack) Prismatic Thermometer', 'PRISMATIC'),
    ('ITM-00018', 'I-01 (Large) Room Thermometer',                      'PRISMATIC'),
    ('ITM-00019', 'I-02 (Big) Room Thermometer',                        'PRISMATIC')
  ) as v(code, name, category)
  join public.product_categories c on c.code = v.category
  join public.product_subcategories s on s.category_id = c.id and s.code = 'THERMOMETER';

-- ---------------------------------------------------------------------------
-- 5. Self-check: abort (roll back) unless the result is exactly as intended.
-- ---------------------------------------------------------------------------
do $$
begin
  if (select count(*) from public.goods_slips) <> 0
     or (select count(*) from public.stock_movements) <> 0
     or (select count(*) from public.stock_balances) <> 0 then
    raise exception 'Transactions were not fully removed; aborting';
  end if;
  if (select count(*) from public.products) <> 19 then
    raise exception 'Expected 19 products, found %; aborting', (select count(*) from public.products);
  end if;
end $$;

commit;

-- Result (read-only): the new catalogue.
select c.name as category, s.name as sub_category, p.code, p.name as product
  from public.products p
  join public.product_categories c on c.id = p.category_id
  left join public.product_subcategories s on s.id = p.subcategory_id
 order by c.name, p.code;
