import { useState } from 'react';

import { Button, Input, Modal, RadioGroup, Textarea } from '@/components/ui';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { inventoryApi } from './api';
import { gsRef, itemTitle, validAssignmentOptions } from './rules';
import type { Assignment, AssignmentCode, InventoryOption, StockRow } from './types';

interface Props {
  row: StockRow;
  options: InventoryOption[];
  onClose: () => void;
  onDone: () => void;
  onOpenTransfer: (transferId: string) => void;
}

/** DD r63-66 custody assignment. Only the options valid for this lot's condition are shown. */
export function CustodyAssignModal({ row, options, onClose, onDone, onOpenTransfer }: Props) {
  const valid = validAssignmentOptions(row, options);
  const [code, setCode] = useState<string>(valid[0]?.code ?? '');
  const [qty, setQty] = useState(row.qty);
  const [notes, setNotes] = useState('');
  // One key per dialog: a retry after a network error re-uses it (G-16).
  const [key] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<Assignment | null>(null);

  const qtyValid = Number.isInteger(qty) && qty >= 1 && qty <= row.qty;
  const submit = () => {
    if (!code || !qtyValid) return;
    setBusy(true);
    setError(null);
    inventoryApi
      .assign(
        {
          lot_id: row.lot_id,
          qty,
          assignment_code: code as AssignmentCode,
          from_location_id: row.location_id,
          ...(notes.trim() ? { notes: notes.trim() } : {}),
        },
        key,
      )
      .then((res) => {
        setResult(res);
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
      title="Custody assignment"
      footer={
        result ? (
          <>
            {result.transfer_id ? (
              <Button
                type="button"
                variant="secondary"
                style={{ minHeight: 44 }}
                onClick={() => {
                  if (result.transfer_id) onOpenTransfer(result.transfer_id);
                }}
              >
                Open transfer
              </Button>
            ) : null}
            <Button type="button" variant="primary" style={{ minHeight: 44 }} onClick={onClose}>
              Done
            </Button>
          </>
        ) : (
          <>
            <Button type="button" variant="secondary" style={{ minHeight: 44 }} onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              style={{ minHeight: 44 }}
              disabled={busy || !code || !qtyValid}
              onClick={submit}
            >
              {busy ? 'Saving…' : 'Assign'}
            </Button>
          </>
        )
      }
    >
      <p style={{ marginTop: 0 }}>
        <strong>{itemTitle(row)}</strong> · {gsRef(row)} · {row.location_name} ({row.qty})
      </p>
      {result ? (
        <div
          role="status"
          style={{
            padding: '0.75rem',
            borderRadius: 8,
            background: 'var(--color-success-bg)',
            color: 'var(--color-fg)',
          }}
        >
          {result.outcome === 'ALREADY_IN_PLACE'
            ? `Recorded: ${String(result.qty)} already with the right custodian (${result.to_location_name}).`
            : `Transfer ${result.transfer_no ?? ''} started to ${result.to_location_name}. The stock is in transit until the custodian accepts it.`}
        </div>
      ) : valid.length === 0 ? (
        <p>No custody assignment applies to this lot.</p>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          <fieldset style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
            <legend className="form-label">Assign to</legend>
            <RadioGroup
              name="custody_assignment"
              value={code}
              onChange={setCode}
              options={valid.map((o) => ({
                value: o.code,
                label: o.label,
                rule_text: o.description ?? null,
              }))}
            />
          </fieldset>
          <div>
            <label className="form-label" htmlFor="assign-qty">
              Quantity (max {row.qty})
            </label>
            <Input
              id="assign-qty"
              type="number"
              inputMode="numeric"
              min={1}
              max={row.qty}
              value={qty}
              onChange={(e) => {
                setQty(Number(e.target.value));
              }}
              error={qtyValid ? undefined : `Enter 1 to ${String(row.qty)}`}
            />
          </div>
          <div>
            <label className="form-label" htmlFor="assign-notes">
              Remarks
            </label>
            <Textarea
              id="assign-notes"
              rows={2}
              maxLength={1000}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
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
