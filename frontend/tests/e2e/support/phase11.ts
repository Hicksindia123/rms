/**
 * Phase 11 · E2E test support helpers for the full 2026-11 workflow.
 *
 * Covers:
 * - AMD-01, AMD-02: Offline gate entry with backdate and numeric entry number
 * - AMD-03, G-02: Multi-carton count and video per carton
 * - AMD-04, AMD-05: Multi-document rows (incl. Courier Slip) and immediate Accounts alerts
 * - AMD-08, AMD-09, G-19: Counting & Categorisation with item bucket conservation
 * - AMD-10, AMD-11: Item field profiles and packaging/container counts
 * - AMD-12, AMD-13: RM review, auto Transfer Slip, intermediate store hold
 * - AMD-14, AMD-15, G-20: Department routing, outcome receiving & G-20 conservation
 * - AMD-16, AMD-17, G-21: RM final actions split & Replacement Slip PDF
 * - AMD-18, AMD-19, G-22: Accounts entry, Dispatch Slip PDF & dispatch
 */
import { api, uploadConfirmed, USERS, type Gs } from './stack';

export const TODAY = new Date().toISOString().slice(0, 10);

export interface FieldProfileSetup {
  dmtCatId: string;
  repairDeptId: string;
  hgDeptId: string;
}

/** Ensure DMT category has DEPARTMENT and ITEM_COUNT profile assignments. */
export async function ensureFieldProfiles(): Promise<FieldProfileSetup> {
  const categories = await api<Array<{ id: string; code: string }>>(
    USERS.admin,
    'GET',
    '/masters/product-categories',
  );
  const dmt = categories.find((c) => c.code === 'DMT');
  if (!dmt) throw new Error('Category DMT not found');

  const fields = await api<Array<{ id: string; field_group: string; code: string }>>(
    USERS.admin,
    'GET',
    '/config/item-field-profiles/fields',
  );

  const repair = fields.find((f) => f.field_group === 'DEPARTMENT' && f.code === 'REPAIR');
  const hg = fields.find((f) => f.field_group === 'DEPARTMENT' && f.code === 'MERCURY_EXTRACTION');
  const pkg = fields.find((f) => f.field_group === 'ITEM_COUNT' && f.code === 'PACKAGING');
  const cont = fields.find((f) => f.field_group === 'ITEM_COUNT' && f.code === 'CONTAINER');
  const manual = fields.find((f) => f.field_group === 'ITEM_COUNT' && f.code === 'USER_MANUAL');

  if (!repair || !hg || !pkg || !cont || !manual) {
    throw new Error('Required library fields not found in item_field_library');
  }

  try {
    const deptScope = await api<{
      groups: Array<{ field_group: string; effective: Array<{ field_id: string }> }>;
    }>(USERS.admin, 'GET', `/config/item-field-profiles/scope?category_id=${dmt.id}`);

    const deptGroup = deptScope.groups.find((g) => g.field_group === 'DEPARTMENT');
    if (!deptGroup || deptGroup.effective.length === 0) {
      await api(
        USERS.admin,
        'PUT',
        '/config/item-field-profiles/scope/DEPARTMENT',
        {
          category_id: dmt.id,
          fields: [
            { field_id: repair.id, is_included: true, sort_order: 10 },
            { field_id: hg.id, is_included: true, sort_order: 20 },
          ],
          reason: 'Phase 11 setup: assign departments to DMT',
        },
      );
    }
  } catch {
    // Already set or concurrent worker set it
  }

  try {
    const countScope = await api<{
      groups: Array<{ field_group: string; effective: Array<{ field_id: string }> }>;
    }>(USERS.admin, 'GET', `/config/item-field-profiles/scope?category_id=${dmt.id}`);

    const countGroup = countScope.groups.find((g) => g.field_group === 'ITEM_COUNT');
    if (!countGroup || countGroup.effective.length === 0) {
      await api(
        USERS.admin,
        'PUT',
        '/config/item-field-profiles/scope/ITEM_COUNT',
        {
          category_id: dmt.id,
          fields: [
            { field_id: pkg.id, is_included: true, sort_order: 10 },
            { field_id: cont.id, is_included: true, sort_order: 20 },
            { field_id: manual.id, is_included: true, sort_order: 30 },
          ],
          reason: 'Phase 11 setup: assign item counts to DMT',
        },
      );
    }
  } catch {
    // Already set or concurrent worker set it
  }

  return { dmtCatId: dmt.id, repairDeptId: repair.id, hgDeptId: hg.id };
}

export async function getParty(): Promise<{
  id: string;
  name: string;
  code: string;
  state_id?: string;
  station_id?: string;
}> {
  const parties = await api<Array<{ id: string; name: string; code: string }>>(
    USERS.gate,
    'GET',
    '/gs/lookups/parties?limit=5',
  );
  const first = parties[0];
  if (!first) throw new Error('No parties found in database');
  return first;
}

export async function getDmtProduct(): Promise<{ id: string; code: string; name: string }> {
  const products = await api<Array<{ id: string; code: string; name: string }>>(
    USERS.aman,
    'GET',
    '/itemization/lookups/products?q=DMT&limit=5',
  );
  const first = products[0];
  if (!first) throw new Error('No DMT products found in database');
  return first;
}

/** Create an Offline return GS with backdated date, numeric entry number, and document rows. */
export async function createOfflineGs(params: {
  tag: string;
  cartonCount?: number;
  gateEntryDate?: string;
  gateEntryNo?: number;
  /** Gate form v4 rows (DEC-62): type + source only. */
  documents?: Array<{ doc_type_code: string; source: 'PARTY' | 'TRANSPORT' }>;
}): Promise<Gs> {
  const party = await getParty();
  const backdate = new Date(Date.now() - 3 * 86400000).toISOString().slice(0, 10);
  const gateEntryDate = params.gateEntryDate ?? backdate;
  const gateEntryNo = params.gateEntryNo ?? (800000 + Math.floor(Math.random() * 100000));
  const cartonCount = params.cartonCount ?? 2;
  const tag = params.tag;

  const docs = params.documents ?? [
    { doc_type_code: 'COURIER_SLIP', source: 'TRANSPORT' as const },
    { doc_type_code: 'INVOICE', source: 'PARTY' as const },
  ];

  const payload = {
    party_id: party.id,
    values: {
      return_type: 'OFFLINE_RETURN',
      gate_entry_date: gateEntryDate,
      gate_entry_no: gateEntryNo,
      carton_count: cartonCount,
      delivery_mode: 'COURIER_PARCEL',
      courier_name: 'SafeX Logistics',
      docket_no: `DKT-${tag}`,
      gs_creation_format: 'AUTO_STANDARD',
    },
    documents: docs,
  };

  const res = await api<{ goods_slip: Gs }>(USERS.gate, 'POST', '/gs', payload, true);
  return res.goods_slip;
}

/** Create an E-Commerce return GS (no gate entry date/number). */
export async function createEcommerceGs(params: {
  tag: string;
  cartonCount?: number;
}): Promise<Gs> {
  const party = await getParty();
  const tag = params.tag;
  const cartonCount = params.cartonCount ?? 1;

  const payload = {
    party_id: party.id,
    values: {
      return_type: 'ECOMMERCE_RETURN',
      carton_count: cartonCount,
      delivery_mode: 'COURIER_PARCEL',
      courier_name: 'DTDC',
      docket_no: `ECOM-${tag}`,
      gs_creation_format: 'AUTO_STANDARD',
    },
    // DEC-62: Delivery Note is no longer a party document type on gate v4.
    documents: [{ doc_type_code: 'HANDWRITTEN_SLIP', source: 'PARTY' }],
  };

  const res = await api<{ goods_slip: Gs }>(USERS.gate, 'POST', '/gs', payload, true);
  return res.goods_slip;
}

/** Upload unboxing videos for cartons (box_no 1..count). */
export async function uploadCartonVideos(
  gsId: string,
  count: number,
  startFromBox = 1,
): Promise<void> {
  for (let i = 0; i < count; i++) {
    const boxNo = startFromBox + i;
    await uploadConfirmed(gsId, 'UNBOXING_VIDEO', boxNo);
  }
}

/** Upload and classify document photo (required by G-02 unless missing_documentation is set). */
export async function uploadClassifiedDocPhoto(gsId: string, docNo: string): Promise<void> {
  const photo = await uploadConfirmed(gsId, 'DOC_PHOTO');
  await api(USERS.aman, 'POST', `/gs/${gsId}/documents`, {
    attachment_id: photo,
    values: {
      doc_classification: 'INVOICE',
      invoice_no: docNo,
      invoice_date: TODAY,
      buyer_gstin: '09AAACH7409R1ZZ',
      seller_gstin: '07AAACB1234C1Z5',
      items_verified: true,
    },
  });
}

/** Add a document row at carton opening stage. */
export async function addCartonDocument(
  gsId: string,
  doc: { doc_type_code: string; doc_no: string; doc_date: string; remarks?: string },
): Promise<void> {
  await api(USERS.aman, 'POST', `/gs/${gsId}/carton-documents`, doc, true);
}

/** Complete carton opening. */
export async function completeCartonOpening(gsId: string): Promise<void> {
  await api(USERS.aman, 'POST', `/gs/${gsId}/unboxing/complete`, {});
}

/** Add an item, submit count (transitions ITEMIZATION -> CATEGORISATION, AMD-08). */
export async function addItemAndSubmitCount(
  gsId: string,
  productId: string,
  qty: number,
): Promise<string> {
  const res = await api<{ id: string }>(USERS.aman, 'POST', `/gs/${gsId}/items`, {
    product_id: productId,
    documented_qty: qty,
    received_qty: qty,
  });
  await api(USERS.aman, 'POST', `/gs/${gsId}/counting/submit`, {}, true);
  return res.id;
}

/** Save and submit item categorization with buckets and auxiliary counts. */
export async function submitItemCategorisation(
  gsId: string,
  itemId: string,
  buckets: Record<string, number>,
  counts: Record<string, number> = { PACKAGING: 10, CONTAINER: 10, USER_MANUAL: 10 },
): Promise<void> {
  await api(
    USERS.aman,
    'PUT',
    `/gs/${gsId}/items/${itemId}/categorisation`,
    {
      buckets: Object.entries(buckets).map(([field_code, qty]) => ({ field_code, qty })),
      counts: Object.entries(counts).map(([count_type, count_value]) => ({
        count_type,
        count_value,
      })),
    },
    true,
  );
  await api(
    USERS.aman,
    'POST',
    `/gs/${gsId}/categorisation/submit`,
    { category_code: 'REGULAR_RETURN' },
    true,
  );
}

/** Approve RM review, auto-generating Transfer Slip (AMD-13). */
export async function approveRmReview(gsId: string): Promise<string> {
  const res = await api<{ transfer_id: string }>(
    USERS.rm,
    'POST',
    `/gs/${gsId}/rm-approve`,
    { remarks: 'Approved by RM in Phase 11 E2E' },
    true,
  );
  return res.transfer_id;
}

/** Intermediate Store accepts the transfer slip. */
export async function acceptStoreTransfer(transferId: string): Promise<void> {
  const detail = await api<{
    lines: Array<{ lot_id: string; qty_sent: number }>;
  }>(USERS.sahil, 'GET', `/custody/transfers/${transferId}`);

  await api(
    USERS.sahil,
    'POST',
    `/custody/transfers/${transferId}/accept`,
    {
      acceptance_code: 'ACCEPTED_VERIFIED',
      lines: detail.lines.map((ln) => ({ lot_id: ln.lot_id, qty_counted: ln.qty_sent })),
      notes: 'Accepted by intermediate store',
    },
    true,
  );
}

/** RM dispatches routing line to a department. */
export async function dispatchRouting(
  gsId: string,
  itemId: string,
  deptFieldId: string,
  qty: number,
): Promise<{ id: string; lines: Array<{ id: string }> }> {
  return api(
    USERS.rm,
    'POST',
    '/department-routing/dispatch',
    {
      gs_id: gsId,
      department_field_id: deptFieldId,
      lines: [{ gs_item_id: itemId, qty_sent: qty }],
      remarks: 'Phase 11 E2E routing to department',
    },
    true,
  );
}

/** Department receiver books return into outcome heads. */
export async function receiveRouting(
  routingId: string,
  routingLineId: string,
  receipts: Array<{ outcome_head_code: string; qty_received: number }>,
): Promise<void> {
  const outcomeHeads = await api<Array<{ id: string; code: string; label: string }>>(
    USERS.aman,
    'GET',
    '/department-routing/outcome-heads',
  );

  await api(
    USERS.aman,
    'POST',
    `/department-routing/${routingId}/receive`,
    {
      routing_id: routingId,
      lines: receipts.map((r) => {
        const head = outcomeHeads.find((h) => h.code === r.outcome_head_code);
        if (!head) throw new Error(`Outcome head ${r.outcome_head_code} not found`);
        return {
          routing_line_id: routingLineId,
          outcome_head_id: head.id,
          quantity: r.qty_received,
          remarks: 'Phase 11 receipt',
        };
      }),
    },
    true,
  );
}

/** RM splits available qty across actions and finalises. */
export async function finaliseFinalActions(
  gsId: string,
  itemId: string,
  actions: Record<string, number>,
): Promise<string> {
  await api(
    USERS.rm,
    'PUT',
    `/gs/${gsId}/final-actions`,
    {
      lines: [
        {
          gs_item_id: itemId,
          actions: Object.entries(actions).map(([action_code, qty]) => ({ action_code, qty })),
        },
      ],
    },
    true,
  );
  const fin = await api<{ current_slip: { id: string } }>(
    USERS.rm,
    'POST',
    `/gs/${gsId}/final-actions/finalise`,
    {},
    true,
  );
  return fin.current_slip.id;
}

/** Accounts enters details per line and completes entry. */
export async function saveAndCompleteAccountsEntry(
  gsId: string,
  acSlipId: string,
  lines: Array<{
    action_line_id?: string;
    line_id?: string;
    cn_no?: string;
    cn_date?: string;
    cn_value?: number;
    challan_no?: string;
    challan_date?: string;
  }>,
): Promise<string> {
  const payloadLines = lines.map((l) => ({
    line_id: l.line_id ?? l.action_line_id ?? '',
    cn_no: l.cn_no,
    cn_date: l.cn_date,
    cn_value: l.cn_value,
    challan_no: l.challan_no,
    challan_date: l.challan_date,
  }));

  await api(
    USERS.accounts,
    'PUT',
    `/ac-entry/gs/${gsId}/lines`,
    {
      ac_action_slip_id: acSlipId,
      lines: payloadLines,
    },
    true,
  );
  const completed = await api<{ dispatch_slip: { id: string } | null }>(
    USERS.accounts,
    'POST',
    `/ac-entry/gs/${gsId}/complete`,
    {
      ac_action_slip_id: acSlipId,
      remarks: 'Accounts entry completed in Phase 11 E2E',
    },
    true,
  );
  return completed.dispatch_slip?.id ?? '';
}

/** Dispatch issues goods against the Dispatch Slip. */
export async function dispatchSlip(slipId: string): Promise<void> {
  await api(
    USERS.dispatch,
    'POST',
    `/dispatch-slips/${slipId}/dispatch`,
    {
      dispatch_date: TODAY,
      transporter: 'SafeX Logistics',
      docket_no: `DKT-DISP-${String(Date.now())}`,
    },
    true,
  );
}
