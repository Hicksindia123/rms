import React, { useEffect, useId } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  children,
  footer,
  size = 'md',
}) => {
  const titleId = useId();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
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
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const sizeClasses = {
    sm: 'max-w-sm',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-5 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={cn(
          'w-full bg-white rounded-2xl shadow-dialog border border-slate-200/80 max-h-[92vh] flex flex-col overflow-hidden transition-all transform animate-in zoom-in-95 duration-150',
          sizeClasses[size],
        )}
      >
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-3 flex-shrink-0 bg-slate-50/50">
          <h2 id={titleId} className="text-base font-semibold text-slate-900 leading-snug">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-700 hover:bg-slate-100 p-2 rounded-lg transition-colors -mr-1.5 min-w-[36px] min-h-[36px] flex items-center justify-center"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-5 sm:p-6 overflow-y-auto flex-1 custom-scrollbar text-sm text-slate-700 leading-relaxed">
          {children}
        </div>

        {footer ? (
          <div className="px-5 py-3.5 border-t border-slate-100 bg-slate-50/80 flex items-center justify-end gap-2.5 flex-shrink-0">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
};
