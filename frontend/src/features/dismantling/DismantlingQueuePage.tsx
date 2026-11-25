import { useEffect, useState } from 'react';
import { AlertTriangle, Boxes, CheckCircle, Layers, Plus, RefreshCw, Wrench } from 'lucide-react';
import { Badge, Button, ErrorState, LoadingState, Select } from '@/components/ui';
import { dismantlingApi } from './api';
import type { DismantleBatchSummary, DismantleQueueItem, StorageMethodCode } from './types';

interface DismantlingQueuePageProps {
  onRecover: (batchId: string) => void;
}

export function DismantlingQueuePage({ onRecover }: DismantlingQueuePageProps) {
  const [activeTab, setActiveTab] = useState<'queue' | 'batches'>('queue');
  const [dismantleableLots, setDismantleableLots] = useState<DismantleQueueItem[]>([]);
  const [disposalLots, setDisposalLots] = useState<DismantleQueueItem[]>([]);
  const [batches, setBatches] = useState<DismantleBatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Batch creation state
  const [selectedLots, setSelectedLots] = useState<Record<string, number>>({});
  const [storageMethod, setStorageMethod] = useState<StorageMethodCode>('PARTITIONED_CONTAINER');
  const [creatingBatch, setCreatingBatch] = useState(false);
  const [createSuccess, setCreateSuccess] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [queueRes, batchesRes] = await Promise.all([
        dismantlingApi.getQueue(),
        dismantlingApi.listBatches({ page_size: 50 }),
      ]);
      setDismantleableLots(queueRes.dismantleable_lots);
      setDisposalLots(queueRes.disposal_required_lots);
      setBatches(batchesRes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load dismantling data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const [queueRes, batchesRes] = await Promise.all([
          dismantlingApi.getQueue(),
          dismantlingApi.listBatches({ page_size: 50 }),
        ]);
        setDismantleableLots(queueRes.dismantleable_lots);
        setDisposalLots(queueRes.disposal_required_lots);
        setBatches(batchesRes);
        setLoading(false);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load dismantling data');
        setLoading(false);
      }
    })();
  }, []);

  const toggleLotSelection = (lot: DismantleQueueItem) => {
    setSelectedLots((prev) => {
      if (prev[lot.lot_id] !== undefined) {
        return Object.fromEntries(Object.entries(prev).filter(([k]) => k !== lot.lot_id));
      }
      return { ...prev, [lot.lot_id]: lot.qty };
    });
  };

  const updateLotQty = (lotId: string, maxQty: number, val: number) => {
    const clamped = Math.max(1, Math.min(maxQty, Math.floor(val) || 1));
    setSelectedLots((prev) => ({
      ...prev,
      [lotId]: clamped,
    }));
  };

  const handleCreateBatch = async () => {
    const lotEntries = Object.entries(selectedLots);
    if (lotEntries.length === 0) return;

    setCreatingBatch(true);
    setError(null);
    setCreateSuccess(null);

    const inputs = lotEntries.map(([lot_id, qty]) => ({ lot_id, qty }));
    const idemKey = `dismantle-batch-${String(Date.now())}-${Math.random().toString(36).slice(2, 8)}`;

    try {
      const created = await dismantlingApi.createBatch(
        {
          inputs,
          storage_method_code: storageMethod,
        },
        idemKey,
      );
      setCreateSuccess(
        `Batch ${created.batch_no} created successfully with ${String(created.total_input_qty)} units!`,
      );
      setSelectedLots({});
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create dismantling batch');
    } finally {
      setCreatingBatch(false);
    }
  };

  const totalSelectedUnits = Object.values(selectedLots).reduce((sum, q) => sum + q, 0);

  if (loading && dismantleableLots.length === 0 && batches.length === 0) {
    return <LoadingState label="Loading dismantling queue..." />;
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <Wrench className="w-6 h-6 text-indigo-600" />
            Stage-4: Dismantling & Parts Recovery
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Dismantle non-good DMT units into TIP, BODY, WIRE, PCB.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void loadData();
            }}
            disabled={loading}
            className="flex items-center gap-1.5"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200 gap-4">
        <button
          type="button"
          onClick={() => {
            setActiveTab('queue');
          }}
          // Rule h: 44 px touch target (P3-04 E2E finding).
          style={{ minHeight: 44 }}
          className={`pb-2 px-1 text-sm font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'queue'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Boxes className="w-4 h-4" />
          Dismantling Queue ({dismantleableLots.length})
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveTab('batches');
          }}
          // Rule h: 44 px touch target (P3-04 E2E finding).
          style={{ minHeight: 44 }}
          className={`pb-2 px-1 text-sm font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'batches'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          Dismantling Batches ({batches.length})
        </button>
      </div>

      {error && (
        <ErrorState
          error={{ message: error }}
          onRetry={() => {
            void loadData();
          }}
        />
      )}

      {createSuccess && (
        <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-emerald-600" />
            <span>{createSuccess}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setCreateSuccess(null);
            }}
            className="text-emerald-700 hover:text-emerald-900 font-bold"
          >
            &times;
          </button>
        </div>
      )}

      {/* TAB 1: Queue */}
      {activeTab === 'queue' && (
        <div className="space-y-6">
          {/* Disposal Route Required Banner (DEC-18) */}
          {disposalLots.length > 0 && (
            <div className="p-4 rounded-lg bg-amber-50 border border-amber-300 space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-semibold text-amber-900">Disposal route required</h3>
                  <p className="text-xs text-amber-800 mt-1">
                    The following {disposalLots.length} lot(s) are non-good units from categories
                    that do NOT support dismantling (e.g. Prismatic, Enclosed Oval). They are
                    excluded from the dismantling queue and must follow separate
                    hazardous/quarantine scrap disposal.
                  </p>
                </div>
              </div>
              <div className="overflow-x-auto border border-amber-200 rounded-md bg-white">
                <table className="w-full text-left text-xs">
                  <thead className="bg-amber-100 text-amber-900 font-semibold border-b border-amber-200">
                    <tr>
                      <th className="p-2">Product</th>
                      <th className="p-2">Category</th>
                      <th className="p-2">Condition</th>
                      <th className="p-2 text-right">Available Qty</th>
                      <th className="p-2">GS No</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-amber-100 text-slate-700">
                    {disposalLots.map((lot) => (
                      <tr key={lot.lot_id} className="hover:bg-amber-50/50">
                        <td className="p-2 font-medium text-slate-900">
                          {lot.product_name ?? 'Unknown'}
                        </td>
                        <td className="p-2">
                          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
                            {lot.category_code ?? 'NON-DMT'}
                          </span>
                        </td>
                        <td className="p-2">{lot.condition_class}</td>
                        <td className="p-2 text-right font-mono font-bold text-amber-950">
                          {lot.qty}
                        </td>
                        <td className="p-2 font-mono text-slate-500">{lot.gs_no ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Dismantleable Lots Section */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Table of Available Lots */}
            <div className="lg:col-span-2 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-slate-900">
                  Non-Good DMT Units (In Non-Functional Store)
                </h2>
                <span className="text-xs text-slate-500">
                  {dismantleableLots.length} lot(s) available
                </span>
              </div>

              {dismantleableLots.length === 0 ? (
                <div className="p-8 text-center border-2 border-dashed border-slate-200 rounded-lg text-slate-500 text-sm">
                  No DMT non-good units currently waiting in Non-Functional Store.
                </div>
              ) : (
                <div className="border border-slate-200 rounded-lg overflow-x-auto bg-white shadow-sm">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200 text-xs uppercase tracking-wider">
                      <tr>
                        <th className="p-3 w-10 text-center">Select</th>
                        <th className="p-3">Product</th>
                        <th className="p-3">Condition</th>
                        <th className="p-3 text-right">Available</th>
                        <th className="p-3 w-28 text-right">Batch Qty</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      {dismantleableLots.map((lot) => {
                        const isSelected = selectedLots[lot.lot_id] !== undefined;
                        const qtyVal = selectedLots[lot.lot_id] ?? lot.qty;

                        return (
                          <tr
                            key={lot.lot_id}
                            className={`transition-colors ${
                              isSelected ? 'bg-indigo-50/60' : 'hover:bg-slate-50'
                            }`}
                          >
                            <td className="p-3 text-center">
                              {/* Rule h: labelled checkbox with a 44 px touch target (P3-08). */}
                              <label
                                className="inline-flex items-center justify-center cursor-pointer"
                                style={{ minWidth: 44, minHeight: 44 }}
                              >
                                <input
                                  type="checkbox"
                                  aria-label={`Select ${lot.gs_no ?? 'lot'} ${lot.product_name ?? ''}`.trim()}
                                  checked={isSelected}
                                  onChange={() => {
                                    toggleLotSelection(lot);
                                  }}
                                  className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500 cursor-pointer"
                                />
                              </label>
                            </td>
                            <td className="p-3">
                              <div className="font-medium text-slate-900">
                                {lot.product_name ?? 'DMT Model'}
                              </div>
                              <div className="text-xs text-slate-500 font-mono">
                                Lot: {lot.lot_id.slice(0, 8)} | GS: {lot.gs_no ?? '—'}
                              </div>
                            </td>
                            <td className="p-3">
                              <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                                {lot.condition_class}
                              </span>
                            </td>
                            <td className="p-3 text-right font-mono font-bold text-slate-900">
                              {lot.qty}
                            </td>
                            <td className="p-3 text-right">
                              {isSelected ? (
                                <input
                                  type="number"
                                  min={1}
                                  max={lot.qty}
                                  value={qtyVal}
                                  onChange={(e) => {
                                    updateLotQty(lot.lot_id, lot.qty, parseInt(e.target.value, 10));
                                  }}
                                  className="w-20 px-2 py-1 text-right text-sm border border-indigo-400 rounded focus:ring-2 focus:ring-indigo-500 font-mono font-bold"
                                />
                              ) : (
                                <span className="text-slate-400 text-xs">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Batch Creation Sidebar */}
            <div className="space-y-4">
              <div className="p-5 bg-white border border-slate-200 rounded-lg shadow-sm space-y-4">
                <h3 className="text-base font-semibold text-slate-900 flex items-center gap-2">
                  <Plus className="w-4 h-4 text-indigo-600" />
                  Create Dismantling Batch
                </h3>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      Storage Method
                    </label>
                    <Select
                      value={storageMethod}
                      onChange={(e) => {
                        setStorageMethod(e.target.value as StorageMethodCode);
                      }}
                      options={[
                        {
                          value: 'PARTITIONED_CONTAINER',
                          label: 'Partitioned Container (Multi-Bin)',
                        },
                        {
                          value: 'DEDICATED_CONTAINERS',
                          label: 'Dedicated Containers (Per Part Type)',
                        },
                      ]}
                    />
                    <p className="text-xs text-slate-500 mt-1">
                      {storageMethod === 'PARTITIONED_CONTAINER'
                        ? 'Parts will be stored in designated compartments of a partitioned bin.'
                        : 'Parts will be stored in individual dedicated bins for TIP, BODY, WIRE, PCB.'}
                    </p>
                  </div>

                  <div className="p-3 bg-slate-50 rounded border border-slate-200 text-xs space-y-1">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Selected Lots:</span>
                      <span className="font-semibold text-slate-800">
                        {Object.keys(selectedLots).length}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Total Units to Dismantle:</span>
                      <span className="font-mono font-bold text-indigo-600 text-sm">
                        {totalSelectedUnits}
                      </span>
                    </div>
                  </div>

                  <Button
                    type="button"
                    variant="primary"
                    disabled={totalSelectedUnits === 0 || creatingBatch}
                    onClick={() => {
                      void handleCreateBatch();
                    }}
                    className="w-full flex items-center justify-center gap-2"
                  >
                    {creatingBatch ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Creating Batch...
                      </>
                    ) : (
                      <>
                        <Boxes className="w-4 h-4" />
                        Allot Dismantle Batch
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: Batches */}
      {activeTab === 'batches' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Dismantling Batches Register</h2>
            <span className="text-xs text-slate-500">{batches.length} batch(es)</span>
          </div>

          {batches.length === 0 ? (
            <div className="p-8 text-center border-2 border-dashed border-slate-200 rounded-lg text-slate-500 text-sm">
              No dismantling batches found. Create one from the queue.
            </div>
          ) : (
            <div className="border border-slate-200 rounded-lg overflow-x-auto bg-white shadow-sm">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200 text-xs uppercase tracking-wider">
                  <tr>
                    <th className="p-3">Batch No</th>
                    <th className="p-3">Technician</th>
                    <th className="p-3">Storage Method</th>
                    <th className="p-3">Status</th>
                    <th className="p-3 text-center">Progress</th>
                    <th className="p-3 text-right">Created At</th>
                    <th className="p-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {batches.map((b) => (
                    <tr key={b.id} className="hover:bg-slate-50">
                      <td className="p-3 font-mono font-bold text-slate-900">{b.batch_no}</td>
                      <td className="p-3 font-medium text-slate-800">{b.technician_name}</td>
                      <td className="p-3 text-xs">
                        <span className="inline-flex px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-700">
                          {b.storage_method_code === 'PARTITIONED_CONTAINER'
                            ? 'Partitioned Bin'
                            : 'Dedicated Bins'}
                        </span>
                      </td>
                      <td className="p-3">
                        <Badge
                          variant={
                            b.status === 'COMPLETED'
                              ? 'success'
                              : b.status === 'OPEN'
                                ? 'warning'
                                : 'default'
                          }
                        >
                          {b.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-center">
                        <div className="flex flex-col items-center">
                          <span className="font-mono text-xs font-bold text-slate-900">
                            {b.total_dismantled_qty} / {b.total_input_qty}
                          </span>
                          <div className="w-24 bg-slate-200 rounded-full h-1.5 mt-1 overflow-hidden">
                            <div
                              className="bg-indigo-600 h-1.5 rounded-full transition-all"
                              style={{
                                width: `${String(
                                  Math.min(
                                    100,
                                    Math.round(
                                      (b.total_dismantled_qty / Math.max(1, b.total_input_qty)) *
                                        100,
                                    ),
                                  ),
                                )}%`,
                              }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="p-3 text-right text-xs text-slate-500">
                        {new Date(b.created_at).toLocaleDateString()}
                      </td>
                      <td className="p-3 text-right">
                        {b.status === 'OPEN' ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="primary"
                            onClick={() => {
                              onRecover(b.id);
                            }}
                            className="inline-flex items-center gap-1.5 text-xs py-1"
                          >
                            <Wrench className="w-3.5 h-3.5" />
                            Recover Parts
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              onRecover(b.id);
                            }}
                            className="inline-flex items-center gap-1 text-xs py-1 text-slate-500"
                          >
                            View
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
