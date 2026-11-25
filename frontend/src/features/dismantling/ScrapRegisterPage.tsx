import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Filter, RefreshCw, Trash2 } from 'lucide-react';
import { Badge, Button, ErrorState, Input, LoadingState, Modal } from '@/components/ui';
import { newIdempotencyKey } from '@/lib/api/client';
import { dismantlingApi } from './api';
import type { DisposableLot, DisposalStatusCode, ScrapRecord } from './types';

async function fetchDisposable(): Promise<DisposableLot[]> {
  // DEC-11: quarantined mercury stock; DEC-18: non-dismantleable non-good stock.
  const [quarantine, queue, marked] = await Promise.all([
    dismantlingApi.listHazardQuarantine(),
    dismantlingApi.getQueue(),
    dismantlingApi.listScrap({ disposal_status: 'MARKED', page_size: 100 }),
  ]);
  // Pieces already marked (awaiting disposal below) are not offered again.
  const markedQty = new Map<string, number>();
  for (const r of marked) {
    if (r.lot_id) markedQty.set(r.lot_id, (markedQty.get(r.lot_id) ?? 0) + r.qty_pieces);
  }
  const lots: DisposableLot[] = [
    ...quarantine.items.map((r) => ({ ...r, hazard: true })),
    ...queue.disposal_required_lots.map((r) => ({
      lot_id: r.lot_id,
      gs_no: r.gs_no ?? null,
      product_name: r.product_name ?? null,
      condition_class: r.condition_class,
      location_code: 'NON_FUNCTIONAL_STORE',
      qty: r.qty,
      hazard: false,
    })),
  ];
  return lots
    .map((l) => ({ ...l, qty: l.qty - (markedQty.get(l.lot_id) ?? 0) }))
    .filter((l) => l.qty > 0);
}

export function ScrapRegisterPage() {
  const [scrapRecords, setScrapRecords] = useState<ScrapRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<DisposalStatusCode | 'ALL'>('ALL');
  const [hazardousOnly, setHazardousOnly] = useState(false);

  // Disposal Modal state
  const [selectedScrap, setSelectedScrap] = useState<ScrapRecord | null>(null);
  const [manifestRef, setManifestRef] = useState('');
  const [disposing, setDisposing] = useState(false);
  const [disposeError, setDisposeError] = useState<string | null>(null);
  const [disposeSuccess, setDisposeSuccess] = useState<string | null>(null);

  // Stock awaiting disposal (P3-08: DEC-11 / DEC-18 lot-linked scrap)
  const [disposable, setDisposable] = useState<DisposableLot[]>([]);
  const [disposableError, setDisposableError] = useState<string | null>(null);
  const [markQty, setMarkQty] = useState<Record<string, string>>({});
  const [marking, setMarking] = useState<string | null>(null);

  const loadDisposable = async () => {
    setDisposableError(null);
    try {
      setDisposable(await fetchDisposable());
    } catch (err: unknown) {
      setDisposableError(err instanceof Error ? err.message : 'Failed to load stock to dispose');
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        setDisposable(await fetchDisposable());
      } catch (err: unknown) {
        setDisposableError(err instanceof Error ? err.message : 'Failed to load stock to dispose');
      }
    })();
  }, []);

  const handleMark = async (lot: DisposableLot) => {
    const qty = Number(markQty[lot.lot_id] ?? lot.qty);
    if (!Number.isInteger(qty) || qty < 1 || qty > lot.qty) {
      setDisposableError(`Enter 1 to ${String(lot.qty)} pieces for ${lot.gs_no ?? 'this lot'}.`);
      return;
    }
    setMarking(lot.lot_id);
    setDisposableError(null);
    try {
      await dismantlingApi.markLotForDisposal(
        { lot_id: lot.lot_id, qty, remarks: lot.hazard ? 'Mercury hazard' : null },
        newIdempotencyKey(),
      );
      setDisposeSuccess(`${String(qty)} piece(s) marked for disposal.`);
      await Promise.all([loadDisposable(), loadScrap()]);
    } catch (err: unknown) {
      setDisposableError(err instanceof Error ? err.message : 'Failed to mark stock for disposal');
    } finally {
      setMarking(null);
    }
  };

  const loadScrap = async () => {
    setLoading(true);
    setError(null);
    try {
      const records = await dismantlingApi.listScrap({
        disposal_status: statusFilter === 'ALL' ? undefined : statusFilter,
        page_size: 100,
      });
      setScrapRecords(records);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load scrap records');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const records = await dismantlingApi.listScrap({
          disposal_status: statusFilter === 'ALL' ? undefined : statusFilter,
          page_size: 100,
        });
        setScrapRecords(records);
        setLoading(false);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load scrap records');
        setLoading(false);
      }
    })();
  }, [statusFilter]);

  const handleOpenDisposeModal = (scrap: ScrapRecord) => {
    setSelectedScrap(scrap);
    setManifestRef('');
    setDisposeError(null);
  };

  const handleDisposeSubmit = async () => {
    if (!selectedScrap) return;

    // DEC-11: Hazardous scrap requires manifest reference
    if (selectedScrap.hazardous && !manifestRef.trim()) {
      setDisposeError('Manifest reference is mandatory for hazardous scrap disposal.');
      return;
    }

    setDisposing(true);
    setDisposeError(null);

    const idemKey = newIdempotencyKey();

    try {
      await dismantlingApi.disposeScrap(
        selectedScrap.id,
        {
          manifest_ref: manifestRef.trim() || null,
        },
        idemKey,
      );
      setDisposeSuccess(`Scrap record disposed successfully!`);
      setSelectedScrap(null);
      await loadScrap();
    } catch (err: unknown) {
      setDisposeError(err instanceof Error ? err.message : 'Failed to dispose scrap record');
    } finally {
      setDisposing(false);
    }
  };

  const filteredRecords = scrapRecords.filter((rec) => {
    if (hazardousOnly && !rec.hazardous) return false;
    return true;
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <Trash2 className="w-6 h-6 text-red-600" />
            Scrap & Safe Disposal Register
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Track and authorize scrap disposal with manifest verification for hazardous waste.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void loadScrap();
            }}
            disabled={loading}
            className="flex items-center gap-1.5"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <ErrorState
          error={{ message: error }}
          onRetry={() => {
            void loadScrap();
          }}
        />
      )}

      {disposeSuccess && (
        <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-emerald-600" />
            <span>{disposeSuccess}</span>
          </div>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => {
              setDisposeSuccess(null);
            }}
            style={{ minWidth: 44, minHeight: 44 }}
            className="text-emerald-700 hover:text-emerald-900 font-bold"
          >
            &times;
          </button>
        </div>
      )}

      {/* Stock awaiting disposal (DEC-11 / DEC-18) */}
      <section
        aria-labelledby="awaiting-disposal-heading"
        className="space-y-3 p-4 bg-white border border-slate-200 rounded-lg shadow-sm"
      >
        <h2 id="awaiting-disposal-heading" className="text-base font-semibold text-slate-900">
          Stock awaiting disposal
        </h2>
        <p className="text-xs text-slate-500">
          Mercury-hazard stock in quarantine and non-good stock that cannot be dismantled. Mark it
          as scrap, then dispose of it below with the manifest.
        </p>
        {disposableError && (
          <ErrorState
            error={{ message: disposableError }}
            onRetry={() => {
              void loadDisposable();
            }}
          />
        )}
        {disposable.length === 0 ? (
          <p className="text-sm text-slate-500">No stock is waiting for disposal.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Stock awaiting disposal">
            {disposable.map((lot) => (
              <li
                key={lot.lot_id}
                data-testid={`disposable-${lot.lot_id}`}
                className="p-3 border border-slate-200 rounded-lg space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono font-bold text-slate-900">{lot.gs_no ?? '-'}</span>
                  {lot.hazard ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold bg-red-100 text-red-800">
                      <AlertTriangle className="w-3 h-3 text-red-600" />
                      HAZARDOUS
                    </span>
                  ) : (
                    <Badge variant="warning">{lot.condition_class}</Badge>
                  )}
                </div>
                <div className="text-sm text-slate-700">{lot.product_name ?? '-'}</div>
                <div className="text-xs text-slate-500">
                  {lot.location_code} - {String(lot.qty)} pcs
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <div className="w-28">
                    <label
                      htmlFor={`mark-qty-${lot.lot_id}`}
                      className="block text-xs font-semibold text-slate-700 mb-1"
                    >
                      Pieces to scrap
                    </label>
                    <Input
                      id={`mark-qty-${lot.lot_id}`}
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={lot.qty}
                      value={markQty[lot.lot_id] ?? String(lot.qty)}
                      onChange={(e) => {
                        setMarkQty((prev) => ({ ...prev, [lot.lot_id]: e.target.value }));
                      }}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="primary"
                    style={{ minHeight: 44 }}
                    disabled={marking !== null}
                    onClick={() => {
                      void handleMark(lot);
                    }}
                  >
                    {marking === lot.lot_id ? 'Marking...' : 'Mark for disposal'}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Filters Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-white border border-slate-200 rounded-lg shadow-sm">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-500" />
          <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
            Status:
          </span>
          {(['ALL', 'MARKED', 'DISPOSED'] as const).map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => {
                setStatusFilter(st);
              }}
              // Rule h: 44 px touch target (P3-04 E2E finding).
              style={{ minHeight: 44 }}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                statusFilter === st
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {st === 'ALL' ? 'All Records' : st}
            </button>
          ))}
        </div>

        <label
          className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer"
          style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <input
            type="checkbox"
            checked={hazardousOnly}
            onChange={(e) => {
              setHazardousOnly(e.target.checked);
            }}
            className="w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500"
          />
          <span>Hazardous Waste Only</span>
        </label>
      </div>

      {/* Table */}
      {loading && filteredRecords.length === 0 ? (
        <LoadingState label="Loading scrap register..." />
      ) : filteredRecords.length === 0 ? (
        <div className="p-12 text-center border-2 border-dashed border-slate-200 rounded-lg text-slate-500 text-sm">
          No scrap records found matching the current filters.
        </div>
      ) : (
        <div className="border border-slate-200 rounded-lg overflow-x-auto bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-700 font-semibold border-b border-slate-200 text-xs uppercase tracking-wider">
              <tr>
                <th className="p-3">Batch / Source</th>
                <th className="p-3 text-right">Pieces</th>
                <th className="p-3 text-right">Weight (kg)</th>
                <th className="p-3">Hazardous Status</th>
                <th className="p-3">Remarks</th>
                <th className="p-3">Disposal Status</th>
                <th className="p-3">Manifest Ref</th>
                <th className="p-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {filteredRecords.map((scrap) => (
                <tr key={scrap.id} className="hover:bg-slate-50">
                  <td className="p-3">
                    <div className="font-mono font-bold text-slate-900">
                      {scrap.batch_no ?? 'Direct Scrap'}
                    </div>
                    <div className="text-xs text-slate-500">
                      {new Date(scrap.created_at).toLocaleDateString()}
                    </div>
                  </td>
                  <td className="p-3 text-right font-mono font-bold text-slate-900">
                    {scrap.qty_pieces}
                  </td>
                  <td className="p-3 text-right font-mono text-slate-700">
                    {scrap.weight_kg !== null && scrap.weight_kg !== undefined
                      ? scrap.weight_kg.toFixed(3)
                      : '—'}
                  </td>
                  <td className="p-3">
                    {scrap.hazardous ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold bg-red-100 text-red-800">
                        <AlertTriangle className="w-3 h-3 text-red-600" />
                        HAZARDOUS
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700">
                        Standard
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-xs text-slate-600 max-w-xs truncate">
                    {scrap.remarks ?? '—'}
                  </td>
                  <td className="p-3">
                    <Badge variant={scrap.disposal_status === 'DISPOSED' ? 'success' : 'warning'}>
                      {scrap.disposal_status}
                    </Badge>
                  </td>
                  <td className="p-3 font-mono text-xs text-slate-700">
                    {scrap.manifest_ref ?? '—'}
                  </td>
                  <td className="p-3 text-right">
                    {scrap.disposal_status === 'MARKED' ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="primary"
                        onClick={() => {
                          handleOpenDisposeModal(scrap);
                        }}
                        className="inline-flex items-center gap-1 text-xs py-1"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Dispose
                      </Button>
                    ) : (
                      <div className="text-xs text-slate-500">
                        Disposed by {scrap.disposed_by_name ?? 'SPM'}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Disposal Modal */}
      <Modal
        isOpen={selectedScrap !== null}
        onClose={() => {
          setSelectedScrap(null);
        }}
        title="Authorize Scrap Disposal"
      >
        {selectedScrap && (
          <div className="space-y-4">
            {disposeError && (
              <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-800 text-xs">
                {disposeError}
              </div>
            )}

            <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-xs space-y-1.5">
              <div className="flex justify-between">
                <span className="text-slate-500">Source Batch:</span>
                <span className="font-mono font-bold text-slate-800">
                  {selectedScrap.batch_no ?? 'Direct Scrap'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Pieces / Weight:</span>
                <span className="font-mono font-bold text-slate-800">
                  {String(selectedScrap.qty_pieces)} pcs{' '}
                  {selectedScrap.weight_kg ? `(${selectedScrap.weight_kg.toFixed(3)} kg)` : ''}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Waste Class:</span>
                <span
                  className={`font-bold ${
                    selectedScrap.hazardous ? 'text-red-700' : 'text-slate-800'
                  }`}
                >
                  {selectedScrap.hazardous ? 'Hazardous Waste' : 'General Scrap'}
                </span>
              </div>
            </div>

            {selectedScrap.hazardous && (
              <div className="p-3 rounded-lg bg-amber-50 border border-amber-300 text-xs text-amber-900 space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <AlertTriangle className="w-4 h-4 text-amber-700" />
                  Compliance Requirement
                </div>
                <p>
                  Disposing hazardous waste requires a verified manifest reference number from the
                  licensed recycler / waste management provider.
                </p>
              </div>
            )}

            <div>
              <label
                htmlFor="scrap-manifest-ref"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Manifest Reference Number {selectedScrap.hazardous ? '*' : '(Optional)'}
              </label>
              <Input
                id="scrap-manifest-ref"
                value={manifestRef}
                onChange={(e) => {
                  setManifestRef(e.target.value);
                }}
                placeholder="e.g. HAZ-MAN-2026-9042"
                required={selectedScrap.hazardous}
              />
              <p className="text-[11px] text-slate-500 mt-1">
                {selectedScrap.hazardous
                  ? 'Mandatory for hazardous scrap compliance.'
                  : 'Optional external tracking reference.'}
              </p>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSelectedScrap(null);
                }}
                disabled={disposing}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => {
                  void handleDisposeSubmit();
                }}
                disabled={disposing || (selectedScrap.hazardous && !manifestRef.trim())}
                className="flex items-center gap-2"
              >
                {disposing ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Disposing...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Confirm Disposal
                  </>
                )}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
