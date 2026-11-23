/**
 * Phase P10 (DEC-70; Q17): the Management e-approval stamp of a goods slip and its "Verify" button.
 * VALID shows "Digitally approved by Management — name, date time, ref <short hash>" (wording from
 * the system setting, built by the backend); CHANGED says the goods slip changed after the
 * approval. Verify recomputes the SHA-256 on the server and shows Valid / Changed.
 *
 * `StampPanel` loads the stamp itself (GS detail page) and renders nothing when there is none.
 */
import React, { useEffect, useState } from 'react';
import { BadgeCheck, ShieldAlert } from 'lucide-react';

import { Button, ErrorState } from '@/components/ui';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';

import { managementApprovalApi } from './api';
import type { Stamp, VerifyResult } from './types';

export const ApprovalStamp: React.FC<{ gsId: string; stamp: Stamp }> = ({ gsId, stamp }) => {
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  if (stamp.state === 'NONE' || !stamp.approval) return null;
  const a = stamp.approval;

  const verify = () => {
    setVerifying(true);
    setError(null);
    managementApprovalApi
      .verify(gsId)
      .then(setResult)
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setVerifying(false);
      });
  };

  const valid = stamp.state === 'VALID';
  return (
    <section
      aria-label="Management approval"
      data-testid="approval-stamp"
      className={`rounded-xl border-2 p-4 text-sm ${
        valid
          ? 'border-emerald-600 bg-emerald-50 text-emerald-950 dark:border-emerald-500 dark:bg-emerald-950/40 dark:text-emerald-100'
          : 'border-amber-500 bg-amber-50 text-amber-950 dark:border-amber-500 dark:bg-amber-950/40 dark:text-amber-100'
      }`}
    >
      <div className="flex items-start gap-2">
        {valid ? (
          <BadgeCheck className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        ) : (
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1 space-y-1">
          {valid ? (
            <p className="break-words font-semibold" data-testid="stamp-text">
              {stamp.stamp_text}
            </p>
          ) : (
            <p className="break-words font-semibold">
              Changed after the Management approval (no. {a.approval_no}, ref {a.short_ref}): a new
              approval is needed.
            </p>
          )}
          <p className="text-xs opacity-80">
            Approval no. {a.approval_no} · {a.approver_role} · {formatDateTime(a.approved_at)}
            {a.has_issue_cn ? ' · includes Issue CN' : ''}
          </p>
          <p className="text-xs opacity-80">{stamp.disclaimer}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <Button
          type="button"
          variant="outline"
          className="min-h-[44px]"
          isLoading={verifying}
          onClick={verify}
        >
          Verify
        </Button>
        {result ? (
          <p role="status" className="break-words text-xs" data-testid="verify-result">
            <strong>{result.result === 'VALID' ? 'Valid' : 'Changed'}</strong>
            {result.result === 'VALID'
              ? ': the goods slip matches the approved snapshot'
              : result.integrity_ok
                ? ': the goods slip differs from the approved snapshot'
                : ': the stored approval does not match its hash'}{' '}
            (now {result.current_sha256.slice(0, 12)}, approved{' '}
            {(result.stored_sha256 ?? '').slice(0, 12)})
          </p>
        ) : null}
      </div>
      {error ? <ErrorState error={error} onRetry={verify} title="Could not verify" /> : null}
    </section>
  );
};

/** Statuses before a goods slip can carry a Management approval (no request is made for them). */
const BEFORE_APPROVAL = new Set([
  'GATE_CREATED',
  'UNBOXING',
  'ITEMIZATION',
  'CATEGORISATION',
  'CSR_APPROVAL_PENDING',
  'INSPECTION',
  'RM_REVIEW',
  'PENDING_TRANSFER_SLIP',
  'TRANSFER_SLIP_GENERATED',
  'STORE_ACKNOWLEDGED',
  'STORE_PROCESSING',
  'SALES_RETURN_HOLD',
]);

/** GS detail page: loads the stamp of the goods slip; nothing when it has no approval. */
export const StampPanel: React.FC<{ gsId: string; status: string }> = ({ gsId, status }) => {
  const enabled = !BEFORE_APPROVAL.has(status);
  const [stamp, setStamp] = useState<Stamp | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    managementApprovalApi
      .getStamp(gsId)
      .then((s) => {
        if (active) {
          setStamp(s);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(toApiError(err));
      });
    return () => {
      active = false;
    };
  }, [gsId, enabled, reloadKey]);

  if (!enabled) return null;
  if (error) {
    return (
      <ErrorState
        error={error}
        onRetry={() => {
          setReloadKey((k) => k + 1);
        }}
        title="Could not load the Management approval"
      />
    );
  }
  return stamp ? <ApprovalStamp gsId={gsId} stamp={stamp} /> : null;
};
