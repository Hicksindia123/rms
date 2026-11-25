import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { creditNotesApi } from '@/features/credit-notes/api';
import { AccountsCreditNoteQueuePage } from '@/features/credit-notes/AccountsCreditNoteQueuePage';
import { CreditNoteWorkspacePage } from '@/features/credit-notes/CreditNoteWorkspacePage';
import { CreditNotePrintPage } from '@/features/credit-notes/CreditNotePrintPage';
import { RmCnDecisionPage } from '@/features/credit-notes/RmCnDecisionPage';
import type {
  CreditNoteDetail,
  CreditNotePrint,
  CreditNoteWorkQueue,
  RmCnDecisionPrefill,
} from '@/features/credit-notes/types';

vi.mock('@/features/credit-notes/api');

const mockWorkQueue: CreditNoteWorkQueue = {
  pending_gs: [
    {
      gs_id: 'gs-101',
      gs_no: 'GS-2026-0101',
      party_id: 'party-1',
      party_name: 'Sharma Electronics',
      allowed_cn_qty: 10,
      draft_cn_qty: 0,
      issued_cn_qty: 0,
      pending_to_credit_qty: 10,
      rm_decision_date: '2026-11-05T10:00:00Z',
      active_credit_notes_count: 0,
    },
  ],
  active_notes: [
    {
      id: 'cn-1',
      gs_id: 'gs-101',
      gs_no: 'GS-2026-0101',
      party_id: 'party-1',
      party_name: 'Sharma Electronics',
      cn_type_code: 'GST_CN',
      cn_type_label: 'GST Credit Note',
      status: 'DRAFT',
      party_doc_code: 'PARTY_INVOICE',
      party_doc_label: 'Tax Invoice',
      gst_portal_code: 'GST_REFLECTED',
      gst_portal_label: 'Reflected on GST Portal',
      cn_no: null,
      cn_date: null,
      jv_no: null,
      jv_date: null,
      total_qty: 10,
      taxable_value: 12000,
      total_value: 14160,
      created_at: '2026-11-05T11:00:00Z',
      issued_at: null,
    },
  ],
};

const mockCnDetail: CreditNoteDetail = {
  id: 'cn-1',
  gs_id: 'gs-101',
  gs_no: 'GS-2026-0101',
  party_id: 'party-1',
  party_name: 'Sharma Electronics',
  party_gstin: '07AAAAA0000A1Z5',
  party_state: 'Delhi',
  cn_type_code: 'GST_CN',
  cn_type_label: 'GST Credit Note',
  status: 'DRAFT',
  party_doc_code: 'PARTY_INVOICE',
  party_doc_label: 'Tax Invoice',
  party_doc_no: 'INV-999',
  party_doc_date: '2026-10-15',
  party_doc_amount: 14160,
  party_doc_notes: 'Original invoice copy matched',
  gst_portal_code: 'GST_REFLECTED',
  gst_portal_label: 'Reflected on GST Portal',
  gst_return_type: 'GSTR-1',
  gst_return_period: '102026',
  gst_checked_on: '2026-11-05',
  gst_evidence_attachment_id: null,
  cn_no: null,
  cn_date: null,
  jv_no: null,
  jv_date: null,
  taxable_value: 12000,
  cgst_rate: 9,
  cgst_amount: 1080,
  sgst_rate: 9,
  sgst_amount: 1080,
  igst_rate: 0,
  igst_amount: 0,
  total_value: 14160,
  is_inter_state: false,
  created_by: 'user-deepak',
  created_by_name: 'Deepak Ji (Accounts)',
  created_at: '2026-11-05T11:00:00Z',
  issued_by: null,
  issued_by_name: null,
  issued_at: null,
  cancelled_by_name: null,
  cancelled_at: null,
  cancel_reason: null,
  lines: [
    {
      id: 'cnl-1',
      credit_note_id: 'cn-1',
      gs_item_id: 'gsi-1',
      line_no: 1,
      product_code: 'FAN-01',
      product_name: 'Ceiling Fan Deluxe',
      lot_id: 'lot-1',
      condition_class: 'FUNCTIONAL_GOOD',
      qty: 10,
      rate: 1200,
      tax_rate: 18,
      taxable_amount: 12000,
      cgst_amount: 1080,
      sgst_amount: 1080,
      igst_amount: 0,
      total_amount: 14160,
      rate_verifications: [
        {
          id: 'rv-1',
          credit_note_line_id: 'cnl-1',
          reference_code: 'RATE_SALES',
          reference_label: 'Historical Sales Invoice',
          ref_doc_no: 'INV-2026-0042',
          ref_doc_date: '2026-09-01',
          rate: 1200,
          notes: null,
          verified_by: 'user-deepak',
          verified_by_name: 'Deepak Ji',
          verified_at: '2026-11-05T11:15:00Z',
        },
      ],
      is_rate_verified: true,
    },
  ],
  linked_step2_documents: [
    {
      id: 'gd-1',
      document_type_code: 'TAX_INVOICE',
      document_type_label: 'Tax Invoice',
      doc_no: 'INV-999',
      doc_date: '2026-10-15',
      amount: 14160,
      attachment_id: 'att-1',
      file_name: 'invoice_photo.jpg',
      storage_path: 'gs_docs/invoice_photo.jpg',
    },
  ],
};

const mockPrefill: RmCnDecisionPrefill = {
  gs_id: 'gs-101',
  gs_no: 'GS-2026-0101',
  party_name: 'Sharma Electronics',
  is_csr: false,
  has_existing_decision: false,
  current_decision: null,
  prefill_lines: [
    {
      gs_item_id: 'gsi-1',
      line_no: 1,
      product_code: 'FAN-01',
      product_name: 'Ceiling Fan Deluxe',
      received_qty: 10,
      planned_action_code: 'ISSUE_CN',
      planned_action_label: 'Issue Credit Note',
      planned_qty: 10,
      default_decision_code: 'ALLOW_CN',
      allowed_qty: 10,
    },
  ],
};

const mockPrint: CreditNotePrint = {
  credit_note_id: 'cn-1',
  gs_id: 'gs-101',
  gs_no: 'GS-2026-0101',
  party_name: 'Sharma Electronics',
  party_gstin: '07AAAAA0000A1Z5',
  party_station: 'New Delhi',
  party_state: 'Delhi',
  cn_type_code: 'GST_CN',
  cn_type_label: 'GST Credit Note',
  voucher_no: 'CN-TALLY-2026-088',
  voucher_date: '2026-11-05',
  voucher_type_name: 'GST CREDIT NOTE',
  party_doc_type: 'Tax Invoice',
  party_doc_no: 'INV-999',
  party_doc_date: '2026-10-15',
  gst_portal_status: 'Reflected on GST Portal',
  gst_return_period: '102026',
  taxable_value: 12000,
  cgst_amount: 1080,
  sgst_amount: 1080,
  igst_amount: 0,
  total_value: 14160,
  is_inter_state: false,
  lines: [
    {
      line_no: 1,
      product_code: 'FAN-01',
      product_name: 'Ceiling Fan Deluxe',
      qty: 10,
      rate: 1200,
      tax_rate: 18,
      taxable_amount: 12000,
      cgst_amount: 1080,
      sgst_amount: 1080,
      igst_amount: 0,
      total_amount: 14160,
      condition_class: 'FUNCTIONAL_GOOD',
      rate_verified_doc: 'INV-2026-0042',
    },
  ],
  signature_blocks: [
    { label: 'Prepared & Verified By', name: 'Deepak Ji', role: 'Accounts Department' },
    { label: 'For Company Name', name: 'Authorised Signatory', role: 'Finance Authority' },
  ],
};

describe('P3-06 Step-7 Credit Notes Frontend Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders Accounts Credit Note Queue with Pending and Register views', async () => {
    vi.mocked(creditNotesApi.getWorkQueue).mockResolvedValue(mockWorkQueue);

    const onOpenCn = vi.fn();
    render(<AccountsCreditNoteQueuePage onOpenCn={onOpenCn} />);

    await waitFor(() => {
      expect(screen.getByText('Credit Notes & Accounts Work Queue')).toBeDefined();
    });

    // Check pending tab content
    expect(screen.getByText('GS-2026-0101')).toBeDefined();
    expect(screen.getByText('Sharma Electronics')).toBeDefined();

    // Switch to Register tab
    const registerTab = screen.getByRole('button', { name: /credit notes register/i });
    fireEvent.click(registerTab);

    // Should list the draft CN
    expect(screen.getByText('GST CN')).toBeDefined();
    expect(screen.getByText('₹14,160.00')).toBeDefined();
  });

  it('renders Credit Note Workspace split view and actions', async () => {
    vi.mocked(creditNotesApi.get).mockResolvedValue(mockCnDetail);

    const onBack = vi.fn();
    const onOpenPrint = vi.fn();

    render(<CreditNoteWorkspacePage cnId="cn-1" onBack={onBack} onOpenPrint={onOpenPrint} />);

    await waitFor(() => {
      expect(screen.getByText(/Credit Note Workspace:/)).toBeDefined();
    });

    // Left pane GS context & documents
    expect(screen.getAllByText('Sharma Electronics').length).toBeGreaterThan(0);
    expect(screen.getByText('07AAAAA0000A1Z5')).toBeDefined();
    expect(screen.getByText('Tax Invoice (INV-999)')).toBeDefined();
    expect(screen.getByText('View Scan')).toBeDefined();

    // Right pane steps
    expect(screen.getByText('Party Document Verification')).toBeDefined();
    expect(screen.getByText('GST Portal Verification')).toBeDefined();
    expect(screen.getByText('Credit Note Type & Compliance')).toBeDefined();
    expect(screen.getByText('Commercial Rate Verification & Valuation')).toBeDefined();
    expect(screen.getByText('Credit Note Voucher Issue')).toBeDefined();
  });

  it('renders RM CN Decision page and enforces deviation reason when diverging', async () => {
    vi.mocked(creditNotesApi.getCnDecisionPrefill).mockResolvedValue(mockPrefill);
    vi.mocked(creditNotesApi.recordCnDecision).mockResolvedValue({
      id: 'dec-1',
      gs_id: 'gs-101',
      gs_no: 'GS-2026-0101',
      party_name: 'Sharma Electronics',
      decision_by: 'rm-user',
      decision_by_name: 'Replacement Manager',
      decision_at: '2026-11-05T12:00:00Z',
      deviation_reason: 'Testing divergence justification',
      is_current: true,
      lines: [],
    });

    const onBack = vi.fn();
    const { container } = render(<RmCnDecisionPage gsId="gs-101" onBack={onBack} />);

    await waitFor(() => {
      expect(screen.getByText('Step-7: RM Credit Note Decision')).toBeDefined();
    });

    expect(screen.getByText('Ceiling Fan Deluxe')).toBeDefined();
    expect(screen.getByText('Planned Action:')).toBeDefined();

    // Toggle to Send Replacement (deviates from planned ISSUE_CN)
    const sendRepBtn = screen.getByRole('button', { name: /send replacement/i });
    fireEvent.click(sendRepBtn);

    // Expect deviation warning banner to appear
    await waitFor(() => {
      expect(screen.getByText(/Deviation Reason Required/)).toBeDefined();
    });

    // Submitting form without deviation reason triggers validation error
    const form = container.querySelector('form');
    if (!form) throw new Error('CN decision form not rendered');
    fireEvent.submit(form);

    await waitFor(() => {
      expect(
        screen.getByText(
          /A deviation reason is mandatory when diverging from the planned RM action/,
        ),
      ).toBeDefined();
    });
  });

  it('renders CreditNotePrintPage with CN_SUMMARY format and dual signatures', async () => {
    vi.mocked(creditNotesApi.getPrint).mockResolvedValue(mockPrint);

    const onBack = vi.fn();
    render(<CreditNotePrintPage cnId="cn-1" onBack={onBack} />);

    await waitFor(() => {
      expect(screen.getByText('GST CREDIT NOTE')).toBeDefined();
    });

    expect(screen.getByText('CN-TALLY-2026-088')).toBeDefined();
    expect(screen.getByText('Sharma Electronics')).toBeDefined();
    expect(screen.getByText('Ceiling Fan Deluxe')).toBeDefined();
    expect(screen.getAllByText(/12000\.00/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/14160\.00/).length).toBeGreaterThan(0);

    // Dual signatures
    expect(screen.getByText('Deepak Ji')).toBeDefined();
    expect(screen.getByText('Accounts Department')).toBeDefined();
    expect(screen.getByText('Authorised Signatory')).toBeDefined();
  });
});
