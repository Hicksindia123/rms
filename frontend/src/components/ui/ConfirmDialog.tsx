import React, { useEffect, useId } from 'react';
import { AlertTriangle, AlertCircle, X } from 'lucide-react';
import { Button } from './Button';
import { cn } from '@/lib/utils';

export interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: 'primary' | 'danger';
  isLoading?: boolean;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirmVariant = 'primary',
  isLoading = false,
}) => {
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen && !isLoading) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, isLoading, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      className="fixed inset-0 z-[1000] flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLoading) onClose();
      }}
    >
      <div className="w-full max-w-md bg-white rounded-2xl shadow-dialog border border-slate-200/80 overflow-hidden flex flex-col transition-all transform animate-in zoom-in-95 duration-150">
        <div className="p-5 flex items-start gap-4">
          <div
            className={cn(
              'w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0',
              confirmVariant === 'danger'
                ? 'bg-rose-50 text-rose-600 border border-rose-100'
                : 'bg-blue-50 text-blue-600 border border-blue-100',
            )}
          >
            {confirmVariant === 'danger' ? (
              <AlertTriangle className="w-5 h-5" aria-hidden="true" />
            ) : (
              <AlertCircle className="w-5 h-5" aria-hidden="true" />
            )}
          </div>
          <div className="flex-1 min-w-0 pt-0.5">
            <h2 id={titleId} className="text-base font-semibold text-slate-900 leading-tight">
              {title}
            </h2>
            {description && (
              <div id={descId} className="text-sm text-slate-500 mt-2 leading-relaxed">
                {description}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg transition-colors -mr-1 -mt-1 disabled:opacity-50"
          >
            <X size={16} />
          </button>
        </div>

        <div className="bg-slate-50/80 px-5 py-3.5 border-t border-slate-100 flex items-center justify-end gap-2.5">
          <Button
            type="button"
            variant="outline"
            size="md"
            onClick={onClose}
            disabled={isLoading}
            className="min-h-[40px] px-4 font-medium"
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={confirmVariant}
            size="md"
            onClick={() => {
              void onConfirm();
            }}
            isLoading={isLoading}
            className="min-h-[40px] px-4 font-medium shadow-sm"
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
};
