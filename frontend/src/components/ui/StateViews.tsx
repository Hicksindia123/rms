import React from 'react';
import { AlertTriangle, Inbox, Loader2, RotateCcw } from 'lucide-react';

import { Button } from './Button';

/** CLAUDE.md rule h: every screen has loading, empty, error (retry + request id) and success. */

export const LoadingState: React.FC<{ label?: string }> = ({ label = 'Loading…' }) => (
  <div
    role="status"
    aria-live="polite"
    style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '0.5rem',
      padding: '2rem 1rem',
      color: 'var(--color-muted)',
    }}
  >
    <Loader2 size={20} className="spin" aria-hidden="true" />
    <span>{label}</span>
  </div>
);

export const EmptyState: React.FC<{ title: string; hint?: string; action?: React.ReactNode }> = ({
  title,
  hint,
  action,
}) => (
  <div
    style={{
      textAlign: 'center',
      padding: '2.5rem 1rem',
      border: '1px dashed var(--color-border)',
      borderRadius: 'var(--radius-md, 8px)',
      backgroundColor: 'var(--color-surface)',
    }}
  >
    <Inbox size={32} aria-hidden="true" style={{ color: 'var(--color-muted)' }} />
    <p style={{ margin: '0.5rem 0 0', fontWeight: 600 }}>{title}</p>
    {hint ? (
      <p style={{ margin: '0.25rem 0 0', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
        {hint}
      </p>
    ) : null}
    {action ? <div style={{ marginTop: '1rem' }}>{action}</div> : null}
  </div>
);

export interface ErrorLike {
  message: string;
  code?: string;
  requestId?: string | null;
}

export const ErrorState: React.FC<{ error: ErrorLike; onRetry?: () => void; title?: string }> = ({
  error,
  onRetry,
  title = 'Something went wrong',
}) => (
  <div
    role="alert"
    style={{
      padding: '1rem',
      borderRadius: 'var(--radius-md, 8px)',
      border: '1px solid var(--color-danger-border)',
      backgroundColor: 'var(--color-danger-bg)',
      color: 'var(--color-fg)',
    }}
  >
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
      <AlertTriangle
        size={20}
        aria-hidden="true"
        style={{ color: 'var(--color-danger)', flexShrink: 0 }}
      />
      <div style={{ minWidth: 0 }}>
        <p style={{ margin: 0, fontWeight: 600 }}>{title}</p>
        <p style={{ margin: '0.25rem 0 0', wordBreak: 'break-word' }}>{error.message}</p>
        {error.code || error.requestId ? (
          <p
            style={{
              margin: '0.25rem 0 0',
              fontSize: '0.75rem',
              color: 'var(--color-muted)',
              wordBreak: 'break-all',
            }}
          >
            {error.code ? `Code: ${error.code}` : null}
            {error.code && error.requestId ? ' · ' : null}
            {error.requestId ? `Request ID: ${error.requestId}` : null}
          </p>
        ) : null}
      </div>
    </div>
    {onRetry ? (
      <Button
        type="button"
        variant="secondary"
        size="md"
        onClick={onRetry}
        style={{ marginTop: '0.75rem', minHeight: '44px' }}
      >
        <RotateCcw size={16} aria-hidden="true" /> Retry
      </Button>
    ) : null}
  </div>
);
