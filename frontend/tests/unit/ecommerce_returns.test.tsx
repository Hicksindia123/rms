/**
 * DEC-73: E-Commerce Return gate entry (config-driven options, conditional product fields,
 * mandatory gallery-only video, 50 MB image total) and the Ticket Handler queue (SLA flag,
 * actions). Rendered from backend-shaped payloads; only the HTTP layer is mocked.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

import { EcommerceGateEntryPage } from '@/features/ecommerce-returns/EcommerceGateEntryPage';
import { TicketQueuePage } from '@/features/ecommerce-returns/TicketQueuePage';
import { entryPath, itemPath } from '@/features/journey/screens';

const MB = 1024 * 1024;
const CONFIG = {
  return_types: [
    { code: 'OFFLINE_RETURN', label: 'Offline Return' },
    { code: 'ECOMMERCE_RETURN', label: 'E-Commerce Return' },
  ],
  platforms: [
    { code: 'AMAZON', label: 'Amazon' },
    { code: 'FLIPKART', label: 'Flipkart' },
    { code: 'WEBSITE', label: 'Website' },
  ],
  product_types: [
    { code: 'COMPANY_PRODUCT', label: 'Company Product' },
    { code: 'DIFFERENT_PRODUCT', label: 'Different Product' },
  ],
  qc_routings: [
    { code: 'TICKET_RAISE', label: 'Ticket Raise' },
    { code: 'ISSUE_TO_CHECKING', label: 'Issue to Checking Department' },
  ],
  business_today: '2026-11-24',
  min_entry_date: '2026-11-17',
  order_id_pattern: '^[A-Za-z0-9-]{3,40}$',
  video: {
    mime_types: ['video/mp4', 'video/quicktime'],
    extensions: ['mov', 'mp4', 'qt'],
    max_bytes: 1024 * MB,
  },
  images: {
    mime_types: ['image/heic', 'image/heif', 'image/jpeg', 'image/png'],
    extensions: ['heic', 'heif', 'jpeg', 'jpg', 'png'],
    max_bytes_each: 25 * MB,
    max_total_bytes: 50 * MB,
  },
  ticket_sla_hours: 2,
};

function file(name: string, type: string, size: number): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

afterEach(() => {
  apiRequest.mockReset();
});

describe('E-Commerce gate entry (DEC-73)', () => {
  async function renderForm(onOffline?: () => void) {
    apiRequest.mockImplementation((path) => {
      if (path === '/ecommerce-returns/form-config') return Promise.resolve(CONFIG);
      return Promise.resolve([]);
    });
    render(<EcommerceGateEntryPage onOffline={onOffline} onOpen={vi.fn()} />);
    await screen.findByTestId('ecom-gate-entry');
  }

  it('renders the configured options and switches back to the offline form', async () => {
    const onOffline = vi.fn();
    await renderForm(onOffline);
    expect(screen.getByRole('option', { name: 'Flipkart' })).toBeTruthy();
    expect(screen.getByText('Issue to Checking Department')).toBeTruthy();
    fireEvent.click(screen.getByTestId('return-type-OFFLINE_RETURN'));
    expect(onOffline).toHaveBeenCalled();
  });

  it('hides the offline switch when the user cannot record offline returns', async () => {
    await renderForm(undefined);
    expect(screen.queryByTestId('return-type-OFFLINE_RETURN')).toBeNull();
  });

  it('shows the product field that matches the product type', async () => {
    await renderForm();
    expect(screen.queryByLabelText(/Different Product Name/)).toBeNull();
    fireEvent.click(screen.getByLabelText('Different Product'));
    expect(screen.getByLabelText(/Different Product Name/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Company Product'));
    expect(screen.queryByLabelText(/Different Product Name/)).toBeNull();
    expect(screen.getByLabelText('Product')).toBeTruthy();
  });

  it('video input is gallery / file only (no camera capture)', async () => {
    await renderForm();
    const input = document.getElementById('ecom-video') as HTMLInputElement;
    expect(input.type).toBe('file');
    expect(input.hasAttribute('capture')).toBe(false);
    expect(input.accept).toContain('video/mp4');
  });

  it('blocks submit until the required fields and the video are valid', async () => {
    await renderForm();
    fireEvent.click(screen.getByTestId('ecom-record'));
    expect(await screen.findByText('Choose the platform')).toBeTruthy();
    expect(screen.getByText('The Order ID is required')).toBeTruthy();
    expect(screen.getByText('Choose the product type')).toBeTruthy();
    expect(screen.getByText('Choose the QC status')).toBeTruthy();
    expect(screen.getByText('The package opening video is required')).toBeTruthy();
    expect(apiRequest).not.toHaveBeenCalledWith('/ecommerce-returns', expect.anything());
  });

  it('rejects images over 50 MB together', async () => {
    await renderForm();
    const input = document.getElementById('ecom-images') as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          file('a.jpg', 'image/jpeg', 20 * MB),
          file('b.jpg', 'image/jpeg', 20 * MB),
          file('c.jpg', 'image/jpeg', 20 * MB),
        ],
      },
    });
    fireEvent.click(screen.getByTestId('ecom-record'));
    expect(await screen.findByText(/the limit is 50\.0 MB together/)).toBeTruthy();
  });

  it('sends only the active product field and the declared files', async () => {
    await renderForm();
    fireEvent.change(screen.getByLabelText(/Platform/), { target: { value: 'AMAZON' } });
    fireEvent.change(screen.getByLabelText(/Order ID/), { target: { value: ' 408-1234567 ' } });
    fireEvent.click(screen.getByLabelText('Different Product'));
    fireEvent.change(screen.getByLabelText(/Different Product Name/), {
      target: { value: 'Toy car' },
    });
    fireEvent.click(screen.getByLabelText('Issue to Checking Department'));
    fireEvent.change(document.getElementById('ecom-video') as HTMLInputElement, {
      target: { files: [file('open.mp4', 'video/mp4', 5 * MB)] },
    });
    // The create call fails (network) so the test stops before real uploads.
    apiRequest.mockImplementation((path) =>
      path === '/ecommerce-returns' ? Promise.reject(new Error('offline')) : Promise.resolve([]),
    );
    fireEvent.click(screen.getByTestId('ecom-record'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith('/ecommerce-returns', expect.anything());
    });
    const call = apiRequest.mock.calls.find((c) => c[0] === '/ecommerce-returns');
    const body = call?.[1]?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      platform_code: 'AMAZON',
      order_id: '408-1234567',
      product_type_code: 'DIFFERENT_PRODUCT',
      product_id: null,
      different_product_desc: 'Toy car',
      qty: 1,
      qc_routing_code: 'ISSUE_TO_CHECKING',
      video: { mime_type: 'video/mp4', size_bytes: 5 * MB, file_name: 'open.mp4' },
      images: [],
    });
    expect(call?.[1]?.idempotencyKey).toBe('web-test-key');
    expect(await screen.findByText('offline')).toBeTruthy();
  });
});

describe('Ticket Handler queue (DEC-73)', () => {
  const ticket = (over: Record<string, unknown>) => ({
    id: 't-1',
    sla_due_at: '2026-11-24T10:00:00Z',
    sla_state: 'OVERDUE',
    minutes_to_due: -35,
    assigned_handler_id: null,
    assigned_handler_name: null,
    raised_at: null,
    response_code: null,
    response_label: null,
    rejection_remark: null,
    claim_amount: null,
    responded_at: null,
    responded_by_name: null,
    closed_at: null,
    closed_by_name: null,
    ...over,
  });
  const row = (over: Record<string, unknown>) => ({
    return_id: 'r-1',
    return_no: 'ECR/2026-27/00001',
    entry_date: '2026-11-24',
    platform_label: 'Amazon',
    order_id: '408-1',
    product_text: 'Thermometer (T1)',
    qty: 1,
    status: 'PENDING_TICKET',
    status_label: 'Ticket Pending',
    ticket: ticket({}),
    ...over,
  });
  const RESPONSES = [
    { code: 'REJECTED', label: 'Rejected' },
    { code: 'CLAIM_RECEIVED', label: 'Claim Received' },
    { code: 'PENDING', label: 'Pending' },
  ];

  it('flags an overdue ticket and raises it with an Idempotency-Key', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-tickets' && !options?.method)
        return Promise.resolve({ response_options: RESPONSES, rows: [row({})] });
      return Promise.resolve({});
    });
    render(<TicketQueuePage canEdit onOpen={vi.fn()} />);
    expect((await screen.findByTestId('sla-overdue')).textContent).toContain('OVERDUE by 35 min');
    fireEvent.click(screen.getByTestId('ticket-raise'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-tickets/t-1/raise',
        expect.objectContaining({ method: 'POST', idempotencyKey: 'web-test-key' }),
      );
    });
  });

  it('cannot close a Pending ticket and requires the claim amount', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/ecommerce-tickets' && !options?.method)
        return Promise.resolve({
          response_options: RESPONSES,
          rows: [
            row({
              status: 'TICKET_RAISED',
              status_label: 'Ticket Raised',
              ticket: ticket({
                sla_state: 'RAISED_ON_TIME',
                minutes_to_due: null,
                raised_at: '2026-11-24T09:00:00Z',
                assigned_handler_name: 'Handler',
                response_code: 'PENDING',
                response_label: 'Pending',
              }),
            }),
          ],
        });
      return Promise.resolve({});
    });
    render(<TicketQueuePage canEdit onOpen={vi.fn()} />);
    const close = await screen.findByTestId('ticket-close');
    expect((close as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId('ticket-respond'));
    fireEvent.click(screen.getByLabelText('Claim Received'));
    fireEvent.click(screen.getByTestId('ticket-response-save'));
    expect(await screen.findByText('Enter the claim amount the platform granted')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Claim amount/), { target: { value: '1499.5' } });
    fireEvent.click(screen.getByTestId('ticket-response-save'));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/ecommerce-tickets/t-1/response',
        expect.objectContaining({
          body: {
            response_code: 'CLAIM_RECEIVED',
            rejection_remark: null,
            claim_amount: '1499.50',
          },
        }),
      );
    });
  });

  it('hides the actions without ecommerce_tickets.edit', async () => {
    apiRequest.mockResolvedValue({ response_options: RESPONSES, rows: [row({})] });
    render(<TicketQueuePage canEdit={false} onOpen={vi.fn()} />);
    await screen.findByTestId('sla-overdue');
    expect(screen.queryByTestId('ticket-raise')).toBeNull();
  });
});

describe('journey screens (DEC-73)', () => {
  it('maps the e-commerce menu entries to their pages', () => {
    expect(entryPath({ code: 'ECOM_GATE_ENTRY', screen_key: 'ecom-return-new' })).toBe(
      '/ecom-returns/new',
    );
    expect(entryPath({ code: 'ECOM_TICKETS', screen_key: 'ecom-tickets' })).toBe('/ecom-tickets');
    expect(itemPath('ecom-return', { gs_id: '', target_id: 'r-9' })).toBe('/ecom-returns/r-9');
  });
});
