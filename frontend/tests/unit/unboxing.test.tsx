import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { canDownscale, MAX_EDGE_PX, scaledSize } from '@/features/unboxing/imageDownscale';
import type { UnboxingState } from '@/features/unboxing/api';
import type { GateDocument } from '@/features/goods-slips/api';

// Test-only API doubles: the screen renders the backend's authoritative checklist.
const stateFn = vi.fn<() => Promise<UnboxingState>>();
const completeFn = vi.fn();
const addCartonFn = vi.fn();
const uploadFilesFn = vi.fn();
vi.mock('@/features/unboxing/api', () => ({
  unboxingApi: {
    state: () => stateFn(),
    complete: (...args: unknown[]) => completeFn(...args) as unknown,
    addCartonDocument: (...args: unknown[]) => addCartonFn(...args) as unknown,
    downloadUrl: () => new Promise(() => undefined),
  },
}));
vi.mock('@/features/goods-slips/gateUploads', () => ({
  uploadDocumentFiles: (...args: unknown[]) => uploadFilesFn(...args) as unknown,
}));
vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ me: { profile: { id: 'u-aman' } } }),
}));

// AMD-08: status / step labels come from the GS_STATUS configuration.
const LABELS: Record<string, string> = {
  UNBOXING: 'Unboxing',
  ITEMIZATION: 'Counting',
};
vi.mock('@/features/goods-slips/statusLabels', () => ({
  useStatusLabels: () => (code: string) => LABELS[code] ?? code,
}));

const { UnboxingPage } = await import('@/features/unboxing/UnboxingPage');

function state(
  over: Partial<UnboxingState['checklist']> = {},
  extra: Partial<UnboxingState> = {},
  missingDoc = false,
): UnboxingState {
  return {
    goods_slip: {
      id: 'gs-1',
      gs_no: 'GS/2026-27/00001',
      status: 'UNBOXING',
      party_name: 'Demo Party',
      station_name: 'Agra',
      carton_count: 2,
      box_count: 2,
      missing_documentation: missingDoc,
      gate_document_code: null,
      gate_document_label: null,
    },
    checklist: {
      video_ok: false,
      video_count: 0,
      doc_photo_count: 0,
      classified_doc_photo_count: 0,
      parcel_photo_count: 0,
      missing_documentation: missingDoc,
      video_per_box_required: true,
      carton_count: 2,
      cartons_with_video: 0,
      boxes_missing_video: [1, 2],
      missing: ['UNBOXING_VIDEO', 'VIDEO_PER_CARTON'],
      ready: false,
      ...over,
    },
    attachments: [],
    documents: [],
    exceptions: [],
    form_version_id: 'fv-2',
    form_snapshot: { form_code: 'S1_UNBOXING', name: 'Unboxing', version_no: 2, fields: [] },
    limits: {
      max_video_bytes: 1073741824,
      max_document_bytes: 26214400,
      resumable_threshold_bytes: 6291456,
    },
    permissions: { can_perform: true },
    gate_documents: [],
    // Backend-shaped: active GATE_DOCUMENT types without NO_DOCUMENT (DEC-62).
    document_types: [
      { code: 'INVOICE', label: 'Invoice', required_fields: [] },
      { code: 'DEBIT_NOTE', label: 'GST Debit Note', required_fields: [] },
      { code: 'HANDWRITTEN_SLIP', label: 'Hand Written Slip', required_fields: [] },
    ],
    ...extra,
  };
}

const READY = {
  video_ok: true,
  video_count: 2,
  cartons_with_video: 2,
  boxes_missing_video: [],
  missing: [],
  ready: true,
};

function cartonDoc(): GateDocument {
  return {
    id: 'doc-c',
    doc_type_code: 'INVOICE',
    doc_type_label: 'Invoice',
    doc_no: null,
    doc_date: null,
    remarks: null,
    source_step: 'S1_UNBOX',
    doc_source: 'CARTON',
    accounts_alerted_at: '2026-11-20T10:00:00Z',
    files: [],
  };
}

afterEach(() => {
  stateFn.mockReset();
  completeFn.mockReset();
  addCartonFn.mockReset();
  uploadFilesFn.mockReset();
});

describe('image downscale', () => {
  it('caps the long edge and keeps the aspect ratio', () => {
    expect(scaledSize(4000, 3000)).toEqual({ width: MAX_EDGE_PX, height: 1920 });
    expect(scaledSize(1200, 1600)).toEqual({ width: 1200, height: 1600 });
  });
  it('only re-encodes JPEG / PNG (PDF and HEIC upload unchanged)', () => {
    expect(canDownscale('image/jpeg')).toBe(true);
    expect(canDownscale('image/png')).toBe(true);
    expect(canDownscale('image/heic')).toBe(false);
    expect(canDownscale('application/pdf')).toBe(false);
  });
});

describe('UnboxingPage (P3: G-02 = video per carton, DEC-63)', () => {
  it('keeps Next disabled until every carton has a video, with carton-wise progress', async () => {
    stateFn.mockResolvedValue(state());
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    const checklist = await screen.findByTestId('checklist');
    expect(checklist.textContent).toContain('Video ✖');
    expect(checklist.textContent).toContain('Carton videos 0 of 2');
    // DEC-63: no document / classification / exception requirement any more.
    expect(checklist.textContent).not.toContain('Classified');
    expect(checklist.textContent).toContain('optional');
    expect(screen.getByTestId('unboxing-next')).toBeDisabled();
    expect(screen.getByTestId('missing-list').textContent).toContain('carton 1, 2');
    expect(screen.getByText('Carton 1 of 2')).toBeInTheDocument();
    expect(screen.getByTestId('record-video')).toBeInTheDocument();
    // The old DOC_PHOTO picker is gone for new work.
    expect(screen.queryByTestId('doc-photo-file-input')).toBeNull();
  });

  it('enables Next with all videos and no document, and moves on to item addition', async () => {
    stateFn.mockResolvedValue(state(READY));
    completeFn.mockResolvedValue({ goods_slip: {}, task_ids: [], notified_user_count: 1 });
    const onNext = vi.fn();
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={onNext} />);
    const next = await screen.findByTestId('unboxing-next');
    await waitFor(() => {
      expect(next).toBeEnabled();
    });
    fireEvent.click(next);
    await waitFor(() => {
      expect(onNext).toHaveBeenCalledWith('gs-1');
    });
    expect(completeFn).toHaveBeenCalledWith('gs-1');
  });

  it('offers one typed carton document (type + photo, no number / date) also without party documents', async () => {
    stateFn.mockResolvedValue(state(READY, {}, true));
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    expect(await screen.findByTestId('no-party-documents')).toBeInTheDocument();
    const form = screen.getByTestId('carton-document-form');
    expect(form).toBeInTheDocument();
    expect(screen.queryByLabelText(/Document no/i)).toBeNull();
    expect(screen.queryByLabelText(/Document date/i)).toBeNull();
    expect(screen.queryByLabelText(/Remarks/i)).toBeNull();
    expect(screen.queryByText(/Missing Document Exception/)).toBeNull();
    const options = Array.from(
      screen.getByLabelText<HTMLSelectElement>(/Document type/).options,
    ).map((o) => o.textContent);
    expect(options).toEqual(
      expect.arrayContaining(['Invoice', 'GST Debit Note', 'Hand Written Slip']),
    );
    expect(options.some((o) => o.includes('No Documents'))).toBe(false);
    expect(screen.getByTestId('carton-doc-camera-input')).toHaveAttribute('capture', 'environment');
    const save = screen.getByRole('button', { name: /Save document/ });
    expect(save).toBeDisabled();
  });

  it('saves the type first, then uploads the photo to the new row', async () => {
    stateFn.mockResolvedValue(state(READY));
    addCartonFn.mockResolvedValue(cartonDoc());
    uploadFilesFn.mockResolvedValue([]);
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    const select = await screen.findByLabelText<HTMLSelectElement>(/Document type/);
    fireEvent.change(select, { target: { value: 'INVOICE' } });
    const file = new File(['x'], 'invoice.heic', { type: 'image/heic' });
    fireEvent.change(screen.getByTestId('carton-doc-file-input'), { target: { files: [file] } });
    const save = screen.getByRole('button', { name: /Save document/ });
    await waitFor(() => {
      expect(save).toBeEnabled();
    });
    fireEvent.click(save);
    await waitFor(() => {
      expect(uploadFilesFn).toHaveBeenCalled();
    });
    expect(addCartonFn).toHaveBeenCalledWith(
      'gs-1',
      { doc_type_code: 'INVOICE' },
      expect.any(String),
    );
    const [, items] = uploadFilesFn.mock.calls[0] as [string, Array<{ documentId: string }>];
    expect(items[0]?.documentId).toBe('doc-c');
  });

  it('shows the saved carton document instead of a second form', async () => {
    stateFn.mockResolvedValue(state(READY, { gate_documents: [cartonDoc()] }));
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    expect(await screen.findByTestId('carton-document')).toBeInTheDocument();
    expect(screen.queryByTestId('carton-document-form')).toBeNull();
    expect(screen.getByTestId('checklist').textContent).toContain('added');
  });

  it('lists a retired Missing Document Exception read-only (no decision buttons)', async () => {
    stateFn.mockResolvedValue(
      state(READY, {
        exceptions: [
          {
            id: 'e1',
            gs_id: 'gs-1',
            gs_no: 'GS/2026-27/00001',
            party_name: 'Demo Party',
            parcel_attachment_id: 'p1',
            parcel_mime_type: 'image/jpeg',
            parcel_preview_unsupported: false,
            remark: 'No invoice in parcel',
            status: 'REQUESTED',
            requested_by_name: 'Aman',
            requested_at: '2026-11-19T10:00:00Z',
            decided_by_name: null,
            decided_at: null,
            decision_remarks: null,
          },
        ],
      }),
    );
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    expect(await screen.findByTestId('exception-history')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve|Reject|Request/ })).toBeNull();
    expect(screen.getByTestId('unboxing-next')).toBeEnabled();
  });

  it('shows the error state with retry when the state cannot be loaded', async () => {
    const { ApiError } = await import('@/lib/api/client');
    stateFn.mockRejectedValue(new ApiError(403, 'GS_ACCESS_DENIED', 'No access', null, 'rid-9'));
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} onNext={vi.fn()} />);
    expect(await screen.findByText('No access')).toBeInTheDocument();
    expect(screen.getByText(/Request ID: rid-9/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });
});
