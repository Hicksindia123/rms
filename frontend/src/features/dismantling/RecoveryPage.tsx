import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  Barcode,
  CheckCircle,
  Cpu,
  Layers,
  Minus,
  Plus,
  RefreshCw,
  Trash2,
  Wrench,
} from 'lucide-react';
import {
  Badge,
  Button,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
  Textarea,
} from '@/components/ui';
import { dismantlingApi } from './api';
import type {
  DismantleBatchDetail,
  PartTypeCode,
  PcbModel,
  PcbSupplier,
  StorageContainer,
} from './types';

interface RecoveryPageProps {
  batchId: string;
  onBack: () => void;
  onCompleted: () => void;
}

const PART_TYPES: Array<{
  type: PartTypeCode;
  title: string;
  desc: string;
  color: string;
}> = [
  {
    type: 'TIP',
    title: 'Tip Component',
    desc: 'Outer probe tip assembly',
    color: 'border-blue-400 bg-blue-50/50',
  },
  {
    type: 'BODY',
    title: 'Casing / Body',
    desc: 'Plastic / metal housing frame',
    color: 'border-emerald-400 bg-emerald-50/50',
  },
  {
    type: 'WIRE',
    title: 'Wire & Connector',
    desc: 'Internal / external wiring harness',
    color: 'border-amber-400 bg-amber-50/50',
  },
  {
    type: 'PCB',
    title: 'PCB Module',
    desc: 'Circuit board & electronics',
    color: 'border-purple-400 bg-purple-50/50',
  },
];

export function RecoveryPage({ batchId, onBack, onCompleted }: RecoveryPageProps) {
  const [batch, setBatch] = useState<DismantleBatchDetail | null>(null);
  const [containers, setContainers] = useState<StorageContainer[]>([]);
  const [pcbModels, setPcbModels] = useState<PcbModel[]>([]);
  const [pcbSuppliers, setPcbSuppliers] = useState<PcbSupplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Recovery form state
  const [unitsDismantled, setUnitsDismantled] = useState<number>(1);
  const [partQuantities, setPartQuantities] = useState<Record<PartTypeCode, number>>({
    TIP: 0,
    BODY: 0,
    WIRE: 0,
    PCB: 0,
  });
  const [storageAssignments, setStorageAssignments] = useState<
    Record<PartTypeCode, { container_id?: string; partition_id?: string }>
  >({
    TIP: {},
    BODY: {},
    WIRE: {},
    PCB: {},
  });

  // PCB specifics (G-11)
  const [selectedPcbModel, setSelectedPcbModel] = useState<string>('');
  const [selectedPcbSupplier, setSelectedPcbSupplier] = useState<string>('');

  // Scrap specifics
  const [scrapPieces, setScrapPieces] = useState<number>(0);
  const [scrapWeight, setScrapWeight] = useState<string>('');
  const [scrapHazardous, setScrapHazardous] = useState<boolean>(false);
  const [scrapRemarks, setScrapRemarks] = useState<string>('');

  // Submitting & Modals
  const [submitting, setSubmitting] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [showAddSupplierModal, setShowAddSupplierModal] = useState(false);
  const [newSupplierName, setNewSupplierName] = useState('');
  const [showAddModelModal, setShowAddModelModal] = useState(false);
  const [newModelName, setNewModelName] = useState('');
  const [modalError, setModalError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [batchRes, contRes, modelsRes, suppliersRes] = await Promise.all([
        dismantlingApi.getBatch(batchId),
        dismantlingApi.listContainers(),
        dismantlingApi.listPcbModels(),
        dismantlingApi.listPcbSuppliers(),
      ]);
      setBatch(batchRes);
      setContainers(contRes);
      setPcbModels(modelsRes);
      setPcbSuppliers(suppliersRes);

      const remaining = batchRes.total_input_qty - batchRes.total_dismantled_qty;
      setUnitsDismantled(Math.max(1, remaining));
      setPartQuantities({
        TIP: remaining,
        BODY: remaining,
        WIRE: remaining,
        PCB: remaining,
      });

      const initStorage: Record<PartTypeCode, { container_id?: string; partition_id?: string }> = {
        TIP: {},
        BODY: {},
        WIRE: {},
        PCB: {},
      };

      if (batchRes.storage_method_code === 'DEDICATED_CONTAINERS') {
        for (const p of PART_TYPES) {
          const match = contRes.find(
            (c) => c.storage_method === 'DEDICATED_CONTAINERS' && c.dedicated_part_type === p.type,
          );
          if (match) initStorage[p.type] = { container_id: match.id };
        }
      } else {
        const partitionedCont = contRes.find((c) => c.storage_method === 'PARTITIONED_CONTAINER');
        if (partitionedCont) {
          for (const p of PART_TYPES) {
            const part = partitionedCont.partitions.find((cp) => cp.part_type === p.type);
            if (part)
              initStorage[p.type] = { partition_id: part.id, container_id: partitionedCont.id };
          }
        }
      }
      setStorageAssignments(initStorage);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load batch data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const [batchRes, contRes, modelsRes, suppliersRes] = await Promise.all([
          dismantlingApi.getBatch(batchId),
          dismantlingApi.listContainers(),
          dismantlingApi.listPcbModels(),
          dismantlingApi.listPcbSuppliers(),
        ]);
        setBatch(batchRes);
        setContainers(contRes);
        setPcbModels(modelsRes);
        setPcbSuppliers(suppliersRes);

        const remaining = batchRes.total_input_qty - batchRes.total_dismantled_qty;
        setUnitsDismantled(Math.max(1, remaining));
        setPartQuantities({
          TIP: remaining,
          BODY: remaining,
          WIRE: remaining,
          PCB: remaining,
        });

        const initStorage: Record<PartTypeCode, { container_id?: string; partition_id?: string }> =
          {
            TIP: {},
            BODY: {},
            WIRE: {},
            PCB: {},
          };

        if (batchRes.storage_method_code === 'DEDICATED_CONTAINERS') {
          for (const p of PART_TYPES) {
            const match = contRes.find(
              (c) =>
                c.storage_method === 'DEDICATED_CONTAINERS' && c.dedicated_part_type === p.type,
            );
            if (match) initStorage[p.type] = { container_id: match.id };
          }
        } else {
          const partitionedCont = contRes.find((c) => c.storage_method === 'PARTITIONED_CONTAINER');
          if (partitionedCont) {
            for (const p of PART_TYPES) {
              const part = partitionedCont.partitions.find((cp) => cp.part_type === p.type);
              if (part)
                initStorage[p.type] = { partition_id: part.id, container_id: partitionedCont.id };
            }
          }
        }
        setStorageAssignments(initStorage);
        setLoading(false);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load batch data');
        setLoading(false);
      }
    })();
  }, [batchId]);

  const remainingBatchUnits = batch ? batch.total_input_qty - batch.total_dismantled_qty : 0;

  const handlePcbModelChange = (modelId: string) => {
    setSelectedPcbModel(modelId);
    const mod = pcbModels.find((m) => m.id === modelId);
    if (mod?.supplier_id) {
      setSelectedPcbSupplier(mod.supplier_id);
    }
  };

  const handleAddSupplier = async () => {
    if (!newSupplierName.trim()) return;
    setModalError(null);
    try {
      const created = await dismantlingApi.createPcbSupplier({ name: newSupplierName.trim() });
      setPcbSuppliers((prev) => [...prev, created]);
      setSelectedPcbSupplier(created.id);
      setShowAddSupplierModal(false);
      setNewSupplierName('');
    } catch (err: unknown) {
      setModalError(
        err instanceof Error
          ? err.message
          : 'Could not add supplier. Masters permissions required or contact admin.',
      );
    }
  };

  const handleAddModel = async () => {
    if (!newModelName.trim() || !selectedPcbSupplier) return;
    setModalError(null);
    try {
      const created = await dismantlingApi.createPcbModel({
        name: newModelName.trim(),
        supplier_id: selectedPcbSupplier,
      });
      setPcbModels((prev) => [...prev, created]);
      setSelectedPcbModel(created.id);
      setShowAddModelModal(false);
      setNewModelName('');
    } catch (err: unknown) {
      setModalError(
        err instanceof Error
          ? err.message
          : 'Could not add model. Masters permissions required or contact admin.',
      );
    }
  };

  const validateBeforeConfirm = (): string | null => {
    if (!batch) return 'Batch not loaded';
    if (unitsDismantled < 1 || unitsDismantled > remainingBatchUnits) {
      return `Units dismantled must be between 1 and ${String(remainingBatchUnits)}`;
    }

    // Check G-11 for PCB
    if (partQuantities.PCB > 0) {
      if (!selectedPcbModel) return 'PCB Model is required';
      if (!selectedPcbSupplier) return 'PCB Supplier is required';
    }

    // Check storage assignments
    for (const p of PART_TYPES) {
      const qty = partQuantities[p.type];
      const storage = storageAssignments[p.type];
      if (qty > 0) {
        if (batch.storage_method_code === 'DEDICATED_CONTAINERS' && !storage.container_id) {
          return `Please select a dedicated container for ${p.type}`;
        }
        if (batch.storage_method_code === 'PARTITIONED_CONTAINER' && !storage.partition_id) {
          return `Please select a container partition for ${p.type}`;
        }
      }
    }

    return null;
  };

  const handleSubmitRecovery = async () => {
    if (!batch) return;
    const valError = validateBeforeConfirm();
    if (valError) {
      setError(valError);
      setShowConfirmModal(false);
      return;
    }

    setSubmitting(true);
    setError(null);

    const partsPayload = PART_TYPES.map((p) => ({
      part_type: p.type,
      qty: partQuantities[p.type],
      pcb_model_id: p.type === 'PCB' && partQuantities.PCB > 0 ? selectedPcbModel : null,
      pcb_supplier_id: p.type === 'PCB' && partQuantities.PCB > 0 ? selectedPcbSupplier : null,
      container_id: storageAssignments[p.type].container_id ?? null,
      partition_id: storageAssignments[p.type].partition_id ?? null,
    }));

    const scrapPayload = {
      qty_pieces: scrapPieces,
      weight_kg: scrapWeight ? parseFloat(scrapWeight) : null,
      hazardous: scrapHazardous,
      remarks: scrapRemarks.trim() || null,
    };

    const idemKey = `recover-${batch.id}-${String(Date.now())}-${Math.random().toString(36).slice(2, 8)}`;

    try {
      await dismantlingApi.recoverBatch(
        batch.id,
        {
          units_dismantled: unitsDismantled,
          parts: partsPayload,
          scrap: scrapPayload,
        },
        idemKey,
      );
      setShowConfirmModal(false);
      onCompleted();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to record parts recovery');
      setShowConfirmModal(false);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <LoadingState label="Loading recovery workspace..." />;
  }

  if (!batch) {
    return <ErrorState error={{ message: 'Dismantle batch not found' }} onRetry={onBack} />;
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto p-4 sm:p-6 pb-24">
      {/* Top Header */}
      <div className="flex items-center justify-between border-b border-slate-200 pb-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors min-h-[44px]"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Queue
        </button>
        <div className="flex items-center gap-2">
          <Badge variant={batch.status === 'COMPLETED' ? 'success' : 'warning'}>
            {batch.status}
          </Badge>
          <span className="font-mono font-bold text-sm text-slate-800">{batch.batch_no}</span>
        </div>
      </div>

      {error && (
        <ErrorState
          error={{ message: error }}
          onRetry={() => {
            void loadData();
          }}
        />
      )}

      {/* Reconciliation Card (DEC-19) */}
      <div className="p-4 bg-white border border-slate-200 rounded-xl shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Layers className="w-5 h-5 text-indigo-600" />
              Units Dismantling Progress
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Storage:{' '}
              <span className="font-semibold text-slate-700">{batch.storage_method_code}</span> |
              Technician:{' '}
              <span className="font-semibold text-slate-700">{batch.technician_name}</span>
            </p>
          </div>
          <div className="text-right">
            <span className="text-xs text-slate-500">Total Progress:</span>
            <div className="font-mono font-extrabold text-indigo-600 text-lg">
              {batch.total_dismantled_qty} / {batch.total_input_qty} Units
            </div>
          </div>
        </div>

        {/* Stepper for units to dismantle in this recovery */}
        <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <label className="text-xs font-bold text-slate-800">
              Units Dismantled in This Session
            </label>
            <p className="text-xs text-slate-500">
              {remainingBatchUnits} input unit(s) remaining in this batch
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={unitsDismantled <= 1}
              onClick={() => {
                setUnitsDismantled((prev) => Math.max(1, prev - 1));
              }}
              className="w-10 h-10 rounded-lg border border-slate-300 bg-white flex items-center justify-center text-slate-700 hover:bg-slate-100 disabled:opacity-40 min-h-[44px] min-w-[44px]"
            >
              <Minus className="w-4 h-4" />
            </button>
            <input
              type="number"
              aria-label="Units dismantled in this session"
              min={1}
              max={remainingBatchUnits}
              value={unitsDismantled}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                if (!isNaN(val)) {
                  setUnitsDismantled(Math.max(1, Math.min(remainingBatchUnits, val)));
                }
              }}
              className="w-16 h-10 text-center font-mono font-bold text-base border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
            />
            <button
              type="button"
              disabled={unitsDismantled >= remainingBatchUnits}
              onClick={() => {
                setUnitsDismantled((prev) => Math.min(remainingBatchUnits, prev + 1));
              }}
              className="w-10 h-10 rounded-lg border border-slate-300 bg-white flex items-center justify-center text-slate-700 hover:bg-slate-100 disabled:opacity-40 min-h-[44px] min-w-[44px]"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Four Part-Type Cards (DEC-19 Free Quantities) */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Wrench className="w-5 h-5 text-indigo-600" />
            Recovered Spare Parts (Free 0..n yield)
          </h3>
          <span className="text-xs text-slate-500">Recorded into Spare Parts Store</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {PART_TYPES.map((part) => {
            const qty = partQuantities[part.type];
            const isPcb = part.type === 'PCB';

            const isDedicated = batch.storage_method_code === 'DEDICATED_CONTAINERS';
            const relevantContainers = containers.filter(
              (c) =>
                c.storage_method === 'DEDICATED_CONTAINERS' && c.dedicated_part_type === part.type,
            );
            const allPartitions = containers
              .flatMap((c) => (c.storage_method === 'PARTITIONED_CONTAINER' ? c.partitions : []))
              .filter((cp) => cp.part_type === part.type);

            return (
              <div
                key={part.type}
                className={`p-4 rounded-xl border-2 transition-all shadow-sm ${part.color} space-y-3`}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <span className="font-mono font-bold text-xs uppercase px-2 py-0.5 rounded bg-white/80 border border-slate-300 text-slate-800">
                      {part.type}
                    </span>
                    <h4 className="font-bold text-slate-900 mt-1">{part.title}</h4>
                    <p className="text-xs text-slate-600">{part.desc}</p>
                  </div>

                  {/* Quantity Stepper */}
                  <div className="flex items-center gap-1.5 bg-white p-1 rounded-lg border border-slate-200">
                    <button
                      type="button"
                      disabled={qty <= 0}
                      onClick={() => {
                        setPartQuantities((prev) => ({
                          ...prev,
                          [part.type]: Math.max(0, prev[part.type] - 1),
                        }));
                      }}
                      className="w-8 h-8 rounded flex items-center justify-center text-slate-600 hover:bg-slate-100 disabled:opacity-30 min-h-[44px] min-w-[44px]"
                    >
                      <Minus className="w-4 h-4" />
                    </button>
                    <input
                      type="number"
                      aria-label={`${part.title} quantity`}
                      min={0}
                      value={qty}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        setPartQuantities((prev) => ({
                          ...prev,
                          [part.type]: Math.max(0, isNaN(val) ? 0 : val),
                        }));
                      }}
                      className="w-12 text-center font-mono font-bold text-sm border-none focus:ring-0 p-0"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        setPartQuantities((prev) => ({
                          ...prev,
                          [part.type]: prev[part.type] + 1,
                        }));
                      }}
                      className="w-8 h-8 rounded flex items-center justify-center text-slate-600 hover:bg-slate-100 min-h-[44px] min-w-[44px]"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Storage Target Selector */}
                {qty > 0 && (
                  <div className="pt-2 border-t border-slate-200/80 space-y-2">
                    <label className="text-xs font-semibold text-slate-800 flex items-center gap-1">
                      <Barcode className="w-3.5 h-3.5 text-slate-500" />
                      {isDedicated ? 'Dedicated Container' : 'Partition Compartment'}
                    </label>

                    {isDedicated ? (
                      <Select
                        aria-label={`Storage for ${part.type}`}
                        value={storageAssignments[part.type].container_id ?? ''}
                        onChange={(e) => {
                          setStorageAssignments((prev) => ({
                            ...prev,
                            [part.type]: { ...prev[part.type], container_id: e.target.value },
                          }));
                        }}
                        placeholder="-- Select Dedicated Container --"
                        options={relevantContainers.map((c) => ({
                          value: c.id,
                          label: `${c.code} (${c.name ?? c.barcode})`,
                        }))}
                      />
                    ) : (
                      <Select
                        aria-label={`Storage for ${part.type}`}
                        value={storageAssignments[part.type].partition_id ?? ''}
                        onChange={(e) => {
                          setStorageAssignments((prev) => ({
                            ...prev,
                            [part.type]: { ...prev[part.type], partition_id: e.target.value },
                          }));
                        }}
                        placeholder="-- Select Compartment Partition --"
                        options={allPartitions.map((p) => ({
                          value: p.id,
                          label: `Compartment ${p.compartment_code} (${part.type})`,
                        }))}
                      />
                    )}
                  </div>
                )}

                {/* PCB Model and Supplier Expandable Section (G-11) */}
                {isPcb && qty > 0 && (
                  <div className="pt-3 border-t border-purple-200 bg-purple-100/50 -mx-4 -mb-4 p-4 rounded-b-xl space-y-3">
                    <div className="flex items-center gap-1.5 text-xs font-bold text-purple-900">
                      <Cpu className="w-4 h-4 text-purple-700" />
                      PCB Mandatory Details
                    </div>

                    {/* PCB Model */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-semibold text-purple-950">PCB Model *</label>
                        <button
                          type="button"
                          onClick={() => {
                            setShowAddModelModal(true);
                          }}
                          className="text-[11px] font-bold text-purple-700 hover:text-purple-900 underline"
                        >
                          + New Model
                        </button>
                      </div>
                      <Select
                        aria-label="PCB Model"
                        value={selectedPcbModel}
                        onChange={(e) => {
                          handlePcbModelChange(e.target.value);
                        }}
                        placeholder="-- Select PCB Model --"
                        options={pcbModels.map((m) => ({
                          value: m.id,
                          label: m.supplier_name ? `${m.name} (${m.supplier_name})` : m.name,
                        }))}
                      />
                    </div>

                    {/* PCB Supplier */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-semibold text-purple-950">
                          PCB Supplier *
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            setShowAddSupplierModal(true);
                          }}
                          className="text-[11px] font-bold text-purple-700 hover:text-purple-900 underline"
                        >
                          + New Supplier
                        </button>
                      </div>
                      <Select
                        aria-label="PCB Supplier"
                        value={selectedPcbSupplier}
                        onChange={(e) => {
                          setSelectedPcbSupplier(e.target.value);
                        }}
                        placeholder="-- Select PCB Supplier --"
                        options={pcbSuppliers.map((s) => ({
                          value: s.id,
                          label: s.name,
                        }))}
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Scrap Section */}
      <div className="p-5 bg-white border border-slate-200 rounded-xl shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Trash2 className="w-5 h-5 text-slate-600" />
            Dismantling Scrap & Waste
          </h3>
          <span className="text-xs text-slate-500">Marked for Disposal Register</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Scrap Pieces Count
            </label>
            <Input
              type="number"
              min={0}
              value={scrapPieces}
              onChange={(e) => {
                setScrapPieces(Math.max(0, parseInt(e.target.value, 10) || 0));
              }}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Weight in Kg (Optional)
            </label>
            <Input
              type="number"
              step="0.001"
              min={0}
              placeholder="e.g. 0.250"
              value={scrapWeight}
              onChange={(e) => {
                setScrapWeight(e.target.value);
              }}
            />
          </div>
        </div>

        {/* Hazardous Toggle */}
        <div className="p-4 rounded-lg border border-slate-200 bg-slate-50 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="hazardous-scrap"
                checked={scrapHazardous}
                onChange={(e) => {
                  setScrapHazardous(e.target.checked);
                }}
                className="w-5 h-5 text-red-600 rounded border-slate-300 focus:ring-red-500 cursor-pointer min-h-[44px] min-w-[44px]"
              />
              <label
                htmlFor="hazardous-scrap"
                className="text-sm font-bold text-slate-900 cursor-pointer"
              >
                Mark as Hazardous Scrap
              </label>
            </div>
            {scrapHazardous && (
              <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-red-100 text-red-800">
                HAZARDOUS
              </span>
            )}
          </div>

          {scrapHazardous && (
            <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 p-2.5 rounded border border-red-200">
              <AlertTriangle className="w-4 h-4 shrink-0 text-red-600 mt-0.5" />
              <span>
                Hazardous scrap cannot be disposed without an official manifest reference (
                <code className="font-mono">manifest_ref</code>) from authorized waste agencies.
              </span>
            </div>
          )}
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Scrap Remarks / Reason
          </label>
          <Textarea
            rows={2}
            placeholder="e.g. Broken casing, crushed PCB traces, oxidization"
            value={scrapRemarks}
            onChange={(e) => {
              setScrapRemarks(e.target.value);
            }}
          />
        </div>
      </div>

      {/* Bottom Sticky Action Bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 p-4 shadow-lg flex items-center justify-between max-w-4xl mx-auto z-10">
        <div>
          <div className="text-xs text-slate-500">Dismantling:</div>
          <div className="font-bold text-sm text-slate-900">
            {unitsDismantled} Unit(s) &rarr;{' '}
            {Object.values(partQuantities).reduce((a, b) => a + b, 0)} Recovered Parts
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" onClick={onBack} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              const err = validateBeforeConfirm();
              if (err) {
                setError(err);
                return;
              }
              setShowConfirmModal(true);
            }}
            disabled={submitting}
            className="flex items-center gap-2 px-5 py-2.5"
          >
            <CheckCircle className="w-4 h-4" />
            Review & Confirm
          </Button>
        </div>
      </div>

      {/* Confirmation Modal */}
      <Modal
        isOpen={showConfirmModal}
        onClose={() => {
          setShowConfirmModal(false);
        }}
        title="Confirm Parts Recovery"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            You are recording the recovery of parts from <strong>{unitsDismantled}</strong>{' '}
            dismantled unit(s). This will add salvaged stock to the{' '}
            <strong>Spare Parts Store</strong>.
          </p>

          <div className="border border-slate-200 rounded-lg p-3 bg-slate-50 text-xs space-y-2">
            <div className="font-bold text-slate-800 border-b border-slate-200 pb-1">
              Recovered Parts Summary:
            </div>
            {PART_TYPES.map((p) => (
              <div key={p.type} className="flex justify-between items-center">
                <span className="font-semibold text-slate-700">{p.type}:</span>
                <span className="font-mono font-bold text-slate-900">
                  {String(partQuantities[p.type])} pcs
                  {p.type === 'PCB' && partQuantities.PCB > 0 && selectedPcbModel && (
                    <span className="text-[11px] font-normal text-purple-700 ml-1">
                      ({pcbModels.find((m) => m.id === selectedPcbModel)?.name})
                    </span>
                  )}
                </span>
              </div>
            ))}
            {(scrapPieces > 0 || scrapWeight) && (
              <div className="pt-2 border-t border-slate-200 flex justify-between items-center text-slate-700">
                <span className="font-semibold">Scrap:</span>
                <span className="font-mono font-bold text-red-700">
                  {String(scrapPieces)} pcs {scrapWeight ? `(${scrapWeight} kg)` : ''}
                  {scrapHazardous ? ' [HAZARDOUS]' : ''}
                </span>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setShowConfirmModal(false);
              }}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                void handleSubmitRecovery();
              }}
              disabled={submitting}
              className="flex items-center gap-2"
            >
              {submitting ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Recording...
                </>
              ) : (
                <>
                  <CheckCircle className="w-4 h-4" />
                  Confirm Recovery
                </>
              )}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Add PCB Supplier Modal */}
      <Modal
        isOpen={showAddSupplierModal}
        onClose={() => {
          setShowAddSupplierModal(false);
        }}
        title="Add PCB Supplier"
      >
        <div className="space-y-4">
          {modalError && (
            <div className="text-xs text-red-600 bg-red-50 p-2 rounded">{modalError}</div>
          )}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Supplier Name *
            </label>
            <Input
              value={newSupplierName}
              onChange={(e) => {
                setNewSupplierName(e.target.value);
              }}
              placeholder="e.g. Apex Electronics Ltd"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setShowAddSupplierModal(false);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                void handleAddSupplier();
              }}
            >
              Add Supplier
            </Button>
          </div>
        </div>
      </Modal>

      {/* Add PCB Model Modal */}
      <Modal
        isOpen={showAddModelModal}
        onClose={() => {
          setShowAddModelModal(false);
        }}
        title="Add PCB Model"
      >
        <div className="space-y-4">
          {modalError && (
            <div className="text-xs text-red-600 bg-red-50 p-2 rounded">{modalError}</div>
          )}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Model Code / Name *
            </label>
            <Input
              value={newModelName}
              onChange={(e) => {
                setNewModelName(e.target.value);
              }}
              placeholder="e.g. DMT-PCB-PRO-V3"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Supplier *</label>
            <Select
              value={selectedPcbSupplier}
              onChange={(e) => {
                setSelectedPcbSupplier(e.target.value);
              }}
              options={[
                { value: '', label: '-- Select Supplier --' },
                ...pcbSuppliers.map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setShowAddModelModal(false);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                void handleAddModel();
              }}
            >
              Add Model
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
