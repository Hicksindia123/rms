/**
 * P3-08 · Full-lifecycle building blocks against the REAL local stack (no mocks).
 *
 * Every step is one business command performed by the role that owns it in the workbook (gate →
 * Anuj, Step-2/3 → Aman, RM → Pratham, Intermediate Store → Sahil, Spare Parts → SPT/SPM, Accounts →
 * Deepak Ji, Dispatch). The lifecycle specs call these for the steps they do not drive through the
 * UI, and run `scripts/integrity_check.sql` after every scenario.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  addItem,
  api,
  categorize,
  createGs,
  inspectByApi,
  productId,
  unboxed,
  USERS,
  type Gs,
} from './stack';

export const DEMO_DMT = 'DEMO-DMT-001';
export const DEMO_PRISMATIC = 'DEMO-PRS-001';
export const TODAY = new Date().toISOString().slice(0, 10);

// --- types ---------------------------------------------------------------------------------------
interface Lot {
  lot_id: string;
  gs_no?: string | null;
  gs_id?: string | null;
  gs_item_id?: string | null;
  condition_class: string;
  source_condition_code?: string | null;
  balance?: number;
  qty?: number;
  available_qty?: number;
}
interface Transfer {
  id: string;
  status: string;
  lines: Array<{ lot_id: string; qty_sent: number }>;
}
export interface ChecklistItem {
  code: string;
  applicable: boolean;
  passed: boolean;
}
export interface Closure {
  can_close: boolean;
  items: ChecklistItem[];
}

const uniq = (p: string) => `${p}-${String(Date.now())}-${String(Math.floor(Math.random() * 1e6))}`;

// --- Step 1–3 ------------------------------------------------------------------------------------
/** Gate → unboxing → one itemised line → categorised. Returns the GS and its line. */
export async function inwardLine(
  tag: string,
  product: string,
  qty: number,
  category: 'RO' | 'CSR' = 'RO',
): Promise<{ gs: Gs; item: string }> {
  const gs = await createGs(tag);
  await unboxed(gs);
  const item = await addItem(gs.id, await productId(product), qty, qty);
  await categorize(gs.id, category);
  return { gs, item };
}

export async function csrApprove(gsId: string): Promise<void> {
  await api(
    USERS.rm,
    'POST',
    `/gs/${gsId}/csr-decision`,
    {
      decision: 'CSR_APPROVED',
      remarks: 'P3-08 lifecycle: full sales return checked',
    },
    true,
  );
}

export const inspect = inspectByApi;

export async function rmActions(
  gsId: string,
  lines: Array<{ item: string; actions: Record<string, number> }>,
  extra: { reason?: string; pendency_details?: Record<string, unknown> } = {},
): Promise<void> {
  await api(USERS.rm, 'PUT', `/gs/${gsId}/rm-actions`, {
    lines: lines.map((l) => ({
      gs_item_id: l.item,
      actions: Object.entries(l.actions).map(([action_code, qty]) => ({ action_code, qty })),
    })),
    ...extra,
  });
  await api(USERS.rm, 'POST', `/gs/${gsId}/rm-actions/finalise`, {});
}

// --- Step 4 handover (BR-21, G-09) ---------------------------------------------------------------
export async function initiateHandover(gsId: string): Promise<Transfer> {
  return api<Transfer>(USERS.aman, 'POST', `/gs/${gsId}/handover`, {}, true);
}

export async function transfer(id: string): Promise<Transfer> {
  return api<Transfer>(USERS.sahil, 'GET', `/custody/transfers/${id}`);
}

export async function acceptAll(transferId: string, as: string = USERS.sahil): Promise<void> {
  const t = await transfer(transferId);
  await api(
    as,
    'POST',
    `/custody/transfers/${transferId}/accept`,
    {
      lines: t.lines.map((l) => ({ lot_id: l.lot_id, qty_counted: l.qty_sent })),
      acceptance_code: 'ACCEPTED_VERIFIED',
    },
    true,
  );
}

export async function handover(gsId: string): Promise<string> {
  const t = await initiateHandover(gsId);
  await acceptAll(t.id);
  return t.id;
}

// --- Intermediate Store, technician, battery (BR-22..BR-25, G-10, DEC-14) ------------------------
export async function storeLots(gsId: string): Promise<Lot[]> {
  const lots = await api<Lot[]>(USERS.sahil, 'GET', '/servicing/intermediate-lots');
  return lots.filter((l) => l.gs_id === gsId);
}

/** DEC-14: visually-OK packed pieces are classified Functional Good directly by Sahil. */
export async function classifyGood(lotId: string, qty: number): Promise<void> {
  await api(
    USERS.sahil,
    'POST',
    `/custody/lots/${lotId}/classify`,
    { qty, remarks: 'P3-08: visually OK and packed' },
    true,
  );
}

export async function technicianId(): Promise<string> {
  const techs = await api<Array<{ id: string; display_name: string }>>(
    USERS.sahil,
    'GET',
    '/servicing/technicians',
  );
  const t = techs[0];
  if (!t) throw new Error('no technician is configured (demo user rajkumar@rms.local)');
  return t.id;
}

export async function batteryTypeId(code = 'LR44'): Promise<string> {
  const types = await api<Array<{ id: string; code: string }>>(
    USERS.spm,
    'GET',
    '/inventory/batteries/types',
  );
  const t = types.find((x) => x.code === code);
  if (!t) throw new Error(`battery type ${code} missing`);
  return t.id;
}

export async function batteryBalance(code = 'LR44'): Promise<number> {
  const rows = await api<Array<{ code: string; balance: number }>>(
    USERS.spm,
    'GET',
    '/inventory/batteries/balances',
  );
  return rows.find((x) => x.code === code)?.balance ?? 0;
}

export async function receiveBatteries(qty: number, code = 'LR44'): Promise<void> {
  await api(
    USERS.spm,
    'POST',
    '/inventory/batteries/receipts',
    { battery_type: code, qty, ref: uniq('P308-BAT') },
    true,
  );
}

interface Batch {
  id: string;
  lines: Array<{ id: string; lot_id: string; qty_allotted: number }>;
}

export async function allot(lines: Array<{ lot_id: string; qty: number }>): Promise<Batch> {
  return api<Batch>(
    USERS.sahil,
    'POST',
    '/servicing/batches',
    { technician_id: await technicianId(), lines },
    true,
  );
}

export interface ReceiveLine {
  lot_id: string;
  qty: number;
  allocations: Partial<
    Record<'FUNCTIONAL_GOOD' | 'FUNCTIONAL_REPAIRED' | 'NON_GOOD' | 'NON_SELLABLE', number>
  >;
  battery?: { replaced: number; checked: number } | 'OK';
  cleaning_code?: string;
}

export async function receive(batch: Batch, lines: ReceiveLine[]): Promise<void> {
  const typeId = await batteryTypeId();
  await api(
    USERS.sahil,
    'POST',
    `/servicing/batches/${batch.id}/receive`,
    {
      lines: lines.map((l) => {
        const bl = batch.lines.find((x) => x.lot_id === l.lot_id);
        if (!bl) throw new Error(`lot ${l.lot_id} is not in batch ${batch.id}`);
        const battery =
          l.battery === undefined || l.battery === 'OK'
            ? { battery_check_code: 'BATTERY_OK', pieces_checked: l.qty }
            : {
                battery_check_code: 'BATTERY_REPLACED',
                pieces_checked: l.battery.checked,
                batteries_installed: l.battery.replaced,
                battery_type_id: typeId,
              };
        return {
          batch_line_id: bl.id,
          qty_receiving: l.qty,
          allocations: l.allocations,
          ...battery,
          ...(l.cleaning_code ? { cleaning_code: l.cleaning_code } : {}),
        };
      }),
    },
    true,
  );
}

// --- Dismantling (BR-26..BR-29, G-11) ------------------------------------------------------------
export async function dismantleQueue(): Promise<{
  dismantleable_lots: Lot[];
  disposal_required_lots: Lot[];
}> {
  return api(USERS.spt, 'GET', '/dismantling/queue');
}

export async function dismantleWithPcb(lotId: string, qty: number): Promise<string> {
  const batch = await api<{ id: string }>(
    USERS.spt,
    'POST',
    '/dismantling/batches',
    { inputs: [{ lot_id: lotId, qty }], storage_method_code: 'DEDICATED_CONTAINERS' },
    true,
  );
  const containers = await api<
    Array<{ id: string; dedicated_part_type: string | null; storage_method: string }>
  >(USERS.spt, 'GET', '/dismantling/containers?storage_method=DEDICATED_CONTAINERS');
  const box = (part: string) => {
    const c = containers.find((x) => x.dedicated_part_type === part);
    if (!c) throw new Error(`no dedicated container for ${part}`);
    return c.id;
  };
  const models = await api<Array<{ id: string }>>(USERS.spt, 'GET', '/dismantling/pcb-models');
  const suppliers = await api<Array<{ id: string }>>(
    USERS.spt,
    'GET',
    '/dismantling/pcb-suppliers',
  );
  await api(
    USERS.spt,
    'POST',
    `/dismantling/batches/${batch.id}/recover`,
    {
      units_dismantled: qty,
      parts: [
        { part_type: 'TIP', qty, container_id: box('TIP') },
        { part_type: 'BODY', qty, container_id: box('BODY') },
        {
          part_type: 'PCB',
          qty,
          container_id: box('PCB'),
          pcb_model_id: models[0]?.id,
          pcb_supplier_id: suppliers[0]?.id,
        },
      ],
      scrap: { qty_pieces: 0, hazardous: false, remarks: 'P3-08 lifecycle' },
    },
    true,
  );
  return batch.id;
}

/** DEC-11 / DEC-18: the Spare Parts Manager marks quarantined stock as scrap, then disposes it. */
export async function disposeHazard(lotId: string, qty: number, manifest: string): Promise<string> {
  const scrap = await api<{ id: string; hazardous: boolean }>(
    USERS.spm,
    'POST',
    '/scrap/from-lot',
    { lot_id: lotId, qty, remarks: 'P3-08 lifecycle: mercury hazard' },
    true,
  );
  if (!scrap.hazardous) throw new Error('quarantined mercury stock must be marked hazardous');
  await api(USERS.spm, 'POST', `/scrap/${scrap.id}/dispose`, { manifest_ref: manifest }, true);
  return scrap.id;
}

export async function hazardLots(gsId: string): Promise<Array<{ lot_id: string; qty: number }>> {
  const page = await api<{ items: Array<{ lot_id: string; gs_id: string | null; qty: number }> }>(
    USERS.spm,
    'GET',
    `/inventory/stock?view=HAZARD_QUARANTINE&page_size=100`,
  );
  return page.items.filter((r) => r.gs_id === gsId);
}

// --- Main Store issue & dispatch (BR-31, DEC-21, DEC-26) -----------------------------------------
export async function functionalLots(gsId: string): Promise<Lot[]> {
  const lots = await api<Lot[]>(USERS.sahil, 'GET', '/store-issues/candidate-lots');
  return lots.filter((l) => l.gs_id === gsId);
}

export async function issueToMainStore(gsId: string, only?: string): Promise<void> {
  const lots = (await functionalLots(gsId)).filter((l) => !only || l.condition_class === only);
  if (lots.length === 0) throw new Error(`no functional stock of GS ${gsId} to issue`);
  await api(
    USERS.sahil,
    'POST',
    '/store-issues',
    {
      issue_type_code: 'ISSUE_MAIN_STORE',
      lines: lots.map((l) => ({ lot_id: l.lot_id, qty: l.available_qty ?? 0 })),
      notes: 'P3-08 lifecycle',
    },
    true,
  );
}

export async function dispatch(
  gsId: string,
  type: 'SEND_NEW' | 'SEND_REPAIRED',
  lines: Array<{ item: string; qty: number; lot_id?: string }>,
): Promise<void> {
  await api(
    USERS.dispatch,
    'POST',
    '/dispatches',
    {
      gs_id: gsId,
      dispatch_type: type,
      lines: lines.map((l) => ({ gs_item_id: l.item, qty: l.qty, lot_id: l.lot_id ?? null })),
      transporter: 'DTDC',
      docket_no: uniq('DKT'),
      ref_doc_no: uniq('CH'),
      ref_doc_date: TODAY,
    },
    true,
  );
}

// --- Step 7 commercial (BR-32..BR-37, G-13, G-14) ------------------------------------------------
export async function cnDecision(
  gsId: string,
  lines: Array<{ item: string; qty: number; decision: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT' }>,
  deviation_reason?: string,
): Promise<void> {
  await api(USERS.rm, 'POST', `/gs/${gsId}/cn-decision`, {
    lines: lines.map((l) => ({ gs_item_id: l.item, qty: l.qty, decision: l.decision })),
    ...(deviation_reason ? { deviation_reason } : {}),
  });
}

interface CreditNote {
  id: string;
  cn_type_code: string;
  status: string;
  lines: Array<{ id: string }>;
}

/** Accounts: draft → party document → GST portal → (type) → rates → issue. Returns the CN. */
export async function creditNote(
  gsId: string,
  lines: Array<{ item: string; qty: number; lot_id?: string }>,
  opts: { type: 'GST_CN' | 'GENERAL_CN'; portal: 'GST_REFLECTED' | 'GST_NOT_REFLECTED' },
): Promise<CreditNote> {
  const created = await api<CreditNote>(
    USERS.accounts,
    'POST',
    '/credit-notes',
    {
      gs_id: gsId,
      cn_type_code: opts.type === 'GST_CN' ? 'GENERAL_CN' : opts.type,
      lines: lines.map((l) => ({ gs_item_id: l.item, qty: l.qty, lot_id: l.lot_id ?? null })),
    },
    true,
  );
  const id = created.id;
  await api(USERS.accounts, 'PATCH', `/credit-notes/${id}/party-document`, {
    party_doc_code: 'PARTY_DEBIT_NOTE',
    doc_no: uniq('DN'),
    doc_date: TODAY,
    amount: 1000,
  });
  await api(USERS.accounts, 'PATCH', `/credit-notes/${id}/gst-check`, {
    gst_portal_code: opts.portal,
    return_type: 'GSTR-1',
    return_period: '10-2026',
    checked_on: TODAY,
  });
  if (opts.type === 'GST_CN' && opts.portal === 'GST_REFLECTED') {
    await api(USERS.accounts, 'PATCH', `/credit-notes/${id}/type`, { cn_type_code: 'GST_CN' });
  }
  const detail = await api<CreditNote>(USERS.accounts, 'GET', `/credit-notes/${id}`);
  for (const line of detail.lines) {
    await api(USERS.accounts, 'POST', `/credit-note-lines/${line.id}/rate-verifications`, {
      reference_code: 'RATE_SALES',
      ref_doc_no: uniq('SI'),
      ref_doc_date: '2026-09-15',
      rate: 120.5,
    });
  }
  const isJv = detail.cn_type_code === 'JV_ONLY';
  return api<CreditNote>(
    USERS.accounts,
    'POST',
    `/credit-notes/${id}/issue`,
    isJv ? { jv_no: uniq('JV'), jv_date: TODAY } : { cn_no: uniq('CN'), cn_date: TODAY },
    true,
  );
}

export async function notifyParty(gsId: string, creditNoteId: string): Promise<void> {
  await api(
    USERS.accounts,
    'POST',
    `/gs/${gsId}/party-notifications`,
    { credit_note_id: creditNoteId, channel: 'EMAIL', recipient: 'accounts@demo-party.example' },
    true,
  );
}

// --- Step 8 closure (G-15) -----------------------------------------------------------------------
export async function closure(gsId: string): Promise<Closure> {
  return api<Closure>(USERS.rm, 'GET', `/gs/${gsId}/closure`);
}

export function failing(c: Closure): string[] {
  return c.items.filter((i) => i.applicable && !i.passed).map((i) => i.code);
}

export async function close(gsId: string): Promise<{ status: string; closure_type?: string }> {
  return api(USERS.rm, 'POST', `/gs/${gsId}/close`, { remarks: 'P3-08 lifecycle' }, true);
}

// --- Integrity (scripts/integrity_check.sql) -----------------------------------------------------
export interface IntegrityRow {
  code: string;
  violations: number;
  samples: string;
}

/** Run scripts/integrity_check.sql against the local Supabase DB (docker container). */
export function integrity(): IntegrityRow[] {
  const sql = readFileSync(resolve(process.cwd(), '..', 'scripts', 'integrity_check.sql'), 'utf-8');
  const container = process.env.RMS_DB_CONTAINER ?? 'supabase_db_rms';
  const out = execFileSync(
    'docker',
    ['exec', '-i', container, 'psql', '-U', 'postgres', '-At', '-F', '\t', '-v', 'ON_ERROR_STOP=1'],
    { input: sql, encoding: 'utf-8' },
  );
  return out
    .split(/\r?\n/)
    .filter((l) => /^IC-\d+\t/.test(l))
    .map((l) => {
      const [code = '', , violations = '0', samples = ''] = l.split('\t');
      return { code, violations: Number(violations), samples };
    });
}

export function integrityViolations(): IntegrityRow[] {
  return integrity().filter((r) => r.violations > 0);
}
