/**
 * Phase P2 / DEC-62: gate form S1_GATE_INWARD v4 screen.
 * Required asterisks come from is_required / required_when of the form config (not hard-coded);
 * "Submit & Create GS" opens a summary sheet; the GS is created only on Submit, with one
 * Idempotency-Key per sheet; document rows are type + file; failed uploads can be retried or
 * removed. The API client is mocked with backend-shaped payloads (goods_slips/schemas.py).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiRequestOptions } from '@/lib/api/client';

const apiRequestFn = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>();
const transferMode = { fail: false };

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    apiRequest: (path: string, options?: ApiRequestOptions) => apiRequestFn(path, options),
  };
});

vi.mock('@/features/unboxing/uploader', () => ({
  createTransfer: (
    _file: Blob,
    _ticket: unknown,
    _type: string,
    handlers: {
      onProgress: (loaded: number, total: number) => void;
      onSuccess: () => void;
      onError: (message: string) => void;
    },
  ) => ({
    resumable: false,
    start() {
      handlers.onProgress(50, 100);
      if (transferMode.fail) handlers.onError('Network down');
      else handlers.onSuccess();
    },
  }),
}));

const { NewGoodsSlipPage } = await import('@/features/goods-slips/NewGoodsSlipPage');

const mode = (value: string) => ({ field: 'delivery_mode', op: 'eq', value });
const option = (code: string, label: string, sort_order: number) => ({
  code,
  label,
  sort_order,
  is_active: true,
});

/** Backend-shaped GET /gs/gate-form for the published v4 (seed.sql DEC-62 block). */
const GATE_FORM = {
  form_version_id: 'fv-4',
  contact_phone_pattern: '^[0-9]{10}$',
  party_state_station_autofill: true,
  business_today: '2026-11-20',
  max_backdate_days: null,
  document_types: [
    { code: 'INVOICE', label: 'Invoice', required_fields: ['doc_no', 'doc_date'] },
    { code: 'DEBIT_NOTE', label: 'GST Debit Note', required_fields: ['doc_no', 'doc_date'] },
    { code: 'HANDWRITTEN_SLIP', label: 'Hand Written Slip', required_fields: ['remarks'] },
  ],
  transport_document_types: [{ code: 'COURIER_SLIP', label: 'Courier Slip', required_fields: [] }],
  snapshot: {
    form_code: 'S1_GATE_INWARD',
    name: 'Gate Inward & GS Creation',
    version_no: 4,
    fields: [
      {
        field_key: 'return_type',
        label: 'Return Type',
        control_type: 'radio',
        is_required: true,
        sort_order: 5,
        section: 'Return Type',
        option_items: [
          option('OFFLINE_RETURN', 'Offline Return', 10),
          option('ECOMMERCE_RETURN', 'E-Commerce Return', 20),
        ],
      },
      {
        field_key: 'gate_entry_no',
        label: 'Gate Entry Number',
        control_type: 'number',
        is_required: false,
        visible_when: { field: 'return_type', op: 'eq', value: 'OFFLINE_RETURN' },
        required_when: { field: 'return_type', op: 'eq', value: 'OFFLINE_RETURN' },
        sort_order: 7,
        section: 'Gate Entry',
      },
      ...(['state', 'station'] as const).map((k, i) => ({
        field_key: k,
        label: k === 'state' ? 'State' : 'Station',
        control_type: 'text',
        is_required: true,
        sort_order: 10 + i * 10,
        section: 'Consignment Header',
      })),
      {
        field_key: 'party_name',
        label: 'Party',
        control_type: 'text',
        is_required: true,
        sort_order: 30,
        section: 'Consignment Header',
      },
      {
        field_key: 'carton_count',
        label: 'Cartons',
        control_type: 'number',
        is_required: true,
        validation: { min: 1 },
        sort_order: 40,
        section: 'Consignment Header',
      },
      {
        field_key: 'delivery_mode',
        label: 'Received Through',
        control_type: 'dropdown',
        is_required: true,
        sort_order: 50,
        section: 'Received Through',
        option_items: [
          option('COURIER_PARCEL', 'Courier', 10),
          option('DIRECT_TRUCK', 'Transport', 20),
          option('SELF_PARTY_REP', 'By Hand', 30),
        ],
      },
      ...(
        [
          ['courier_name', 'Courier Name', 'COURIER_PARCEL', 60],
          ['docket_no', 'Docket No.', 'COURIER_PARCEL', 70],
          ['transporter_name', 'Transport Name', 'DIRECT_TRUCK', 90],
          ['rep_name', 'Contact Name', 'SELF_PARTY_REP', 100],
          ['rep_contact', 'Contact Number', 'SELF_PARTY_REP', 110],
        ] as const
      ).map(([field_key, label, code, sort_order]) => ({
        field_key,
        label,
        control_type: 'text',
        is_required: false,
        visible_when: mode(code),
        required_when: mode(code),
        sort_order,
        section: 'Received Through',
      })),
      {
        field_key: 'no_document',
        label: 'No Documents From Party',
        control_type: 'checkbox',
        is_required: false,
        default_value: false,
        sort_order: 120,
        section: 'Documents From Party',
        help_text: 'Optional.',
      },
      {
        field_key: 'transport_document',
        label: 'Documents From Transport',
        control_type: 'dropdown',
        is_required: false,
        sort_order: 130,
        section: null,
        option_items: [option('COURIER_SLIP', 'Courier Slip', 10)],
      },
    ],
  },
};

const GS = {
  id: 'gs-1',
  gs_no: 'GS/2026-27/00042',
  status: 'GATE_CREATED',
  carton_count: 3,
  return_type_label: 'E-Commerce Return',
  party_name: 'New Party',
  gate_entry_no: null,
};

function route(createDocs: Array<{ id: string }> = []) {
  apiRequestFn.mockImplementation((path: string, options?: ApiRequestOptions) => {
    if (path === '/gs/gate-form') return Promise.resolve(GATE_FORM);
    if (path === '/gs/lookups/states')
      return Promise.resolve([{ id: 'st-1', name: 'Uttar Pradesh' }]);
    if (path === '/gs/lookups/stations') return Promise.resolve([{ id: 'stn-1', name: 'Agra' }]);
    if (path === '/gs/lookups/parties/by-location')
      return Promise.resolve({
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        scope: 'STATION',
        fallback_applied: false,
        fallback_setting: 'STATE',
      });
    if (path === '/gs' && options?.method === 'POST')
      return Promise.resolve({
        goods_slip: { ...GS, documents: createDocs },
        warnings: [],
        task_ids: [],
        notified_user_count: 0,
      });
    if (path.endsWith('/files/upload-url'))
      return Promise.resolve({
        attachment: { id: 'att-1', mime_type: 'image/jpeg' },
        upload: { method: 'PUT', url: 'http://storage.test/put', object_path: 'p/1' },
      });
    if (path.startsWith('/attachments/')) return Promise.resolve({ id: 'att-1' });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function createCalls() {
  return apiRequestFn.mock.calls.filter(([p, o]) => p === '/gs' && o?.method === 'POST');
}

/** The label element of a DynamicForm field and whether it carries the red asterisk. */
function asterisk(label: string): boolean {
  const el = screen.getByText(label, { selector: 'label' });
  return within(el).queryByText('*') !== null;
}

async function renderPage() {
  render(<NewGoodsSlipPage onOpenTag={vi.fn()} onOpenGs={vi.fn()} />);
  await screen.findByRole('button', { name: 'Submit & Create GS' });
}

async function fillHeader() {
  fireEvent.click(screen.getByTestId('return-type-ECOMMERCE_RETURN'));
  fireEvent.change(screen.getByLabelText(/^State/), { target: { value: 'st-1' } });
  await waitFor(() => {
    expect(screen.getByRole('option', { name: 'Agra' })).toBeTruthy();
  });
  fireEvent.change(screen.getByLabelText(/^Station/), { target: { value: 'stn-1' } });
  fireEvent.click(await screen.findByRole('button', { name: /Create provisional party/ }));
  fireEvent.change(screen.getByLabelText('New party name'), { target: { value: 'New Party' } });
  fireEvent.click(screen.getByRole('button', { name: 'Use this party' }));
  fireEvent.change(screen.getByLabelText(/^Cartons/), { target: { value: '3' } });
  fireEvent.change(screen.getByLabelText(/^Received Through/), {
    target: { value: 'COURIER_PARCEL' },
  });
  fireEvent.change(screen.getByLabelText(/^Courier Name/), { target: { value: 'BlueDart' } });
  fireEvent.change(screen.getByLabelText(/^Docket No\./), { target: { value: 'BD-1' } });
}

beforeEach(() => {
  apiRequestFn.mockReset();
  transferMode.fail = false;
});

describe('Gate form v4 (DEC-62)', () => {
  it('marks only the required fields, as configured, and follows Received Through', async () => {
    route();
    await renderPage();
    expect(asterisk('Party')).toBe(true);
    expect(asterisk('State')).toBe(true);
    expect(asterisk('Cartons')).toBe(true);
    expect(asterisk('Received Through')).toBe(true);
    expect(asterisk('Documents From Transport')).toBe(false); // optional (DEC-62)
    expect(screen.queryByText('Vehicle Number')).toBeNull(); // Q5: not on v4

    const modeSelect = screen.getByLabelText(/^Received Through/);
    fireEvent.change(modeSelect, { target: { value: 'COURIER_PARCEL' } });
    expect(asterisk('Courier Name')).toBe(true);
    expect(asterisk('Docket No.')).toBe(true);
    expect(screen.queryByText('Transport Name')).toBeNull();

    fireEvent.change(modeSelect, { target: { value: 'DIRECT_TRUCK' } });
    expect(asterisk('Transport Name')).toBe(true);
    expect(screen.queryByText('Docket No.')).toBeNull();

    fireEvent.change(modeSelect, { target: { value: 'SELF_PARTY_REP' } });
    expect(asterisk('Contact Name')).toBe(true);
    expect(asterisk('Contact Number')).toBe(true);

    // The gate entry number is required only for an Offline Return (required_when).
    fireEvent.click(screen.getByTestId('return-type-OFFLINE_RETURN'));
    expect(asterisk('Gate Entry Number')).toBe(true);
  });

  it('opens a summary sheet; Back keeps the form; Submit creates once with one key', async () => {
    route();
    await renderPage();
    await fillHeader();
    fireEvent.click(screen.getByRole('button', { name: 'Submit & Create GS' }));

    const sheet = await screen.findByRole('dialog', { name: 'Check before creating the GS' });
    const summary = within(sheet).getByTestId('gate-summary');
    const row = (label: string) =>
      within(summary).getByText(label, { selector: 'dt' }).nextElementSibling?.textContent;
    expect(row('Party')).toBe('New Party (new party)');
    expect(row('State')).toBe('Uttar Pradesh');
    expect(row('Station')).toBe('Agra');
    expect(row('Cartons')).toBe('3');
    expect(row('Received Through')).toBe('Courier');
    expect(row('Courier Name')).toBe('BlueDart');
    expect(row('Docket No.')).toBe('BD-1');
    expect(row('Documents From Party')).toBe('None');
    expect(row('Documents From Transport')).toBe('None');
    expect(createCalls()).toHaveLength(0); // nothing is created before Submit

    fireEvent.click(within(sheet).getByRole('button', { name: 'Back to edit' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>(/^Docket No\./).value).toBe('BD-1');
    expect(createCalls()).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Submit & Create GS' }));
    const again = await screen.findByRole('dialog', { name: 'Check before creating the GS' });
    const submit = within(again).getByRole('button', { name: 'Submit' });
    fireEvent.click(submit);
    fireEvent.click(submit); // double tap

    expect(await screen.findByTestId('created-gs-no')).toHaveTextContent('GS/2026-27/00042');
    expect(screen.getByRole('button', { name: /Print GS Tag/ })).toBeTruthy();
    const calls = createCalls();
    expect(calls.length).toBeGreaterThanOrEqual(1);
    const keys = new Set(calls.map(([, o]) => o?.idempotencyKey));
    expect(keys.size).toBe(1); // G-16: a replay can never create a second GS
    const body = calls[0]?.[1]?.body as {
      values: Record<string, unknown>;
      documents: unknown[];
      provisional_party: { name: string };
    };
    expect(body.values).toMatchObject({
      return_type: 'ECOMMERCE_RETURN',
      carton_count: 3,
      delivery_mode: 'COURIER_PARCEL',
      courier_name: 'BlueDart',
      docket_no: 'BD-1',
    });
    expect(body.documents).toEqual([]);
    expect(body.provisional_party.name).toBe('New Party');
  });

  it('needs a type and a file per document row; "No Documents From Party" replaces the rows', async () => {
    route();
    await renderPage();
    await fillHeader();
    fireEvent.click(screen.getByRole('button', { name: 'Add party document' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit & Create GS' }));
    expect(await screen.findByText('Choose the document type')).toBeTruthy();
    expect(screen.getByText('Attach a photo or PDF of the document')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();

    // The party type list offers the configured "No Documents From Party" choice.
    const party = screen.getByTestId('party-documents');
    fireEvent.change(within(party).getByLabelText(/^Document type/), {
      target: { value: 'NO_DOCUMENT' },
    });
    expect(within(party).queryByLabelText(/^Photo \/ PDF/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add party document' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Submit & Create GS' }));
    const sheet = await screen.findByRole('dialog', { name: 'Check before creating the GS' });
    expect(
      within(sheet).getByText('Documents From Party', { selector: 'dt' }).nextElementSibling
        ?.textContent,
    ).toBe('No Documents From Party');
    fireEvent.click(within(sheet).getByRole('button', { name: 'Submit' }));
    await screen.findByTestId('created-gs-no');
    const body = createCalls()[0]?.[1]?.body as {
      values: Record<string, unknown>;
      documents: unknown[];
    };
    expect(body.values.no_document).toBe(true);
    expect(body.documents).toEqual([]);
  });

  it('uploads files after Submit; a failed upload can be retried or removed', async () => {
    route([{ id: 'doc-p1' }, { id: 'doc-t1' }]);
    transferMode.fail = true;
    await renderPage();
    await fillHeader();
    fireEvent.click(screen.getByRole('button', { name: 'Add party document' }));
    const party = screen.getByTestId('party-documents');
    fireEvent.change(within(party).getByLabelText(/^Document type/), {
      target: { value: 'INVOICE' },
    });
    const invoice = new File(['x'], 'invoice.jpg', { type: 'image/jpeg' });
    fireEvent.change(within(party).getByLabelText(/^Photo \/ PDF/), {
      target: { files: [invoice] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add transport document' }));
    const transport = screen.getByTestId('transport-documents');
    fireEvent.change(within(transport).getByLabelText(/^Document type/), {
      target: { value: 'COURIER_SLIP' },
    });
    const slip = new File(['y'], 'slip.jpg', { type: 'image/jpeg' });
    fireEvent.change(within(transport).getByLabelText(/^Photo \/ PDF/), {
      target: { files: [slip] },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Submit & Create GS' }));
    const sheet = await screen.findByRole('dialog', { name: 'Check before creating the GS' });
    expect(
      within(sheet).getByText('Documents From Party', { selector: 'dt' }).nextElementSibling
        ?.textContent,
    ).toBe('1 (Invoice)');
    fireEvent.click(within(sheet).getByRole('button', { name: 'Submit' }));

    const failed = await screen.findByTestId('gate-upload-failed');
    expect(within(failed).getByText(/invoice\.jpg: Network down/)).toBeTruthy();
    const body = createCalls()[0]?.[1]?.body as { documents: unknown[] };
    expect(body.documents).toEqual([
      { doc_type_code: 'INVOICE', source: 'PARTY' },
      { doc_type_code: 'COURIER_SLIP', source: 'TRANSPORT' },
    ]);
    // Each file went to its own row's signed URL.
    const urls = apiRequestFn.mock.calls.map(([p]) => p).filter((p) => p.endsWith('upload-url'));
    expect(urls).toEqual([
      '/gs/gs-1/gate-documents/doc-p1/files/upload-url',
      '/gs/gs-1/gate-documents/doc-t1/files/upload-url',
    ]);

    // Retry one file (now succeeds), remove the other.
    transferMode.fail = false;
    fireEvent.click(within(failed).getByRole('button', { name: 'Retry invoice.jpg' }));
    await waitFor(() => {
      expect(screen.queryByText(/invoice\.jpg: Network down/)).toBeNull();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Remove slip.jpg' }));
    expect(screen.queryByTestId('gate-upload-failed')).toBeNull();
  });
});
