import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RmApproveResult, RmReviewData, RmReviewItem } from '@/features/rm-review/types';

const mockData: RmReviewData = {
  goods_slip: {
    id: 'gs-222',
    gs_no: 'GS/2026/042',
    status: 'RM_REVIEW',
    party_id: 'party-1',
    party_name: 'Alpha Traders',
    station_name: 'Delhi Hub',
    doc_type: 'TAX_INVOICE',
    doc_no: 'INV-999',
    doc_date: '2026-11-10',
    transporter_name: 'V-Trans',
    docket_no: 'DKT-123',
    carton_count: 2,
    counted_by: 'user-aman',
    counted_by_name: 'Aman (Inward Verifier)',
    category_code: 'REGULAR_RETURN',
    created_at: '2026-11-13T10:00:00Z',
  },
  documents: [
    {
      id: 'doc-1',
      document_type: 'TAX_INVOICE',
      document_number: 'INV-999',
      document_date: '2026-11-10',
      file_url: 'https://storage.example.com/inv-999.pdf',
      file_name: 'inv-999.pdf',
    },
  ],
  carton_videos: [
    {
      id: 'vid-1',
      carton_no: 1,
      file_url: 'https://storage.example.com/box-1.mp4',
      file_name: 'box-1.mp4',
      created_at: '2026-11-13T10:15:00Z',
    },
  ],
  items: [
    {
      item_id: 'item-10',
      product_id: 'prod-10',
      sku_code: 'SKU-IRON-01',
      sku_name: 'Electric Iron 1000W',
      documented_qty: 8,
      received_qty: 8,
      short_qty: 0,
      excess_qty: 0,
      allowed_buckets: [
        { field_id: 'f-1', field_code: 'OK_PACKED', label: 'OK and Packed', rank: 10 },
        { field_id: 'f-2', field_code: 'DAMAGED', label: 'Damaged', rank: 20 },
      ],
      buckets: [
        { field_code: 'OK_PACKED', label_snapshot: 'OK and Packed', qty: 8 },
        { field_code: 'DAMAGED', label_snapshot: 'Damaged', qty: 0 },
      ],
      total_bucket_qty: 8,
      is_conserved: true,
      counts: [
        { field_code: 'PACKAGING_COUNT', label_snapshot: 'Packaging Box Count', count_value: 8 },
      ],
    },
  ],
  revisions: [
    {
      id: 'rev-1',
      revision_no: 1,
      action: 'SUBMITTED',
      items_snapshot: [],
      remarks: 'Initial submission by Aman',
      created_by: 'user-aman',
      created_by_name: 'Aman',
      created_at: '2026-11-13T10:30:00Z',
    },
  ],
  transfer_slip: null,
  all_conserved: true,
  can_review: true,
};

const getReviewDataFn = vi.fn<() => Promise<RmReviewData>>();
const editItemFn = vi.fn<(...args: unknown[]) => Promise<RmReviewItem>>();
const sendBackFn = vi.fn<(...args: unknown[]) => Promise<{ gs_id: string; status: string; remarks: string }>>();
const approveFn = vi.fn<(...args: unknown[]) => Promise<RmApproveResult>>();

vi.mock('@/features/rm-review/api', () => ({
  rmReviewApi: {
    getReviewData: () => getReviewDataFn(),
    editItem: (...args: unknown[]) => editItemFn(...args),
    sendBack: (...args: unknown[]) => sendBackFn(...args),
    approve: (...args: unknown[]) => approveFn(...args),
  },
}));

vi.mock('@/features/goods-slips/statusLabels', () => ({
  useStatusLabels: () => (code: string) => (code === 'RM_REVIEW' ? 'RM Review' : code),
}));

const { RmReviewPage } = await import('@/features/rm-review/RmReviewPage');

describe('RmReviewPage (AMD-12, AMD-13, G-19)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getReviewDataFn.mockResolvedValue(mockData);
  });

  it('renders one-screen GS at a glance with header, docs, carton videos and items', async () => {
    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/RM Review: GS\/2026\/042/i)).toBeInTheDocument();
    expect(screen.getByText(/Alpha Traders/i)).toBeInTheDocument();
    expect(screen.getByText(/Aman \(Inward Verifier\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Uploaded Documents \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Carton Opening Videos \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Electric Iron 1000W/i)).toBeInTheDocument();
    expect(screen.getByText(/Conserved \(8\/8\)/i)).toBeInTheDocument();
  });

  it('allows RM to open Edit modal and adjusts quantity with G-19 conservation', async () => {
    editItemFn.mockResolvedValue({
      ...mockData.items[0]!,
      received_qty: 6,
      total_bucket_qty: 6,
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Electric Iron 1000W/i)).toBeInTheDocument();

    const editBtn = screen.getByRole('button', { name: /Edit Qty\/Buckets/i });
    fireEvent.click(editBtn);

    expect(screen.getByText(/Edit Item: Electric Iron 1000W/i)).toBeInTheDocument();

    const recvInput = screen.getByLabelText(/Received \(Counted\) Qty/i);
    fireEvent.change(recvInput, { target: { value: '6' } });

    // In modal, adjusting recv to 6 causes mismatch until bucket is changed
    const bucketInput = screen.getAllByRole('spinbutton')[2]!; // first bucket input
    fireEvent.change(bucketInput, { target: { value: '6' } });

    const remarksInput = screen.getByLabelText(/Reason for Adjustment/i);
    fireEvent.change(remarksInput, { target: { value: 'RM adjusted count from 8 to 6' } });

    const saveBtn = screen.getByRole('button', { name: /Save Adjustment \(G-19\)/i });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(editItemFn).toHaveBeenCalledWith(
        'gs-222',
        'item-10',
        expect.objectContaining({
          received_qty: 6,
          remarks: 'RM adjusted count from 8 to 6',
        }),
        expect.any(String),
      );
    });
  });

  it('allows RM to send back to categorisation with remarks', async () => {
    sendBackFn.mockResolvedValue({
      gs_id: 'gs-222',
      status: 'CATEGORISATION',
      remarks: 'Please recount box 2',
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/RM Review: GS\/2026\/042/i)).toBeInTheDocument();

    const sendBackBtn = screen.getByRole('button', { name: /Send Back/i });
    fireEvent.click(sendBackBtn);

    expect(screen.getByText(/Send Back to Categorisation/i)).toBeInTheDocument();

    const remarksInput = screen.getByLabelText(/Remarks for Inward Verifier/i);
    fireEvent.change(remarksInput, { target: { value: 'Please recount box 2' } });

    const confirmBtn = screen.getByRole('button', { name: /Confirm Send Back/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(sendBackFn).toHaveBeenCalledWith(
        'gs-222',
        { remarks: 'Please recount box 2' },
        expect.any(String),
      );
    });
  });

  it('approves goods slip and displays auto-generated Transfer Slip with print action', async () => {
    approveFn.mockResolvedValue({
      goods_slip_id: 'gs-222',
      status: 'HELD_AT_INTERMEDIATE_STORE',
      transfer_id: 'trf-777',
      transfer_no: 'TRF/2026/0001',
      message: 'Approved and transfer slip generated',
    });

    const onOpenTransfer = vi.fn();

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} onOpenTransfer={onOpenTransfer} />);

    expect(await screen.findByText(/RM Review: GS\/2026\/042/i)).toBeInTheDocument();

    const approveBtn = screen.getByRole('button', { name: /Approve & Handover/i });
    fireEvent.click(approveBtn);

    expect(screen.getByText(/Approve & Generate Custody Transfer Slip/i)).toBeInTheDocument();

    const confirmApproveBtn = screen.getByRole('button', { name: /Approve & Generate Transfer/i });
    fireEvent.click(confirmApproveBtn);

    await waitFor(() => {
      expect(approveFn).toHaveBeenCalledWith(
        'gs-222',
        expect.objectContaining({ remarks: null }),
        expect.any(String),
      );
    });

    // Verification banner should be rendered
    expect(await screen.findByText(/Transfer Slip Auto-Generated: TRF\/2026\/0001/i)).toBeInTheDocument();
    const printBtn = screen.getByRole('button', { name: /Print Transfer Note/i });
    fireEvent.click(printBtn);
    expect(onOpenTransfer).toHaveBeenCalledWith('trf-777');
  });

  it('shows revision audit history when toggled', async () => {
    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Revision Audit Trail/i)).toBeInTheDocument();

    const expandBtn = screen.getByRole('button', { name: /Revision Audit Trail/i });
    fireEvent.click(expandBtn);

    expect(screen.getByText(/Revision #1/i)).toBeInTheDocument();
    expect(screen.getByText(/"Initial submission by Aman"/i)).toBeInTheDocument();
  });
});
