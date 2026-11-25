import React, { useState } from 'react';
import { AlertTriangle, Inbox, Loader2, RotateCcw, Copy, Check } from 'lucide-react';
import { Button } from './Button';
import { cn } from '@/lib/utils';

/** CLAUDE.md rule h: every screen has loading, empty, error (retry + request id) and success. */

export const LoadingState: React.FC<{ label?: string; className?: string }> = ({
  label = 'Loading…',
  className,
}) => (
  <div
    role="status"
    aria-live="polite"
    className={cn(
      'flex items-center justify-center gap-2.5 py-10 px-4 text-slate-500 font-medium text-sm',
      className,
    )}
  >
    <Loader2 size={18} className="animate-spin text-blue-600 flex-shrink-0" aria-hidden="true" />
    <span>{label}</span>
  </div>
);

export const EmptyState: React.FC<{
  title: string;
  hint?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}> = ({ title, hint, action, icon, className }) => (
  <div
    className={cn(
      'flex flex-col items-center justify-center text-center py-12 px-6 border border-dashed border-slate-300 rounded-2xl bg-white/70 shadow-xs',
      className,
    )}
  >
    <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center text-slate-400 mb-3.5 shadow-subtle">
      {icon || <Inbox size={24} aria-hidden="true" />}
    </div>
    <p className="text-base font-semibold text-slate-800 m-0">{title}</p>
    {hint ? <p className="text-xs sm:text-sm text-slate-500 mt-1 max-w-sm leading-normal">{hint}</p> : null}
    {action ? <div className="mt-4">{action}</div> : null}
  </div>
);

export interface ErrorLike {
  message: string;
  code?: string;
  requestId?: string | null;
}

export const ErrorState: React.FC<{
  error: ErrorLike;
  onRetry?: () => void;
  title?: string;
  className?: string;
}> = ({ error, onRetry, title = 'Something went wrong', className }) => {
  const [copied, setCopied] = useState(false);

  const handleCopyRequestId = () => {
    if (error.requestId) {
      void navigator.clipboard.writeText(error.requestId);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    }
  };

  return (
    <div
      role="alert"
      className={cn(
        'p-4 sm:p-5 rounded-2xl border border-rose-200 bg-rose-50/60 shadow-xs transition-all',
        className,
      )}
    >
      <div className="flex items-start gap-3.5">
        <div className="w-9 h-9 rounded-xl bg-rose-100 text-rose-600 flex items-center justify-center flex-shrink-0 mt-0.5">
          <AlertTriangle size={18} aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-rose-900 m-0">{title}</p>
          <p className="text-xs sm:text-sm text-rose-700 mt-1 break-words leading-relaxed">
            {error.message}
          </p>
          {error.code || error.requestId ? (
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-rose-600/90 font-mono">
              {error.code ? (
                <span className="bg-rose-100/80 px-2 py-0.5 rounded-md border border-rose-200">
                  Code: {error.code}
                </span>
              ) : null}
              {error.requestId ? (
                <button
                  type="button"
                  onClick={handleCopyRequestId}
                  title="Click to copy request ID"
                  className="inline-flex items-center gap-1.5 bg-rose-100/80 hover:bg-rose-200/80 px-2 py-0.5 rounded-md border border-rose-200 text-rose-800 transition-colors cursor-pointer"
                >
                  <span>Request ID: {error.requestId}</span>
                  {copied ? <Check size={11} className="text-emerald-600" /> : <Copy size={11} />}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {onRetry ? (
        <div className="mt-3.5 pl-12.5 flex items-center">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRetry}
            className="border-rose-300 text-rose-800 hover:bg-rose-100/70"
          >
            <RotateCcw size={14} aria-hidden="true" />
            <span>Retry</span>
          </Button>
        </div>
      ) : null}
    </div>
  );
};
