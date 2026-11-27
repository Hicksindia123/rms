/**
 * DEC-76: the E-Commerce Executive's portal resolution (what the portal shows for the order id:
 * Free Replacement / Refund, from the ECOM_PORTAL_RESOLUTION option set) with its qty and a short
 * note. Used when closing a platform ticket and in the Portal Check queue. A refund becomes "Qty
 * Issue CN" on the action sheet; a free replacement never gets a credit note.
 */
import React, { useRef, useState } from 'react';

import { Button, ErrorState, Input, Modal, RadioGroup, Textarea } from '@/components/ui';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import type { Option, ResolutionIn } from './types';
import { REFUND } from './types';

interface Props {
  title: string;
  intro?: React.ReactNode;
  options: Option[];
  maxQty: number;
  submitLabel: string;
  onSubmit: (body: ResolutionIn, idempotencyKey: string) => Promise<unknown>;
  onClose: () => void;
  onDone: () => void;
}

export const ResolutionModal: React.FC<Props> = ({
  title,
  intro,
  options,
  maxQty,
  submitLabel,
  onSubmit,
  onClose,
  onDone,
}) => {
  const [code, setCode] = useState('');
  const [qty, setQty] = useState(String(maxQty));
  const [note, setNote] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());

  const n = Number(qty);
  const save = async () => {
    setFieldError(null);
    if (!code) {
      setFieldError('Choose what the portal shows for this order');
      return;
    }
    if (!Number.isInteger(n) || n < 1 || n > maxQty) {
      setFieldError(`Qty must be 1 to ${String(maxQty)}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(
        { resolution_code: code, resolution_qty: n, resolution_note: note.trim() || null },
        key.current,
      );
      onDone();
    } catch (err) {
      console.error('Recording the portal resolution failed', { err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            className="min-h-[44px]"
            disabled={busy}
            data-testid="resolution-save"
            onClick={() => {
              void save();
            }}
          >
            {submitLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {intro}
        <p className="form-control__label m-0">
          Portal shows <span className="text-red-600">*</span>
        </p>
        <RadioGroup
          id="portal-resolution"
          name="resolution_code"
          value={code}
          options={options.map((o) => ({ value: o.code, label: o.label }))}
          onChange={(v) => {
            setCode(v);
          }}
        />
        <div>
          <label htmlFor="resolution-qty" className="form-control__label">
            Qty <span className="text-red-600">*</span>
          </label>
          <Input
            id="resolution-qty"
            type="number"
            inputMode="numeric"
            min={1}
            max={maxQty}
            step={1}
            value={qty}
            onChange={(e) => {
              setQty(e.target.value);
            }}
          />
          <p className="m-0 mt-1 text-xs text-slate-500">
            {code === REFUND
              ? `Accounts issues a credit note for ${String(Number.isInteger(n) ? n : 0)} pc(s).`
              : code
                ? 'No credit note for this order.'
                : `Up to the ${String(maxQty)} received.`}
          </p>
        </div>
        <div>
          <label htmlFor="resolution-note" className="form-control__label">
            Short note
          </label>
          <Textarea
            id="resolution-note"
            rows={2}
            maxLength={200}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
        </div>
        {fieldError ? (
          <p className="form-control__error" role="alert">
            {fieldError}
          </p>
        ) : null}
        {error ? <ErrorState error={error} title="Could not save" /> : null}
      </div>
    </Modal>
  );
};

/** DEC-76: a follow-up with the platform on a raised ticket. */
export const FollowUpModal: React.FC<{
  title: string;
  today: string;
  onSubmit: (
    body: { note: string; next_follow_up_on: string | null },
    key: string,
  ) => Promise<unknown>;
  onClose: () => void;
  onDone: () => void;
}> = ({ title, today, onSubmit, onClose, onDone }) => {
  const [note, setNote] = useState('');
  const [next, setNext] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ note: note.trim(), next_follow_up_on: next || null }, key.current);
      onDone();
    } catch (err) {
      console.error('Saving the follow-up failed', { err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            className="min-h-[44px]"
            disabled={busy || note.trim().length < 3}
            data-testid="follow-up-save"
            onClick={() => {
              void save();
            }}
          >
            Save follow-up
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label htmlFor="follow-up-note" className="form-control__label">
            What happened <span className="text-red-600">*</span>
          </label>
          <Textarea
            id="follow-up-note"
            rows={3}
            maxLength={300}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
        </div>
        <div>
          <label htmlFor="follow-up-next" className="form-control__label">
            Next follow-up on
          </label>
          <Input
            id="follow-up-next"
            type="date"
            min={today}
            value={next}
            onChange={(e) => {
              setNext(e.target.value);
            }}
          />
        </div>
        {error ? <ErrorState error={error} title="Could not save" /> : null}
      </div>
    </Modal>
  );
};
