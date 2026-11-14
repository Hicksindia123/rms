import { useEffect, useState } from 'react';
import { AlertCircle, AlertTriangle, Truck, X } from 'lucide-react';

import { Button } from '@/components/ui';
import { toApiError } from '@/lib/api/client';

import { dispatchApi } from './api';
import type { DispatchCandidateLot, DispatchQueueItem, ReplacementDispatch } from './types';

interface Props {
  item: DispatchQueueItem;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (dispatch: ReplacementDispatch) => void;
}

export function DispatchModal({ item, isOpen, onClose, onSuccess }: Props) {
  const [dispatchQty, setDispatchQty] = useState(item.pending_qty);
  const [transporter, setTransporter] = useState('DTDC Express');
  const [docketNo, setDocketNo] = useState('');
  const [vehicleNo, setVehicleNo] = useState('');
  const [refDocNo, setRefDocNo] = useState('');
  const [refDocDate, setRefDocDate] = useState(new Date().toISOString().split('T')[0]);
  const [overrideReason, setOverrideReason] = useState('');
  const [notes, setNotes] = useState('');

  // Lots for SEND_REPAIRED
  const [candidateLots, setCandidateLots] = useState<DispatchCandidateLot[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string>('');
  const [loadingLots, setLoadingLots] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSendRepaired = item.action_code === 'SEND_REPAIRED';
  const isOverdispatch = dispatchQty > item.pending_qty;

  // Enter the loading state when a new lot lookup is due (adjusted during render, not
  // synchronously inside the effect).
  const lotsRequestKey = isOpen && isSendRepaired ? `${item.product_id}|${item.gs_item_id}` : null;
  const [prevLotsRequestKey, setPrevLotsRequestKey] = useState<string | null>(null);
  if (prevLotsRequestKey !== lotsRequestKey) {
    setPrevLotsRequestKey(lotsRequestKey);
    if (lotsRequestKey !== null) setLoadingLots(true);
  }

  useEffect(() => {
    if (isOpen && isSendRepaired) {
      dispatchApi
        .getCandidateLots(item.product_id, item.gs_item_id)
        .then((lots) => {
          setCandidateLots(lots);
          if (lots.length > 0 && lots[0]) {
            setSelectedLotId(lots[0].lot_id);
          }
        })
        .catch((err: unknown) => {
          setError(toApiError(err).message);
        })
        .finally(() => {
          setLoadingLots(false);
        });
    }
  }, [isOpen, isSendRepaired, item.product_id, item.gs_item_id]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transporter.trim()) {
      setError('Transporter name is required');
      return;
    }
    if (isSendRepaired && !selectedLotId) {
      setError('A FUNCTIONAL_REPAIRED lot must be selected for dispatch');
      return;
    }
    if (isOverdispatch && !overrideReason.trim()) {
      setError(
        'RM override_reason is required when dispatching more than planned quantity (DEC-33)',
      );
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const res = await dispatchApi.createDispatch({
        gs_id: item.gs_id,
        dispatch_type: item.action_code,
        transporter: transporter.trim(),
        docket_no: docketNo.trim() || undefined,
        vehicle_no: vehicleNo.trim() || undefined,
        ref_doc_no: refDocNo.trim() || undefined,
        ref_doc_date: refDocDate || undefined,
        override_reason: overrideReason.trim() || undefined,
        notes: notes.trim() || undefined,
        lines: [
          {
            gs_item_id: item.gs_item_id,
            qty: dispatchQty,
            lot_id: isSendRepaired ? selectedLotId : null,
          },
        ],
      });

      onSuccess(res);
      onClose();
    } catch (err) {
      setError(toApiError(err).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-card text-card-foreground border rounded-xl shadow-xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="p-4 border-b flex items-center justify-between bg-muted/30">
          <div>
            <h2 className="text-base font-bold flex items-center gap-2 text-foreground">
              <Truck className="w-5 h-5 text-primary" />
              Dispatch Replacement ({item.action_code})
            </h2>
            <div className="text-xs text-muted-foreground mt-0.5">
              Goods Slip: <strong className="text-foreground">{item.gs_no}</strong> • Party:{' '}
              <strong className="text-foreground">{item.party_name}</strong>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={(e) => void handleSubmit(e)} className="p-5 space-y-4 overflow-y-auto">
          {error && (
            <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Item Info Box */}
          <div className="p-3 rounded-lg bg-muted/40 border space-y-1 text-xs sm:text-sm">
            <div className="font-semibold text-foreground">{item.product_name}</div>
            <div className="font-mono text-xs text-muted-foreground">{item.product_code}</div>
            <div className="flex flex-wrap items-center gap-3 pt-1 text-xs">
              <div>
                Planned: <strong className="text-foreground font-mono">{item.planned_qty}</strong>{' '}
                pcs
              </div>
              <div>
                Dispatched:{' '}
                <strong className="text-foreground font-mono">{item.dispatched_qty}</strong> pcs
              </div>
              <div>
                Pending: <strong className="text-primary font-mono">{item.pending_qty}</strong> pcs
              </div>
            </div>
          </div>

          {/* Dispatch Info Notice */}
          {isSendRepaired ? (
            <div className="p-3 rounded-lg bg-teal-50/60 border border-teal-200 text-teal-900 dark:bg-teal-950/20 dark:border-teal-900/50 dark:text-teal-300 text-xs">
              <strong>SEND_REPAIRED:</strong> Consumes FUNCTIONAL_REPAIRED stock from Intermediate
              or Main Store (G-04) into DISPATCHED location.
            </div>
          ) : (
            <div className="p-3 rounded-lg bg-blue-50/60 border border-blue-200 text-blue-900 dark:bg-blue-950/20 dark:border-blue-900/50 dark:text-blue-300 text-xs">
              <strong>SEND_NEW (DEC-26):</strong> Dispatched from fresh Main Store stock outside the
              RMS returned-goods ledger. No lot is consumed.
            </div>
          )}

          {/* Quantity */}
          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              Dispatch Quantity (Pcs) <span className="text-destructive">*</span>
            </label>
            <input
              type="number"
              min={1}
              value={dispatchQty}
              onChange={(e) => {
                setDispatchQty(parseInt(e.target.value) || 1);
              }}
              className="w-full px-3 py-1.5 text-sm rounded-md border border-input bg-background font-mono font-bold"
              required
            />
          </div>

          {/* Over-dispatch warning */}
          {isOverdispatch && (
            <div className="p-3 rounded-lg bg-amber-50/80 border border-amber-300 text-amber-900 dark:bg-amber-950/20 dark:border-amber-900/50 dark:text-amber-300 text-xs space-y-1">
              <div className="flex items-center gap-1 font-semibold">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                Over-Dispatch Warning (DEC-33)
              </div>
              <p>
                Quantity exceeds pending RM allocation ({item.pending_qty} pcs). An RM override
                reason is mandatory.
              </p>
              <textarea
                placeholder="Reason for overriding planned RM allocation..."
                value={overrideReason}
                onChange={(e) => {
                  setOverrideReason(e.target.value);
                }}
                className="w-full mt-1.5 p-2 rounded border border-amber-300 bg-background text-foreground text-xs"
                rows={2}
                required
              />
            </div>
          )}

          {/* Repaired Lot Selector (for SEND_REPAIRED only) */}
          {isSendRepaired && (
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                Source Repaired Lot <span className="text-destructive">*</span>
              </label>
              {loadingLots ? (
                <div className="text-xs text-muted-foreground">
                  Loading available repaired lots...
                </div>
              ) : candidateLots.length === 0 ? (
                <div className="p-3 rounded bg-destructive/10 border border-destructive/20 text-destructive text-xs">
                  No FUNCTIONAL_REPAIRED lots with stock found for this product. Technical servicing
                  must complete first.
                </div>
              ) : (
                <select
                  value={selectedLotId}
                  onChange={(e) => {
                    setSelectedLotId(e.target.value);
                  }}
                  className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
                  required
                >
                  {candidateLots.map((lot) => (
                    <option key={lot.lot_id} value={lot.lot_id}>
                      Lot in {lot.location_code} • Avail: {lot.available_qty} pcs{' '}
                      {lot.gs_no ? `(from ${lot.gs_no})` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Transporter Details */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                Transporter / Courier <span className="text-destructive">*</span>
              </label>
              <input
                type="text"
                value={transporter}
                onChange={(e) => {
                  setTransporter(e.target.value);
                }}
                className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                Docket / Tracking No
              </label>
              <input
                type="text"
                placeholder="e.g. DKT-77889"
                value={docketNo}
                onChange={(e) => {
                  setDocketNo(e.target.value);
                }}
                className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                Vehicle / Reg No
              </label>
              <input
                type="text"
                placeholder="e.g. DL-01-AB-1234"
                value={vehicleNo}
                onChange={(e) => {
                  setVehicleNo(e.target.value);
                }}
                className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                Invoice / Delivery Challan No
              </label>
              <input
                type="text"
                placeholder="e.g. DC/2026/099"
                value={refDocNo}
                onChange={(e) => {
                  setRefDocNo(e.target.value);
                }}
                className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              Document Date
            </label>
            <input
              type="date"
              value={refDocDate}
              onChange={(e) => {
                setRefDocDate(e.target.value);
              }}
              className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              Notes / Remarks
            </label>
            <input
              type="text"
              placeholder="Dispatch remarks..."
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
              }}
              className="w-full px-3 py-1.5 text-xs rounded-md border border-input bg-background"
            />
          </div>

          {/* Footer Buttons */}
          <div className="pt-3 border-t flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting || (isSendRepaired && !selectedLotId)}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {submitting ? 'Dispatching...' : `Confirm Dispatch (${String(dispatchQty)} Pcs)`}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
