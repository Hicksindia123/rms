/**
 * Phase P5 (DEC-65): the RM's open Edit Request on a locked goods slip, shown on the item screen
 * where Super Admin / Management make the post-lock edits (DEC-64 d). They mark it "Edited" after
 * changing the lines, or reject it with a note; the RM is notified either way. Also lists the GS's
 * transfer slips (live and voided).
 */
import React, { useEffect, useRef, useState } from 'react';

import { Badge, Button, Modal } from '@/components/ui';
import { newIdempotencyKey } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';

import { type GsTransferSlips, slipErrorMessage, transferSlipsApi } from './api';
import { SlipStatusBadge } from './SlipStatusBadge';

interface Props {
  gsId: string;
  /** Super Admin / Management (itemization.configure). */
  canResolve: boolean;
  /** A new value (e.g. the reloaded item state) when the GS changed, so the panel reloads. */
  version: unknown;
  onOpenSlip?: (slipId: string) => void;
}

export const EditRequestPanel: React.FC<Props> = ({ gsId, canResolve, version, onOpenSlip }) => {
  const [data, setData] = useState<GsTransferSlips | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const keyRef = useRef(newIdempotencyKey());

  useEffect(() => {
    let active = true;
    transferSlipsApi
      .forGs(gsId)
      .then((d) => {
        if (active) {
          setData(d);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(slipErrorMessage(err));
      });
    return () => {
      active = false;
    };
  }, [gsId, version, reload]);

  if (error) {
    return (
      <div className="banner banner--warning" role="alert">
        {error}{' '}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            setReload((k) => k + 1);
          }}
        >
          Retry
        </Button>
      </div>
    );
  }
  if (!data || (!data.open_edit_request && data.slips.length === 0)) return null;

  const req = data.open_edit_request;
  const resolve = (outcome: 'EDITED' | 'REJECTED') => {
    if (!req) return;
    setBusy(true);
    setActionError(null);
    transferSlipsApi
      .resolveEdit(req.id, outcome, outcome === 'REJECTED' ? note.trim() : null, keyRef.current)
      .then(() => {
        keyRef.current = newIdempotencyKey();
        setRejecting(false);
        setNote('');
        setReload((k) => k + 1);
      })
      .catch((err: unknown) => {
        keyRef.current = newIdempotencyKey();
        setActionError(slipErrorMessage(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <section className="card" aria-labelledby="gs-transfer-slips" data-testid="edit-request-panel">
      <h2 id="gs-transfer-slips" className="card__title">
        Transfer slips &amp; edit request
      </h2>
      {req ? (
        <div className="banner banner--warning" role="status" data-testid="open-edit-request">
          <strong>Edit requested</strong> by {req.requested_by_name ?? '—'} on{' '}
          {formatDateTime(req.requested_at)}: {req.reason}
        </div>
      ) : null}
      {req && canResolve ? (
        <div className="form-actions" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => {
              resolve('EDITED');
            }}
          >
            Mark as edited
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => {
              setActionError(null);
              setRejecting(true);
            }}
          >
            Reject request
          </Button>
        </div>
      ) : null}
      {actionError && !rejecting ? (
        <p role="alert" className="form-control__error">
          {actionError}
        </p>
      ) : null}
      {data.slips.length ? (
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: '0.75rem 0 0' }}>
          {data.slips.map((s) => (
            <li
              key={s.id}
              style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}
            >
              {onOpenSlip ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onOpenSlip(s.id);
                  }}
                >
                  <span className="mono">{s.slip_no}</span>
                </Button>
              ) : (
                <span className="mono">{s.slip_no}</span>
              )}
              <SlipStatusBadge status={s.status} />
              <Badge variant="neutral">{s.store.name}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
      <Modal
        isOpen={rejecting}
        onClose={() => {
          if (!busy) setRejecting(false);
        }}
        title="Reject the edit request"
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setRejecting(false);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={busy || note.trim().length < 3}
              isLoading={busy}
              onClick={() => {
                resolve('REJECTED');
              }}
            >
              Reject
            </Button>
          </>
        }
      >
        <label htmlFor="reject-note" className="form-control__label">
          Why is no change needed? (sent to the Replacement Manager)
        </label>
        <textarea
          id="reject-note"
          className="input"
          rows={3}
          value={note}
          maxLength={2000}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          style={{ width: '100%' }}
        />
        {actionError ? (
          <p role="alert" className="form-control__error">
            {actionError}
          </p>
        ) : null}
      </Modal>
    </section>
  );
};
