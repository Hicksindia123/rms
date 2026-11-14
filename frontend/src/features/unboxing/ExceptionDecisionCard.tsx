import { useState } from 'react';
import { Check, X } from 'lucide-react';

import { Button, Textarea } from '@/components/ui';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';

import { unboxingApi, type MissingDocException } from './api';
import { AttachmentThumb } from './SignedMedia';

/** DEC-03: the Replacement Manager approves or rejects a Missing Document Exception (mobile card). */
export function ExceptionDecisionCard({
  exception,
  onDecided,
  onOpenGs,
}: {
  exception: MissingDocException;
  onDecided: (updated: MissingDocException) => void;
  onOpenGs?: (gsId: string) => void;
}) {
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState<'APPROVE' | 'REJECT' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const decide = async (decision: 'APPROVE' | 'REJECT') => {
    setBusy(decision);
    setError(null);
    try {
      onDecided(
        await unboxingApi.decideException(exception.gs_id, exception.id, decision, remarks.trim()),
      );
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="card approval-card" data-testid="exception-card">
      <div className="approval-card__head">
        <AttachmentThumb
          attachment={{
            id: exception.parcel_attachment_id,
            gs_id: exception.gs_id,
            kind: 'PARCEL_PHOTO',
            mime_type: exception.parcel_mime_type,
            size_bytes: 0,
            box_no: null,
            status: 'CONFIRMED',
            uploaded_by: null,
            uploaded_by_name: null,
            created_at: exception.requested_at,
            confirmed_at: exception.requested_at,
            preview_unsupported: exception.parcel_preview_unsupported,
          }}
          alt={`Parcel photo for ${exception.gs_no}`}
        />
        <div style={{ minWidth: 0 }}>
          <p style={{ margin: 0, fontWeight: 700, wordBreak: 'break-all' }}>
            {onOpenGs ? (
              <button
                type="button"
                className="dataview__link"
                onClick={() => {
                  onOpenGs(exception.gs_id);
                }}
              >
                {exception.gs_no}
              </button>
            ) : (
              exception.gs_no
            )}
          </p>
          {exception.party_name ? (
            <p className="page__subtitle" style={{ margin: 0 }}>
              {exception.party_name}
            </p>
          ) : null}
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
            {exception.requested_by_name ?? 'Unknown'} · {formatDateTime(exception.requested_at)}
          </p>
        </div>
      </div>
      <p style={{ margin: '0.75rem 0', whiteSpace: 'pre-wrap' }}>“{exception.remark}”</p>
      <label className="form-label" htmlFor={`decision-${exception.id}`}>
        Decision remarks (required to reject)
      </label>
      <Textarea
        id={`decision-${exception.id}`}
        value={remarks}
        rows={2}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {error ? (
        <p role="alert" className="form-control__error">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
      <div className="approval-card__actions">
        <Button
          type="button"
          variant="danger"
          isLoading={busy === 'REJECT'}
          disabled={busy !== null}
          onClick={() => {
            void decide('REJECT');
          }}
        >
          <X size={16} aria-hidden="true" /> Reject
        </Button>
        <Button
          type="button"
          variant="primary"
          isLoading={busy === 'APPROVE'}
          disabled={busy !== null}
          onClick={() => {
            void decide('APPROVE');
          }}
        >
          <Check size={16} aria-hidden="true" /> Approve exception
        </Button>
      </div>
    </article>
  );
}
