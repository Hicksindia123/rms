import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { canDownscale, MAX_EDGE_PX, scaledSize } from '@/features/unboxing/imageDownscale';
import type { UnboxingState } from '@/features/unboxing/api';

// Test-only API double: the screen renders the backend's authoritative checklist.
const stateFn = vi.fn<() => Promise<UnboxingState>>();
vi.mock('@/features/unboxing/api', () => ({
  unboxingApi: {
    state: () => stateFn(),
    downloadUrl: () => new Promise(() => undefined),
  },
}));
vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ me: { profile: { id: 'u-aman' } } }),
}));

// AMD-08: status / step labels come from the GS_STATUS configuration.
const LABELS: Record<string, string> = {
  UNBOXING: 'Carton Opening',
  ITEMIZATION: 'Counting',
  CATEGORISATION: 'Categorisation',
};
vi.mock('@/features/goods-slips/statusLabels', () => ({
  useStatusLabels: () => (code: string) => LABELS[code] ?? code,
}));

const { UnboxingPage } = await import('@/features/unboxing/UnboxingPage');

function state(over: Partial<UnboxingState['checklist']> = {}, missingDoc = false): UnboxingState {
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
      gate_document_code: missingDoc ? 'NO_DOCUMENT' : 'INVOICE',
      gate_document_label: missingDoc ? 'No Document Attached' : 'Invoice',
    },
    checklist: {
      video_ok: false,
      documents_ok: false,
      classified_ok: false,
      video_count: 0,
      doc_photo_count: 0,
      classified_doc_photo_count: 0,
      parcel_photo_count: 0,
      missing_documentation: missingDoc,
      exception_approved: false,
      video_per_box_required: false,
      carton_count: 2,
      cartons_with_video: 0,
      boxes_missing_video: [],
      missing: ['UNBOXING_VIDEO', 'CLASSIFIED_DOC_PHOTO'],
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
    permissions: { can_perform: true, can_approve_exception: false },
    gate_documents: [],
    document_types: [
      { code: 'INVOICE', label: 'Invoice', required_fields: ['doc_no', 'doc_date'] },
    ],
  };
}

afterEach(() => {
  stateFn.mockReset();
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

describe('UnboxingPage checklist (G-02)', () => {
  it('shows ✖ items and keeps Complete disabled while evidence is missing', async () => {
    stateFn.mockResolvedValue(state());
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const checklist = await screen.findByTestId('checklist');
    expect(checklist.textContent).toContain('Video ✖');
    expect(checklist.textContent).toContain('Documents ✖');
    expect(checklist.textContent).toContain('Classified ✖');
    expect(screen.getByRole('button', { name: 'Complete carton opening' })).toBeDisabled();
    expect(screen.getByTestId('missing-list').textContent).toContain('a video for every carton');
    expect(screen.getByTestId('record-video')).toBeInTheDocument();
  });

  it('enables Complete once the backend reports the checklist ready', async () => {
    stateFn.mockResolvedValue(
      state({
        video_ok: true,
        documents_ok: true,
        classified_ok: true,
        video_count: 1,
        doc_photo_count: 1,
        classified_doc_photo_count: 1,
        missing: [],
        ready: true,
      }),
    );
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Complete carton opening' })).toBeEnabled();
    });
    expect(screen.getByTestId('checklist').textContent).toContain('Video ✔');
  });

  it('enforces one video per carton with carton-wise progress (G-02, AMD-03)', async () => {
    stateFn.mockResolvedValue(
      state({
        video_ok: false,
        video_per_box_required: true,
        boxes_missing_video: [1, 2],
        missing: ['VIDEO_PER_CARTON'],
      }),
    );
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(
      await screen.findByRole('group', { name: 'Carton video coverage selector' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Carton 1 of 2')).toBeInTheDocument();
    expect(screen.getByText('Carton 2 of 2')).toBeInTheDocument();
    expect(screen.getByTestId('checklist').textContent).toContain('Carton videos 0 of 2');
    // AMD-04: documents found in the cartons can be added on the same screen.
    expect(screen.getByTestId('carton-document-form')).toBeInTheDocument();
    expect(screen.queryByText(/Whole consignment/i)).toBeNull();
    expect(screen.getByText(/Mandatory carton-wise videos/i)).toBeInTheDocument();
  });

  it('shows the DEC-03 parcel / exception flow for a GS without documents', async () => {
    stateFn.mockResolvedValue(
      state({ missing: ['UNBOXING_VIDEO', 'MISSING_DOC_EXCEPTION'] }, true),
    );
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByText(/Missing documents \(DEC-03\)/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Request Missing Document Exception' }),
    ).toBeDisabled();
    expect(screen.getByTestId('checklist').textContent).toContain('exception needed');
  });

  it('shows the error state with retry when the state cannot be loaded', async () => {
    const { ApiError } = await import('@/lib/api/client');
    stateFn.mockRejectedValue(new ApiError(403, 'GS_ACCESS_DENIED', 'No access', null, 'rid-9'));
    render(<UnboxingPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByText('No access')).toBeInTheDocument();
    expect(screen.getByText(/Request ID: rid-9/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });
});
