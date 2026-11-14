import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { dismantlingApi } from '@/features/dismantling/api';
import { DismantlingQueuePage } from '@/features/dismantling/DismantlingQueuePage';
import { RecoveryPage } from '@/features/dismantling/RecoveryPage';
import { ScrapRegisterPage } from '@/features/dismantling/ScrapRegisterPage';
import type {
  DismantleBatchDetail,
  DismantleBatchSummary,
  DismantleQueueResponse,
  PcbModel,
  PcbSupplier,
  ScrapRecord,
  StorageContainer,
} from '@/features/dismantling/types';

vi.mock('@/features/dismantling/api');

const mockQueue: DismantleQueueResponse = {
  dismantleable_lots: [
    {
      lot_id: 'lot-dmt-1',
      stock_item_id: 'item-1',
      gs_no: 'GS/2026-27/00001',
      product_name: 'Digital Thermometer DMT',
      product_sku: 'DMT-01',
      category_code: 'THERMOMETER',
      category_name: 'Thermometer',
      supports_dismantling: true,
      condition_class: 'NON_GOOD',
      qty: 5,
      requires_evaluation: false,
    },
  ],
  disposal_required_lots: [
    {
      lot_id: 'lot-eo-1',
      stock_item_id: 'item-2',
      gs_no: 'GS/2026-27/00002',
      product_name: 'Enclosed Oval Unit',
      product_sku: 'EO-01',
      category_code: 'ENCLOSED_OVAL',
      category_name: 'Enclosed Oval',
      supports_dismantling: false,
      condition_class: 'NON_GOOD',
      qty: 3,
      requires_evaluation: false,
    },
  ],
  total_dismantleable_qty: 5,
  total_disposal_required_qty: 3,
};

const mockBatchSummary: DismantleBatchSummary = {
  id: 'batch-1',
  batch_no: 'DM/2026-27/00001',
  technician_profile_id: 'tech-1',
  technician_name: 'Spare Parts Technician',
  storage_method_code: 'PARTITIONED_CONTAINER',
  status: 'OPEN',
  total_input_qty: 5,
  total_dismantled_qty: 0,
  created_at: '2026-11-04T12:00:00Z',
  completed_at: null,
};

const mockContainers: StorageContainer[] = [
  {
    id: 'cont-part-1',
    code: 'PART-BIN-01',
    barcode: 'BC-PART-01',
    name: 'Partitioned Bin 01',
    container_type: 'PARTITIONED',
    storage_method: 'PARTITIONED_CONTAINER',
    dedicated_part_type: null,
    is_active: true,
    partitions: [
      {
        id: 'part-tip',
        container_id: 'cont-part-1',
        compartment_code: 'A1',
        part_type: 'TIP',
        is_active: true,
      },
      {
        id: 'part-body',
        container_id: 'cont-part-1',
        compartment_code: 'A2',
        part_type: 'BODY',
        is_active: true,
      },
      {
        id: 'part-wire',
        container_id: 'cont-part-1',
        compartment_code: 'A3',
        part_type: 'WIRE',
        is_active: true,
      },
      {
        id: 'part-pcb',
        container_id: 'cont-part-1',
        compartment_code: 'A4',
        part_type: 'PCB',
        is_active: true,
      },
    ],
  },
];

const mockPcbModels: PcbModel[] = [
  { id: 'pcb-mod-1', name: 'DMT V2.0 Mainboard', supplier_id: null, is_active: true },
];

const mockPcbSuppliers: PcbSupplier[] = [
  { id: 'pcb-sup-1', name: 'Shenzhen Micro Electronics', is_active: true },
];

const mockBatchDetail: DismantleBatchDetail = {
  ...mockBatchSummary,
  inputs: [
    {
      id: 'input-1',
      batch_id: 'batch-1',
      lot_id: 'lot-dmt-1',
      qty: 5,
      product_name: 'Digital Thermometer DMT',
      created_at: '2026-11-04T12:00:00Z',
    },
  ],
  recovered_parts: [],
  scrap_records: [],
};

const mockScrapRecords: ScrapRecord[] = [
  {
    id: 'scrap-1',
    batch_id: 'batch-1',
    batch_no: 'DM/2026-27/00001',
    qty_pieces: 2,
    weight_kg: 0.25,
    hazardous: true,
    disposal_status: 'MARKED',
    manifest_ref: null,
    remarks: 'Cracked plastic with residue',
    created_at: '2026-11-04T12:30:00Z',
  },
  {
    id: 'scrap-2',
    batch_id: 'batch-1',
    batch_no: 'DM/2026-27/00001',
    qty_pieces: 1,
    weight_kg: 0.1,
    hazardous: false,
    disposal_status: 'DISPOSED',
    manifest_ref: 'MNF-2026-001',
    remarks: 'Packaging remnants',
    created_at: '2026-11-04T11:00:00Z',
    disposed_at: '2026-11-04T12:00:00Z',
    disposed_by_name: 'Spare Parts Manager',
  },
];

describe('DismantlingQueuePage', () => {
  const onRecover = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dismantlingApi.getQueue).mockResolvedValue(mockQueue);
    vi.mocked(dismantlingApi.listBatches).mockResolvedValue([mockBatchSummary]);
    vi.mocked(dismantlingApi.createBatch).mockResolvedValue(mockBatchDetail);
  });

  it('renders DMT candidate lots and highlights non-dismantling items with DEC-18 warning', async () => {
    render(<DismantlingQueuePage onRecover={onRecover} />);

    expect(await screen.findByText('Digital Thermometer DMT')).toBeInTheDocument();

    // Verify DEC-18 Disposal route required banner
    expect(screen.getByText(/Disposal route required \(DEC-18\)/i)).toBeInTheDocument();
    expect(screen.getByText('Enclosed Oval Unit')).toBeInTheDocument();
  });

  it('creates a dismantling batch when lots are selected and storage method is chosen', async () => {
    render(<DismantlingQueuePage onRecover={onRecover} />);
    await screen.findByText('Digital Thermometer DMT');

    // Select the checkbox for DMT lot
    const checkboxes = screen.getAllByRole('checkbox');
    const firstCheckbox = checkboxes[0];
    expect(firstCheckbox).toBeDefined();
    if (!firstCheckbox) throw new Error('Checkbox not found');
    fireEvent.click(firstCheckbox);

    // Choose storage method
    const select = screen.getByDisplayValue(/Partitioned Container/i);
    expect(select).toBeInTheDocument();

    // Click Allot Dismantle Batch button
    const startBtn = screen.getByRole('button', { name: /Allot Dismantle Batch/i });
    expect(startBtn).not.toBeDisabled();
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(dismantlingApi.createBatch).toHaveBeenCalledWith(
        {
          inputs: [{ lot_id: 'lot-dmt-1', qty: 5 }],
          storage_method_code: 'PARTITIONED_CONTAINER',
        },
        expect.any(String),
      );
    });
  });
});

describe('RecoveryPage', () => {
  const onBack = vi.fn();
  const onCompleted = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dismantlingApi.getBatch).mockResolvedValue(mockBatchDetail);
    vi.mocked(dismantlingApi.listContainers).mockResolvedValue(mockContainers);
    vi.mocked(dismantlingApi.listPcbModels).mockResolvedValue(mockPcbModels);
    vi.mocked(dismantlingApi.listPcbSuppliers).mockResolvedValue(mockPcbSuppliers);
    vi.mocked(dismantlingApi.recoverBatch).mockResolvedValue({
      ...mockBatchDetail,
      status: 'COMPLETED',
      total_dismantled_qty: 5,
    });
  });

  it('renders four part cards (TIP, BODY, WIRE, PCB) and enforces G-11 PCB model & supplier', async () => {
    render(<RecoveryPage batchId="batch-1" onBack={onBack} onCompleted={onCompleted} />);

    expect(await screen.findByText('Units Dismantling Progress')).toBeInTheDocument();
    expect(screen.getByText('DM/2026-27/00001')).toBeInTheDocument();

    // Verify 4 part cards exist
    expect(screen.getByText('Tip Component')).toBeInTheDocument();
    expect(screen.getByText('Casing / Body')).toBeInTheDocument();
    expect(screen.getByText('Wire & Connector')).toBeInTheDocument();
    expect(screen.getByText('PCB Module')).toBeInTheDocument();

    // Set PCB quantity to 1 using aria-label input
    const pcbQtyInput = screen.getByLabelText('PCB Module quantity');
    fireEvent.change(pcbQtyInput, { target: { value: '1' } });

    // Wait for PCB G-11 expandable section to appear in DOM
    expect(await screen.findByText(/PCB Mandatory Details \(G-11 Guard\)/i)).toBeInTheDocument();

    // Try reviewing without selecting PCB model or supplier
    const reviewBtn = screen.getByRole('button', { name: /Review & Confirm/i });
    fireEvent.click(reviewBtn);

    // G-11 validation message should appear and API should NOT be called
    expect(await screen.findByText(/G-11: PCB Model is required/i)).toBeInTheDocument();
    expect(dismantlingApi.recoverBatch).not.toHaveBeenCalled();

    // Now select PCB Model
    const modelSelect = screen.getByLabelText('PCB Model');
    fireEvent.change(modelSelect, { target: { value: 'pcb-mod-1' } });
    await waitFor(() => {
      expect(modelSelect).toHaveValue('pcb-mod-1');
    });

    // Try reviewing again -> supplier is missing
    fireEvent.click(reviewBtn);
    expect(await screen.findByText(/G-11: PCB Supplier is required/i)).toBeInTheDocument();
    expect(dismantlingApi.recoverBatch).not.toHaveBeenCalled();

    // Select PCB Supplier
    const supplierSelect = screen.getByLabelText('PCB Supplier');
    fireEvent.change(supplierSelect, { target: { value: 'pcb-sup-1' } });
    await waitFor(() => {
      expect(supplierSelect).toHaveValue('pcb-sup-1');
    });

    // Set partition for PCB to empty to test partition validation
    const partitionSelect = screen.getByLabelText('Storage for PCB');
    fireEvent.change(partitionSelect, { target: { value: '' } });
    await waitFor(() => {
      expect(partitionSelect).toHaveValue('');
    });

    // Try reviewing again -> partition is missing for PCB
    fireEvent.click(reviewBtn);
    expect(
      await screen.findByText(/Please select a container partition for PCB/i),
    ).toBeInTheDocument();

    // Select Partition for PCB
    fireEvent.change(partitionSelect, { target: { value: 'part-pcb' } });
    await waitFor(() => {
      expect(partitionSelect).toHaveValue('part-pcb');
    });

    // Review & Confirm -> Modal should open
    fireEvent.click(reviewBtn);
    expect(await screen.findByText('Confirm Parts Recovery')).toBeInTheDocument();

    // Click Confirm Recovery in the modal
    const confirmBtn = screen.getByRole('button', { name: /Confirm Recovery/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(dismantlingApi.recoverBatch).toHaveBeenCalled();
    });
    const calls = vi.mocked(dismantlingApi.recoverBatch).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const firstCall = calls[0];
    if (!firstCall) throw new Error('Expected recoverBatch call');
    const [calledBatchId, payload] = firstCall;
    expect(calledBatchId).toBe('batch-1');
    expect(payload.units_dismantled).toBe(5);
    const pcbPart = payload.parts.find((p) => p.part_type === 'PCB');
    expect(pcbPart).toEqual(
      expect.objectContaining({
        part_type: 'PCB',
        qty: 1,
        pcb_model_id: 'pcb-mod-1',
        pcb_supplier_id: 'pcb-sup-1',
        partition_id: 'part-pcb',
      }),
    );
  });

  it('displays hazardous scrap toggle and shows hazardous warning', async () => {
    render(<RecoveryPage batchId="batch-1" onBack={onBack} onCompleted={onCompleted} />);
    await screen.findByText('Units Dismantling Progress');

    const hazToggle = screen.getByRole('checkbox', { name: /Mark as Hazardous Scrap/i });
    expect(hazToggle).not.toBeChecked();
    fireEvent.click(hazToggle);
    expect(hazToggle).toBeChecked();

    // Warning banner should appear for hazardous scrap (DEC-11)
    expect(screen.getByText(/DEC-11 Enforced:/i)).toBeInTheDocument();
  });
});

describe('ScrapRegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dismantlingApi.listScrap).mockResolvedValue(mockScrapRecords);
    vi.mocked(dismantlingApi.disposeScrap).mockResolvedValue({
      id: 'scrap-1',
      batch_id: 'batch-1',
      batch_no: 'DM/2026-27/00001',
      qty_pieces: 2,
      hazardous: true,
      disposal_status: 'DISPOSED',
      manifest_ref: 'MNF-NEW-123',
      disposed_at: '2026-11-04T14:00:00Z',
      created_at: '2026-11-04T12:30:00Z',
    });
  });

  it('renders scrap items and enforces manifest reference for hazardous disposal (DEC-11)', async () => {
    render(<ScrapRegisterPage />);

    expect(
      await screen.findByText(/Scrap & Safe Disposal Register \(DEC-11\)/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Cracked plastic with residue')).toBeInTheDocument();

    // Click Dispose for hazardous item (exact button name "Dispose")
    const disposeBtn = screen.getByRole('button', { name: /^Dispose$/i });
    fireEvent.click(disposeBtn);

    // Dialog opens with DEC-11 note
    expect(await screen.findByText(/DEC-11 Compliance Requirement/i)).toBeInTheDocument();

    // Confirm Disposal button should be disabled when manifest is empty
    const confirmBtn = screen.getByRole('button', { name: /Confirm Disposal/i });
    expect(confirmBtn).toBeDisabled();

    // Enter manifest reference
    const manifestInput = screen.getByPlaceholderText(/e\.g\. HAZ-MAN-2026-9042/i);
    fireEvent.change(manifestInput, { target: { value: 'MNF-NEW-123' } });

    // Now button is enabled
    expect(confirmBtn).not.toBeDisabled();
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(dismantlingApi.disposeScrap).toHaveBeenCalledWith(
        'scrap-1',
        {
          manifest_ref: 'MNF-NEW-123',
        },
        expect.any(String),
      );
    });
  });
});
