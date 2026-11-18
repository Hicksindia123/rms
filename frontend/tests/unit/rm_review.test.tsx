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
      // Shapes as returned by GET /gs/{id}/rm-review (backend rm_review/schemas.py).
      allowed_buckets: [
        { field_id: 'f-1', field_code: 'OK_PACKED', field_label: 'OK and Packed', sort_order: 10 },
        { field_id: 'f-2', field_code: 'DAMAGED', field_label: 'Damaged', sort_order: 20 },
      ],
      allowed_counts: [
        { field_id: 'fc-1', field_code: 'PACKAGING', field_label: 'Packaging', sort_order: 10 },
      ],
      buckets: [
        { id: 'b-1', item_id: 'item-10', field_code: 'OK_PACKED', field_label: 'OK and Packed', qty: 8 },
        { id: 'b-2', item_id: 'item-10', field_code: 'DAMAGED', field_label: 'Damaged', qty: 0 },
      ],
      total_bucket_qty: 8,
      is_conserved: true,
      counts: [
        { id: 'c-1', item_id: 'item-10', count_type: 'PACKAGING', field_label: 'Packaging', count_value: 8 },
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
const addLineFn = vi.fn<(...args: unknown[]) => Promise<RmReviewItem>>();
const removeLineFn = vi.fn<(...args: unknown[]) => Promise<{ goods_slip_id: string; item_id: string; status: string }>>();
const changeProductFn = vi.fn<(...args: unknown[]) => Promise<RmReviewItem>>();
const sendBackFn = vi.fn<(...args: unknown[]) => Promise<{ gs_id: string; status: string; remarks: string }>>();
const approveFn = vi.fn<(...args: unknown[]) => Promise<RmApproveResult>>();

vi.mock('@/features/rm-review/api', () => ({
  rmReviewApi: {
    getReviewData: () => getReviewDataFn(),
    editItem: (...args: unknown[]) => editItemFn(...args),
    addLine: (...args: unknown[]) => addLineFn(...args),
    removeLine: (...args: unknown[]) => removeLineFn(...args),
    changeProduct: (...args: unknown[]) => changeProductFn(...args),
    sendBack: (...args: unknown[]) => sendBackFn(...args),
    approve: (...args: unknown[]) => approveFn(...args),
  },
}));

vi.mock('@/features/itemization/api', () => ({
  itemizationApi: {
    categories: () =>
      Promise.resolve([
        {
          id: 'cat-1',
          code: 'DMT',
          name: 'Domestic Appliances',
          subcategories: [{ id: 'sub-1', code: 'IRN', name: 'Electric Irons' }],
        },
      ]),
    products: () =>
      Promise.resolve([
        {
          id: 'prod-20',
          code: 'SKU-STEAM-01',
          name: 'Steam Iron 2000W',
          category_id: 'cat-1',
          category_name: 'Domestic Appliances',
          subcategory_id: 'sub-1',
          subcategory_name: 'Electric Irons',
        },
      ]),
    productFields: (productId: string) =>
      Promise.resolve({
        product_id: productId,
        allowed_buckets: [
          { field_id: 'f-1', field_code: 'OK_PACKED', field_label: 'OK and Packed', sort_order: 10 },
          { field_id: 'f-2', field_code: 'DAMAGED', field_label: 'Damaged', sort_order: 20 },
        ],
        allowed_counts: [
          { field_id: 'fc-1', field_code: 'PACKAGING', field_label: 'Packaging', sort_order: 10 },
        ],
      }),
  },
  newIdempotencyKey: () => 'web-test-key',
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
    // Labels come from the backend's field_label (config), not the code.
    expect(screen.getByText('OK and Packed:')).toBeInTheDocument();
    expect(screen.getByText(/Packaging:/)).toBeInTheDocument();
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
          // RmEditItemIn.counts is keyed by count_type (the backend rejects field_code).
          counts: [{ count_type: 'PACKAGING', count_value: 8 }],
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

  it('allows RM to open Add Line modal, choose product, enter split & reason, and submit (DEC-54)', async () => {
    addLineFn.mockResolvedValue({
      item_id: 'item-20',
      product_id: 'prod-20',
      sku_code: 'SKU-STEAM-01',
      sku_name: 'Steam Iron 2000W',
      documented_qty: 5,
      received_qty: 5,
      short_qty: 0,
      excess_qty: 0,
      allowed_buckets: [
        { field_id: 'f-1', field_code: 'OK_PACKED', field_label: 'OK and Packed', sort_order: 10 },
      ],
      allowed_counts: [],
      buckets: [
        { id: 'b-20', item_id: 'item-20', field_code: 'OK_PACKED', field_label: 'OK and Packed', qty: 5 },
      ],
      total_bucket_qty: 5,
      is_conserved: true,
      counts: [],
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/RM Review: GS\/2026\/042/i)).toBeInTheDocument();

    const addLineBtn = screen.getByRole('button', { name: /Add line/i });
    fireEvent.click(addLineBtn);

    expect(screen.getByText(/Add Line in RM Review \(DEC-54\)/i)).toBeInTheDocument();

    // Select product from combobox
    const productInput = screen.getByPlaceholderText(/Search product name, code…/i);
    fireEvent.change(productInput, { target: { value: 'Steam' } });

    const option = await screen.findByText('Steam Iron 2000W');
    fireEvent.click(option);

    // Enter Documented and Received quantities using element IDs
    const docInput = document.getElementById('add-line-doc') as HTMLInputElement;
    fireEvent.change(docInput, { target: { value: '5' } });

    const recvInput = document.getElementById('add-line-recv') as HTMLInputElement;
    fireEvent.change(recvInput, { target: { value: '5' } });

    // Enter Condition Split (OK and Packed = 5)
    await waitFor(() => {
      expect(document.getElementById('add-line-bucket-OK_PACKED')).toBeInTheDocument();
    });
    const bucketInput = document.getElementById('add-line-bucket-OK_PACKED') as HTMLInputElement;
    fireEvent.change(bucketInput, { target: { value: '5' } });

    // Reason is mandatory
    const reasonInput = document.getElementById('add-line-reason') as HTMLTextAreaElement;
    fireEvent.change(reasonInput, { target: { value: 'Found extra carton with goods' } });

    const submitBtn = screen.getByRole('button', { name: /Add Line \(RM_ADD_LINE\)/i });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(addLineFn).toHaveBeenCalledWith(
        'gs-222',
        expect.objectContaining({
          product_id: 'prod-20',
          documented_qty: 5,
          received_qty: 5,
          buckets: expect.arrayContaining([{ field_code: 'OK_PACKED', qty: 5 }]),
          reason: 'Found extra carton with goods',
        }),
        expect.any(String),
      );
    });
  });

  it('allows RM to open Change Product modal on a line, pick new product, enter split & reason, and submit (DEC-54)', async () => {
    changeProductFn.mockResolvedValue({
      ...mockData.items[0]!,
      product_id: 'prod-20',
      sku_code: 'SKU-STEAM-01',
      sku_name: 'Steam Iron 2000W',
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Electric Iron 1000W/i)).toBeInTheDocument();

    const changeBtn = screen.getByRole('button', { name: /Change product/i });
    fireEvent.click(changeBtn);

    expect(screen.getByText(/Change Product: Electric Iron 1000W/i)).toBeInTheDocument();

    // Select new product
    const prodSearchWrapper = document.getElementById('change-prod-search')!;
    const productInput = prodSearchWrapper.querySelector('input')!;
    fireEvent.change(productInput, { target: { value: 'Steam' } });

    const option = await screen.findByText('Steam Iron 2000W');
    fireEvent.click(option);

    // Existing received_qty is 8, so set OK and Packed to 8 for G-19 conservation
    await waitFor(() => {
      expect(document.getElementById('change-prod-bucket-OK_PACKED')).toBeInTheDocument();
    });
    const bucketInput = document.getElementById('change-prod-bucket-OK_PACKED') as HTMLInputElement;
    fireEvent.change(bucketInput, { target: { value: '8' } });

    const reasonInput = document.getElementById('change-prod-reason') as HTMLTextAreaElement;
    fireEvent.change(reasonInput, { target: { value: 'Carton marked Steam Iron 2000W not 1000W' } });

    const submitBtn = screen.getByRole('button', { name: /Change Product \(RM_CHANGE_PRODUCT\)/i });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(changeProductFn).toHaveBeenCalledWith(
        'gs-222',
        'item-10',
        expect.objectContaining({
          product_id: 'prod-20',
          buckets: expect.arrayContaining([{ field_code: 'OK_PACKED', qty: 8 }]),
          reason: 'Carton marked Steam Iron 2000W not 1000W',
        }),
        expect.any(String),
      );
    });
  });

  it('allows RM to open Remove Line modal on a line, enter mandatory reason, and submit (DEC-54)', async () => {
    // Provide 2 items so that remaining count > 1 (BR-07)
    getReviewDataFn.mockResolvedValue({
      ...mockData,
      items: [
        mockData.items[0]!,
        {
          item_id: 'item-20',
          product_id: 'prod-20',
          sku_code: 'SKU-STEAM-01',
          sku_name: 'Steam Iron 2000W',
          documented_qty: 4,
          received_qty: 4,
          short_qty: 0,
          excess_qty: 0,
          allowed_buckets: [
            { field_id: 'f-1', field_code: 'OK_PACKED', field_label: 'OK and Packed', sort_order: 10 },
          ],
          allowed_counts: [],
          buckets: [
            { id: 'b-20', item_id: 'item-20', field_code: 'OK_PACKED', field_label: 'OK and Packed', qty: 4 },
          ],
          total_bucket_qty: 4,
          is_conserved: true,
          counts: [],
        },
      ],
    });

    removeLineFn.mockResolvedValue({
      goods_slip_id: 'gs-222',
      item_id: 'item-10',
      status: 'REMOVED',
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Electric Iron 1000W/i)).toBeInTheDocument();

    const removeBtns = screen.getAllByRole('button', { name: /Remove line/i });
    fireEvent.click(removeBtns[0]!);

    expect(screen.getByText(/Remove Item Line \(DEC-54\)/i)).toBeInTheDocument();

    const reasonInput = document.getElementById('remove-line-reason') as HTMLTextAreaElement;
    fireEvent.change(reasonInput, { target: { value: 'Item belongs to another party shipment' } });

    const confirmBtn = screen.getByRole('button', { name: /Remove Line \(RM_REMOVE_LINE\)/i });
    expect(confirmBtn).not.toBeDisabled();
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(removeLineFn).toHaveBeenCalledWith(
        'gs-222',
        'item-10',
        { reason: 'Item belongs to another party shipment' },
        expect.any(String),
      );
    });
  });

  it('disables / hides all review edit, add, remove, send-back, and approve actions when transfer slip is present (DEC-54 T2)', async () => {
    getReviewDataFn.mockResolvedValue({
      ...mockData,
      transfer_slip: {
        id: 'trf-999',
        transfer_no: 'TRF/2026/0001',
        status: 'INITIATED',
        from_location_code: 'INWARD_STAGING',
        to_location_code: 'INTERMEDIATE_STORE',
        total_lines: 1,
        total_qty: 8,
      },
      can_review: false,
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Transfer Slip Auto-Generated: TRF\/2026\/0001/i)).toBeInTheDocument();

    // Review modification and workflow action buttons must be completely absent (strictly read-only)
    expect(screen.queryByRole('button', { name: /Add line/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Change product/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove line/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Edit Qty\/Buckets/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Send Back/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve & Handover/i })).not.toBeInTheDocument();
  });

  it('displays revision history badges for RM_ADD_LINE, RM_CHANGE_PRODUCT, and RM_REMOVE_LINE (DEC-54)', async () => {
    getReviewDataFn.mockResolvedValue({
      ...mockData,
      revisions: [
        ...mockData.revisions,
        {
          id: 'rev-2',
          revision_no: 2,
          action: 'RM_ADD_LINE',
          items_snapshot: [],
          remarks: 'Added line 2',
          created_by: 'user-rm',
          created_by_name: 'Pratham',
          created_at: '2026-11-13T11:00:00Z',
        },
        {
          id: 'rev-3',
          revision_no: 3,
          action: 'RM_CHANGE_PRODUCT',
          items_snapshot: [],
          remarks: 'Changed product to 2000W',
          created_by: 'user-rm',
          created_by_name: 'Pratham',
          created_at: '2026-11-13T11:10:00Z',
        },
        {
          id: 'rev-4',
          revision_no: 4,
          action: 'RM_REMOVE_LINE',
          items_snapshot: [],
          remarks: 'Removed wrong line',
          created_by: 'user-rm',
          created_by_name: 'Pratham',
          created_at: '2026-11-13T11:20:00Z',
        },
      ],
    });

    render(<RmReviewPage gsId="gs-222" onBack={vi.fn()} />);

    expect(await screen.findByText(/Revision Audit Trail/i)).toBeInTheDocument();

    const expandBtn = screen.getByRole('button', { name: /Revision Audit Trail/i });
    fireEvent.click(expandBtn);

    expect(screen.getByText('RM_ADD_LINE')).toBeInTheDocument();
    expect(screen.getByText('RM_CHANGE_PRODUCT')).toBeInTheDocument();
    expect(screen.getByText('RM_REMOVE_LINE')).toBeInTheDocument();
    expect(screen.getByText(/"Added line 2"/i)).toBeInTheDocument();
    expect(screen.getByText(/"Changed product to 2000W"/i)).toBeInTheDocument();
    expect(screen.getByText(/"Removed wrong line"/i)).toBeInTheDocument();
  });
});
