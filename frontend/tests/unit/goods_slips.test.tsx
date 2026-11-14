import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { parseHash } from '@/app/router';
import { DataView, DynamicForm } from '@/components/erp';
import type { BackendFormSnapshot } from '@/features/goods-slips/api';
import { age, humanize } from '@/features/goods-slips/format';
import { defaultValues, optionOf, toDynamicFormSnapshot } from '@/features/goods-slips/snapshot';

const SNAPSHOT: BackendFormSnapshot = {
  form_code: 'S1_GATE_INWARD',
  name: 'Gate Inward & GS Creation',
  version_no: 1,
  fields: [
    {
      field_key: 'delivery_mode',
      label: 'Delivery Mode / Transporter',
      control_type: 'dropdown',
      is_required: true,
      sort_order: 50,
      section: 'Delivery Details',
      option_items: [
        { code: 'COURIER_PARCEL', label: 'Courier / Parcel', sort_order: 10, is_active: true },
        { code: 'RETIRED', label: 'Retired', sort_order: 99, is_active: false },
      ],
    },
    {
      field_key: 'rep_contact',
      label: 'Representative Contact No.',
      control_type: 'text',
      is_required: false,
      sort_order: 110,
      required_when: { field: 'delivery_mode', op: 'eq', value: 'SELF_PARTY_REP' },
      visible_when: { field: 'delivery_mode', op: 'eq', value: 'SELF_PARTY_REP' },
    },
    {
      field_key: 'accompanying_doc',
      label: 'Accompanying Document at Gate',
      control_type: 'dropdown',
      is_required: true,
      sort_order: 120,
      option_items: [
        {
          code: 'NO_DOCUMENT',
          label: 'No Document Attached',
          allowed_status: 'CONDITIONAL',
          rule_text: 'Flag consignment as missing documentation',
          sort_order: 50,
        },
      ],
    },
    {
      field_key: 'gs_creation_format',
      label: 'GS Creation Format',
      control_type: 'dropdown',
      is_required: true,
      sort_order: 170,
      default_value: 'AUTO_STANDARD',
      option_items: [{ code: 'AUTO_STANDARD', label: 'Auto-Generated', sort_order: 10 }],
    },
  ],
};

describe('goods slip form snapshot mapping', () => {
  it('maps backend snapshot fields to DynamicForm fields, dropping inactive options', () => {
    const form = toDynamicFormSnapshot(SNAPSHOT, { rep_contact: { regex: '^[6-9][0-9]{9}$' } });
    expect(form.version).toBe(1);
    const mode = form.fields.find((f) => f.field_key === 'delivery_mode');
    expect(mode?.required).toBe(true);
    expect(mode?.options?.map((o) => o.code)).toEqual(['COURIER_PARCEL']);
    const contact = form.fields.find((f) => f.field_key === 'rep_contact');
    expect(contact?.validation?.regex).toBe('^[6-9][0-9]{9}$');
    expect(contact?.required_when).toEqual({
      field: 'delivery_mode',
      op: 'eq',
      value: 'SELF_PARTY_REP',
    });
  });

  it('takes defaults (AUTO_STANDARD) and option texts from config', () => {
    expect(defaultValues(SNAPSHOT)).toEqual({ gs_creation_format: 'AUTO_STANDARD' });
    expect(optionOf(SNAPSHOT, 'accompanying_doc', 'NO_DOCUMENT')?.label).toBe(
      'No Document Attached',
    );
  });

  it('renders custom field renderers and server errors in DynamicForm', () => {
    const form = toDynamicFormSnapshot(SNAPSHOT);
    render(
      <DynamicForm
        formSnapshot={form}
        onSubmit={vi.fn()}
        fieldRenderers={{
          delivery_mode: (_f, api) => (
            <button
              type="button"
              onClick={() => {
                api.onChange('COURIER_PARCEL');
              }}
            >
              custom picker
            </button>
          ),
        }}
        serverErrors={{ accompanying_doc: ['Accompanying Document at Gate is required'] }}
      />,
    );
    expect(screen.getByRole('button', { name: 'custom picker' })).toBeInTheDocument();
    expect(screen.getByText('Accompanying Document at Gate is required')).toBeInTheDocument();
  });
});

describe('DataView', () => {
  const rows = [{ id: '1', gs_no: 'GS/2026-27/00001' }];
  const columns = [{ key: 'gs', header: 'GS No.', render: (r: { gs_no: string }) => r.gs_no }];

  it('renders both the desktop table and the mobile cards', () => {
    const onClick = vi.fn();
    render(
      <DataView
        rows={rows}
        rowKey={(r) => r.id}
        columns={columns}
        renderCard={(r) => <span>card {r.gs_no}</span>}
        onRowClick={onClick}
        rowLabel={(r) => `Open ${r.gs_no}`}
        emptyTitle="Nothing"
      />,
    );
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('card GS/2026-27/00001')).toBeInTheDocument();
    const [, cardButton] = screen.getAllByRole('button', { name: 'Open GS/2026-27/00001' });
    if (!cardButton) throw new Error('card button missing');
    fireEvent.click(cardButton);
    expect(onClick).toHaveBeenCalledWith(rows[0]);
  });

  it('shows empty and error states (with request id and retry)', () => {
    const retry = vi.fn();
    const { rerender } = render(
      <DataView
        rows={[]}
        rowKey={() => 'x'}
        columns={columns}
        renderCard={() => null}
        emptyTitle="No goods slips yet"
      />,
    );
    expect(screen.getByText('No goods slips yet')).toBeInTheDocument();
    rerender(
      <DataView
        rows={null}
        rowKey={() => 'x'}
        columns={columns}
        renderCard={() => null}
        emptyTitle="x"
        error={{ message: 'Boom', code: 'INTERNAL_ERROR', requestId: 'req-123' }}
        onRetry={retry}
      />,
    );
    expect(screen.getByText(/Request ID: req-123/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
    expect(retry).toHaveBeenCalled();
  });
});

describe('helpers', () => {
  it('parses hash routes', () => {
    expect(parseHash('#/gs/abc/tag')).toEqual(['gs', 'abc', 'tag']);
    expect(parseHash('')).toEqual([]);
    expect(parseHash('#/gs?x=1')).toEqual(['gs']);
  });

  it('humanizes codes and formats age', () => {
    expect(humanize('GATE_CREATED')).toBe('Gate created');
    const now = Date.parse('2026-11-03T10:00:00Z');
    expect(age('2026-11-03T09:30:00Z', now)).toBe('30m');
    expect(age('2026-11-02T10:00:00Z', now)).toBe('24h');
    expect(age('2026-10-30T10:00:00Z', now)).toBe('4d');
  });
});

describe('All India States & Stations for Gate Entry', () => {
  it('contains all 36 States and Union Territories of India', async () => {
    const { ALL_INDIA_STATES } = await import('@/features/goods-slips/indiaData');
    expect(ALL_INDIA_STATES.length).toBe(36);

    const names = ALL_INDIA_STATES.map((s) => s.name);
    // Key sample states and UTs
    expect(names).toContain('Uttar Pradesh');
    expect(names).toContain('Maharashtra');
    expect(names).toContain('Delhi');
    expect(names).toContain('Karnataka');
    expect(names).toContain('Tamil Nadu');
    expect(names).toContain('Gujarat');
    expect(names).toContain('West Bengal');
    expect(names).toContain('Rajasthan');
    expect(names).toContain('Kerala');
    expect(names).toContain('Chandigarh');
    expect(names).toContain('Ladakh');
  });

  it('resolves stations for selected states', async () => {
    const { getStationsForState } = await import('@/features/goods-slips/indiaData');

    const upStations = getStationsForState('Uttar Pradesh').map((s) => s.name);
    expect(upStations).toContain('Agra');
    expect(upStations).toContain('Lucknow');
    expect(upStations).toContain('Kanpur Nagar');
    expect(upStations).toContain('Varanasi');
    expect(upStations).toContain('Prayagraj (Allahabad)');

    const mhStations = getStationsForState('Maharashtra').map((s) => s.name);
    expect(mhStations).toContain('Mumbai City');
    expect(mhStations).toContain('Pune');
    expect(mhStations).toContain('Nagpur');

    const dlStations = getStationsForState('Delhi').map((s) => s.name);
    expect(dlStations).toContain('New Delhi');
    expect(dlStations).toContain('Connaught Place');

    const gjStations = getStationsForState('Gujarat').map((s) => s.name);
    expect(gjStations).toContain('Ahmedabad');
    expect(gjStations).toContain('Surat');
    expect(gjStations).toContain('Vadodara');
  });

  it('provides all 75+ cities/districts for Uttar Pradesh without omission', async () => {
    const { getStationsForState } = await import('@/features/goods-slips/indiaData');
    const upStations = getStationsForState('Uttar Pradesh');
    expect(upStations.length).toBeGreaterThanOrEqual(75);
    const names = upStations.map((s) => s.name);
    expect(names).toContain('Agra');
    expect(names).toContain('Aligarh');
    expect(names).toContain('Ayodhya');
    expect(names).toContain('Bareilly');
    expect(names).toContain('Ghaziabad');
    expect(names).toContain('Gorakhpur');
    expect(names).toContain('Hathras');
    expect(names).toContain('Jhansi');
    expect(names).toContain('Kanpur Nagar');
    expect(names).toContain('Lucknow');
    expect(names).toContain('Mathura');
    expect(names).toContain('Meerut');
    expect(names).toContain('Moradabad');
    expect(names).toContain('Gautam Buddha Nagar (Noida / Greater Noida)');
    expect(names).toContain('Prayagraj (Allahabad)');
    expect(names).toContain('Varanasi');
  });

  it('useStations hook retains all 75+ stations when merging with API results', async () => {
    const { renderHook, act } = await import('@testing-library/react');
    const { useStations } = await import('@/features/goods-slips/useStations');
    const { gsApi } = await import('@/features/goods-slips/api');

    const upStateUuid = 'd7cb9192-0000-0000-0000-000000000001';
    const statesList = [{ id: upStateUuid, name: 'Uttar Pradesh', code: 'UP' }];

    // Mock API returning only 2 old seed rows
    const apiSpy = vi.spyOn(gsApi, 'stations').mockResolvedValue([
      { id: 'uuid-hathras', name: 'Hathras' },
      { id: 'uuid-agra', name: 'Agra' },
    ]);

    const { result } = renderHook(() => useStations(statesList));

    await act(async () => {
      result.current.load(upStateUuid);
      // Wait for async API call to resolve
      await Promise.resolve();
    });

    const stations = result.current.get(upStateUuid);
    expect(stations.length).toBeGreaterThanOrEqual(75);
    const stationNames = stations.map((s) => s.name);
    // Verified: Both existing API items and all static cities are present
    expect(stationNames).toContain('Agra');
    expect(stationNames).toContain('Hathras');
    expect(stationNames).toContain('Lucknow');
    expect(stationNames).toContain('Kanpur Nagar');
    expect(stationNames).toContain('Varanasi');
    expect(stationNames).toContain('Aligarh');
    expect(stationNames).toContain('Ghaziabad');

    // And matched API item has the real DB uuid
    const agraItem = stations.find((s) => s.name === 'Agra');
    expect(agraItem?.id).toBe('uuid-agra');

    apiSpy.mockRestore();
  });

  // Change plan 2026-11-12 Phase 2 (AMD-04): document rows replace the single gate document.
  describe('Gate document rows (AMD-04)', () => {
    const TYPES = [
      { code: 'INVOICE', label: 'Invoice', required_fields: ['doc_no', 'doc_date'] as const },
      { code: 'COURIER_SLIP', label: 'Courier Slip', required_fields: [] as const },
    ].map((t) => ({ ...t, required_fields: [...t.required_fields] }));

    it('adds, edits and removes rows; required marks and API errors come from config / server', async () => {
      const { GateDocumentsEditor } = await import('@/features/goods-slips/GateDocumentsEditor');
      const { newDocDraft } = await import('@/features/goods-slips/gateDocs');
      const onChange = vi.fn();
      const row = { ...newDocDraft(), doc_type_code: 'INVOICE' };
      const { rerender } = render(
        <GateDocumentsEditor
          types={TYPES}
          rows={[row]}
          onChange={onChange}
          errors={{ 'documents.0.doc_no': ['Document No. is required for Invoice'] }}
          maxDate="2026-11-13"
          disabled={false}
        />,
      );
      expect(screen.getByText('Document no. *')).toBeInTheDocument();
      expect(screen.getByText('Document No. is required for Invoice')).toBeInTheDocument();
      expect(screen.getByLabelText('Document date *')).toHaveAttribute('max', '2026-11-13');

      fireEvent.click(screen.getByRole('button', { name: /Add document/ }));
      expect(onChange).toHaveBeenLastCalledWith([
        row,
        expect.objectContaining({ doc_type_code: '' }),
      ]);

      fireEvent.change(screen.getByLabelText('Document no. *'), { target: { value: 'INV-9' } });
      expect(onChange).toHaveBeenLastCalledWith([{ ...row, doc_no: 'INV-9' }]);

      fireEvent.click(screen.getByRole('button', { name: 'Remove document 1' }));
      expect(onChange).toHaveBeenLastCalledWith([]);

      // A courier slip requires nothing beyond its type.
      rerender(
        <GateDocumentsEditor
          types={TYPES}
          rows={[{ ...row, doc_type_code: 'COURIER_SLIP' }]}
          onChange={onChange}
          errors={undefined}
          maxDate="2026-11-13"
          disabled={false}
        />,
      );
      expect(screen.getByText('Document no.')).toBeInTheDocument();
    });

    it('maps drafts to the API payload (trimmed, empty as null)', async () => {
      const { newDocDraft, toDocumentInputs } = await import('@/features/goods-slips/gateDocs');
      const draft = { ...newDocDraft(), doc_type_code: 'COURIER_SLIP', doc_no: ' AWB-1 ' };
      expect(toDocumentInputs([draft])).toEqual([
        { doc_type_code: 'COURIER_SLIP', doc_no: 'AWB-1', doc_date: null, remarks: null },
      ]);
    });

    it('adds the legacy document image field only to v1 forms', () => {
      const v1 = toDynamicFormSnapshot(SNAPSHOT);
      expect(v1.fields.some((f) => f.field_key === 'gate_doc_image')).toBe(true);
      const v2 = toDynamicFormSnapshot({
        ...SNAPSHOT,
        version_no: 2,
        fields: SNAPSHOT.fields.filter((f) => f.field_key !== 'accompanying_doc'),
      });
      expect(v2.fields.some((f) => f.field_key === 'gate_doc_image')).toBe(false);
    });
  });
});
