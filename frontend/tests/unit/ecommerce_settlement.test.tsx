/**
 * DEC-76: E-Commerce settlement screens: the executive's portal resolution (ticket close, portal
 * check), unboxing per platform into an action sheet, store acknowledgement and the credit note on
 * the action sheet. Rendered from backend-shaped payloads; only the HTTP layer is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    code: 'ERR',
    requestId: 'req-ecom',
    fieldErrors: {},
  }),
}));

import { EcomActionSheetPage } from '@/features/ecommerce-returns/EcomActionSheetPage';
import { EcomStoreReceiptsPage } from '@/features/ecommerce-returns/EcomStoreReceiptsPage';
import { EcomUnboxingPage } from '@/features/ecommerce-returns/EcomUnboxingPage';
import { PortalCheckPage } from '@/features/ecommerce-returns/PortalCheckPage';
import { TicketQueuePage } from '@/features/ecommerce-returns/TicketQueuePage';
import { entryPath, itemPath } from '@/features/journey/screens';

const RESOLUTIONS = [
  { code: 'FREE_REPLACEMENT', label: 'Free Replacement' },
  { code: 'REFUND', label: 'Refund' },
];

afterEach(() => {
  apiRequest.mockReset();
});

describe('E-Commerce Executive (DEC-76)', () => {
  const ticket = {
    id: 't-1',
    sla_due_at: '2026-11-26T10:00:00Z',
    sla_state: 'RAISED_ON_TIME',
    minutes_to_due: null,
    assigned_handler_id: 'u-1',
    assigned_handler_name: 'Exec',
    raised_at: '2026-11-26T09:00:00Z',
    response_code: 'CLAIM_RECEIVED',
    response_label: 'Claim Received',
    rejection_remark: null,
    claim_amount: '250.00',
    responded_at: '2026-11-26T09:30:00Z',
    responded_by_name: 'Exec',
    closed_at: null,
    closed_by_name: null,
    follow_up_count: 2,
    last_follow_up_at: '2026-11-26T09:20:00Z',
    next_follow_up_on: '2026-11-28',
  };
  const row = {
    return_id: 'r-1',
    return_no: 'ECR/2026-27/00001',
    entry_date: '2026-11-26',
    platform_label: 'Amazon',
    order_id: '408-1',
    product_text: 'Thermometer',
    qty: 3,
    status: 'TICKET_RAISED',
    status_label: 'Ticket Raised',
    ticket,
  };

  it('closes a ticket with the portal resolution and records follow-ups', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-tickets' && !options?.method)
        return Promise.resolve({
          response_options: [{ code: 'CLAIM_RECEIVED', label: 'Claim Received' }],
          resolution_options: RESOLUTIONS,
          rows: [row],
        });
      return Promise.resolve({});
    });
    render(<TicketQueuePage canEdit onOpen={vi.fn()} />);
    expect((await screen.findByTestId('ticket-follow-ups')).textContent).toContain('2 follow-up');

    fireEvent.click(screen.getByTestId('ticket-close'));
    fireEvent.click(screen.getByTestId('resolution-save'));
    expect(await screen.findByText('Choose what the portal shows for this order')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Refund'));
    fireEvent.change(screen.getByLabelText(/^Qty/), { target: { value: '4' } });
    fireEvent.click(screen.getByTestId('resolution-save'));
    expect(await screen.findByText('Qty must be 1 to 3')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Qty/), { target: { value: '2' } });
    expect(screen.getByText('Accounts issues a credit note for 2 pc(s).')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Short note'), { target: { value: ' Refunded ' } });
    fireEvent.click(screen.getByTestId('resolution-save'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-tickets/t-1/close',
        expect.objectContaining({
          method: 'POST',
          idempotencyKey: 'web-test-key',
          body: { resolution_code: 'REFUND', resolution_qty: 2, resolution_note: 'Refunded' },
        }),
      );
    });

    fireEvent.click(screen.getByTestId('ticket-follow-up'));
    fireEvent.change(screen.getByLabelText(/What happened/), {
      target: { value: 'Called support' },
    });
    fireEvent.click(screen.getByTestId('follow-up-save'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-tickets/t-1/follow-up',
        expect.objectContaining({ body: { note: 'Called support', next_follow_up_on: null } }),
      );
    });
  });

  it('records a portal check for a return without a ticket', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-tickets/portal-checks' && !options?.method)
        return Promise.resolve({
          resolution_options: RESOLUTIONS,
          rows: [
            {
              return_id: 'r-2',
              return_no: 'ECR/2026-27/00002',
              entry_date: '2026-11-26',
              platform_label: 'Flipkart',
              order_id: 'OD1',
              product_text: 'Thermometer',
              qty: 1,
              submitted_at: '2026-11-26T08:00:00Z',
            },
          ],
        });
      return Promise.resolve({});
    });
    render(<PortalCheckPage canEdit onOpen={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('portal-check-record'));
    fireEvent.click(screen.getByLabelText('Free Replacement'));
    expect(screen.getByText('No credit note for this order.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('resolution-save'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-tickets/portal-checks/r-2',
        expect.objectContaining({
          body: { resolution_code: 'FREE_REPLACEMENT', resolution_qty: 1, resolution_note: null },
        }),
      );
    });
  });

  it('hides the portal check action without ecommerce_tickets.edit', async () => {
    apiRequest.mockResolvedValue({ resolution_options: RESOLUTIONS, rows: [] });
    render(<PortalCheckPage canEdit={false} onOpen={vi.fn()} />);
    expect(await screen.findByText('Nothing to check')).toBeTruthy();
  });
});

describe('E-Commerce unboxing (DEC-76)', () => {
  const base = {
    entry_date: '2026-11-26',
    qc_routing_label: 'Ticket Raise',
    resolution_note: null,
    resolved_at: '2026-11-26T09:00:00Z',
    store_name: 'Intermediate Store OP',
  };
  const QUEUE = {
    platforms: [
      { code: 'AMAZON', label: 'Amazon' },
      { code: 'FLIPKART', label: 'Flipkart' },
    ],
    buckets: [
      { code: 'TO_STORE', label: 'Good / Fresh → Store' },
      { code: 'TO_REPAIR', label: 'Production / Repair' },
      { code: 'WASTAGE', label: 'Damaged / Wastage' },
    ],
    repair_locations: [{ id: 'loc-r', code: 'DEPT_REPACKAGING', name: 'Department: Repackaging' }],
    rows: [
      {
        ...base,
        return_id: 'a1',
        return_no: 'ECR/1',
        platform_code: 'AMAZON',
        platform_label: 'Amazon',
        order_id: 'AMZ-1',
        product_text: 'Thermometer (T1)',
        is_company_product: true,
        qty: 2,
        resolution_code: 'REFUND',
        resolution_label: 'Refund',
        resolution_qty: 2,
        cn_qty: 2,
      },
      {
        ...base,
        return_id: 'a2',
        return_no: 'ECR/2',
        platform_code: 'AMAZON',
        platform_label: 'Amazon',
        order_id: 'AMZ-2',
        product_text: 'A toy car',
        is_company_product: false,
        qty: 1,
        resolution_code: 'FREE_REPLACEMENT',
        resolution_label: 'Free Replacement',
        resolution_qty: 1,
        cn_qty: 0,
        store_name: null,
      },
      {
        ...base,
        return_id: 'f1',
        return_no: 'ECR/3',
        platform_code: 'FLIPKART',
        platform_label: 'Flipkart',
        order_id: 'OD-1',
        product_text: 'Thermometer (T1)',
        is_company_product: true,
        qty: 1,
        resolution_code: 'REFUND',
        resolution_label: 'Refund',
        resolution_qty: 1,
        cn_qty: 1,
      },
    ],
    repairs: [],
  };

  it('splits the pieces per order and submits one platform as an action sheet', async () => {
    const onOpenSheet = vi.fn();
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-settlement/unboxing' && !options?.method)
        return Promise.resolve(QUEUE);
      if (path === '/ecommerce-settlement/unboxing') return Promise.resolve({ id: 'sheet-1' });
      return Promise.resolve({});
    });
    render(<EcomUnboxingPage canEdit onOpen={vi.fn()} onOpenSheet={onOpenSheet} />);
    const card = await screen.findByTestId('unbox-ECR/1');
    expect(screen.getByTestId('unbox-platform-AMAZON').textContent).toContain('Amazon (2)');
    // Not our product: all wastage, no qty fields.
    expect(within(screen.getByTestId('unbox-ECR/2')).getByText(/Not our product/)).toBeTruthy();
    expect(screen.queryByTestId('unbox-ECR/3')).toBeNull(); // other platform tab

    // Move one piece from the store to repair: the department becomes required.
    const good = within(within(card).getByTestId('unbox-good')).getByRole('spinbutton');
    const repair = within(within(card).getByTestId('unbox-repair')).getByRole('spinbutton');
    fireEvent.change(good, { target: { value: '1' } });
    expect(within(card).getByText('Store + repair + wastage must be 2')).toBeTruthy();
    expect(screen.getByTestId<HTMLButtonElement>('unbox-submit').disabled).toBe(true);
    fireEvent.change(repair, { target: { value: '1' } });
    expect(within(card).getByText('Choose the repair department')).toBeTruthy();
    fireEvent.change(within(card).getByLabelText('Repair department'), {
      target: { value: 'loc-r' },
    });
    expect(screen.getByText(/Qty Issue CN 2/, { selector: 'p' })).toBeTruthy();
    fireEvent.click(screen.getByTestId('unbox-submit'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-settlement/unboxing',
        expect.objectContaining({
          method: 'POST',
          idempotencyKey: 'web-test-key',
          body: {
            platform_code: 'AMAZON',
            lines: [
              {
                return_id: 'a1',
                good_qty: 1,
                repair_qty: 1,
                wastage_qty: 0,
                repair_location_id: 'loc-r',
                note: null,
              },
              {
                return_id: 'a2',
                good_qty: 0,
                repair_qty: 0,
                wastage_qty: 1,
                repair_location_id: null,
                note: null,
              },
            ],
          },
        }),
      );
    });
    await waitFor(() => {
      expect(onOpenSheet).toHaveBeenCalledWith('sheet-1');
    });
  });

  it('shows an empty state and no submit bar when nothing waits', async () => {
    apiRequest.mockResolvedValue({ ...QUEUE, rows: [] });
    render(<EcomUnboxingPage canEdit onOpen={vi.fn()} onOpenSheet={vi.fn()} />);
    expect(await screen.findByText('Nothing to unbox')).toBeTruthy();
    expect(screen.queryByTestId('unbox-submit')).toBeNull();
  });
});

describe('Store receipts and action sheet (DEC-76)', () => {
  it('acknowledges the selected receipts of the store', async () => {
    const receipt = (id: string, can: boolean) => ({
      id,
      return_id: `r-${id}`,
      return_no: `ECR/${id}`,
      platform_label: 'Amazon',
      order_id: `AMZ-${id}`,
      product_code: 'T1',
      product_name: 'Thermometer',
      source: 'UNBOXING',
      source_label: 'Good / Fresh → Store',
      store_id: 's-1',
      store_name: 'Intermediate Store OP',
      from_location_name: 'Inward Staging',
      qty: 1,
      status: 'PENDING',
      created_at: '2026-11-26T09:00:00Z',
      acknowledged_at: null,
      acknowledged_by_name: null,
      can_acknowledge: can,
    });
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-settlement/store-receipts' && !options?.method)
        return Promise.resolve({ rows: [receipt('1', true), receipt('2', false)] });
      return Promise.resolve({ rows: [receipt('1', false)] });
    });
    render(<EcomStoreReceiptsPage onOpen={vi.fn()} />);
    await screen.findByTestId('receipt-ECR/1');
    expect(screen.queryByLabelText('Select ECR/2')).toBeNull(); // another store's receipt
    fireEvent.click(screen.getByLabelText('Select ECR/1'));
    fireEvent.click(screen.getByTestId('receipts-acknowledge'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-settlement/store-receipts/acknowledge',
        expect.objectContaining({ body: { receipt_ids: ['1'] }, idempotencyKey: 'web-test-key' }),
      );
    });
    expect(await screen.findByText('1 receipt(s) acknowledged.')).toBeTruthy();
  });

  const SHEET = {
    id: 'sheet-1',
    sheet_no: 'EAS/2026-27/00001',
    platform_code: 'AMAZON',
    platform_label: 'Amazon',
    status: 'PENDING_ACCOUNTS',
    status_label: 'Pending with Accounts',
    created_at: '2026-11-26T10:00:00Z',
    created_by_name: 'Unboxer',
    total_received: 3,
    total_cn_qty: 2,
    cn_no: null,
    cn_date: null,
    cn_value: null,
    remarks: null,
    completed_at: null,
    completed_by_name: null,
    company_name: 'Hicks',
    business_today: '2026-11-26',
    lines: [
      {
        return_id: 'a1',
        return_no: 'ECR/1',
        entry_date: '2026-11-26',
        order_id: 'AMZ-1',
        product_text: 'Thermometer (T1)',
        qty_received: 2,
        resolution_code: 'REFUND',
        resolution_label: 'Refund',
        resolution_qty: 2,
        cn_qty: 2,
        good_qty: 2,
        repair_qty: 0,
        wastage_qty: 0,
        status: 'UNBOXED',
        status_label: 'In Process',
      },
      {
        return_id: 'a2',
        return_no: 'ECR/2',
        entry_date: '2026-11-26',
        order_id: 'AMZ-2',
        product_text: 'A toy car',
        qty_received: 1,
        resolution_code: 'FREE_REPLACEMENT',
        resolution_label: 'Free Replacement',
        resolution_qty: 1,
        cn_qty: 0,
        good_qty: 0,
        repair_qty: 0,
        wastage_qty: 1,
        status: 'CLOSED',
        status_label: 'Closed',
      },
    ],
  };

  it('prints the platform and the totals, and Accounts issues the credit note', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-settlement/action-sheets/sheet-1' && !options?.method)
        return Promise.resolve(SHEET);
      return Promise.resolve({
        ...SHEET,
        status: 'COMPLETED',
        status_label: 'Completed',
        cn_no: 'CN-1',
        cn_date: '2026-11-26',
        cn_value: '500.00',
      });
    });
    render(
      <EcomActionSheetPage sheetId="sheet-1" canIssueCn onBack={vi.fn()} onOpenReturn={vi.fn()} />,
    );
    expect((await screen.findByTestId('sheet-platform')).textContent).toBe('Amazon');
    const table = screen.getByTestId('sheet-table');
    expect(within(table).getByText('AMZ-1')).toBeTruthy();
    expect(within(table).getByText('Total (2 order(s))')).toBeTruthy();

    fireEvent.click(screen.getByTestId('sheet-complete'));
    expect(await screen.findByText('Enter the CN number, date and value')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/CN No/), { target: { value: 'CN-1' } });
    fireEvent.change(screen.getByLabelText(/CN Value/), { target: { value: '500' } });
    fireEvent.click(screen.getByTestId('sheet-complete'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-settlement/action-sheets/sheet-1/complete',
        expect.objectContaining({
          body: { cn_no: 'CN-1', cn_date: '2026-11-26', cn_value: '500.00', remarks: null },
        }),
      );
    });
    expect((await screen.findByTestId('sheet-cn')).textContent).toContain('CN-1');
    expect(screen.queryByTestId('sheet-issue-cn')).toBeNull();
  });

  it('has no credit note form without ecommerce_accounts.edit', async () => {
    apiRequest.mockResolvedValue(SHEET);
    render(
      <EcomActionSheetPage
        sheetId="sheet-1"
        canIssueCn={false}
        onBack={vi.fn()}
        onOpenReturn={vi.fn()}
      />,
    );
    await screen.findByTestId('sheet-platform');
    expect(screen.queryByTestId('sheet-issue-cn')).toBeNull();
  });
});

describe('journey screens (DEC-76)', () => {
  it('maps the settlement menu entries to their pages', () => {
    expect(entryPath({ code: 'ECOM_PORTAL_CHECK', screen_key: 'ecom-portal-check' })).toBe(
      '/ecom-portal-check',
    );
    expect(entryPath({ code: 'ECOM_UNBOXING', screen_key: 'ecom-unboxing' })).toBe(
      '/ecom-unboxing',
    );
    expect(entryPath({ code: 'ECOM_STORE_RECEIPTS', screen_key: 'ecom-store-receipts' })).toBe(
      '/ecom-store-receipts',
    );
    expect(entryPath({ code: 'ECOM_ACTION_SHEETS', screen_key: 'ecom-action-sheets' })).toBe(
      '/ecom-action-sheets',
    );
    expect(itemPath('ecom-action-sheet', { gs_id: '', target_id: 's-9' })).toBe(
      '/ecom-action-sheets/s-9',
    );
  });
});
