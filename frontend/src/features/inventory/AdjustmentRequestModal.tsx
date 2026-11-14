import { useState } from 'react';

import { Button, Input, Modal, Textarea } from '@/components/ui';
import { toApiError, type ApiError } from '@/lib/api/client';
import { inventoryApi } from './api';
import { formatDelta } from './rules';
import type { Balance, StockCard } from './types';

interface Props {
  card: StockCard;
  balance: Balance;
  onClose: () => void;
  onDone: () => void;
}

/** A physical count difference, raised by the custodian; an approver posts the ADJUST. */
export function AdjustmentRequestModal({ card, balance, onClose, onDone }: Props) {
  const [counted, setCounted] = useState<number>(balance.qty);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [sent, setSent] = useState(false);

  const delta = counted - balance.qty;
  const valid = Number.isInteger(counted) && counted >= 0 && delta !== 0 && reason.trim() !== '';

  const submit = () => {
    if (!valid) return;
    setBusy(true);
    setError(null);
    inventoryApi
      .requestAdjustment({
        lot_id: card.lot_id,
        location_id: balance.location_id,
        counted_qty: counted,
        reason: reason.trim(),
      })
      .then(() => {
        setSent(true);
        onDone();
      })
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title="Report count difference"
      footer={
        sent ? (
          <Button type="button" variant="primary" style={{ minHeight: 44 }} onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button type="button" variant="secondary" style={{ minHeight: 44 }} onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              style={{ minHeight: 44 }}
              disabled={busy || !valid}
              onClick={submit}
            >
              {busy ? 'Sending…' : 'Send for approval'}
            </Button>
          </>
        )
      }
    >
      <p style={{ marginTop: 0 }}>
        {balance.location_name}: system quantity <strong>{balance.qty}</strong>
      </p>
      {sent ? (
        <p role="status">Sent for approval. The stock changes only when it is approved.</p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          <div>
            <label className="form-label" htmlFor="adj-counted">
              Physically counted
            </label>
            <Input
              id="adj-counted"
              type="number"
              inputMode="numeric"
              min={0}
              value={counted}
              onChange={(e) => {
                setCounted(Number(e.target.value));
              }}
              helperText={delta !== 0 ? `Difference ${formatDelta(delta)}` : 'No difference yet'}
            />
          </div>
          <div>
            <label className="form-label" htmlFor="adj-reason">
              Reason <span className="required-star">*</span>
            </label>
            <Textarea
              id="adj-reason"
              rows={3}
              maxLength={1000}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
          </div>
        </div>
      )}
      {error ? (
        <p role="alert" className="form-error">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
    </Modal>
  );
}
