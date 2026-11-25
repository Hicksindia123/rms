import React, { useState, useCallback, useEffect } from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  TOAST_DISMISS_EVENT,
  ToastContext,
  setGlobalToastHandler,
  type ToastItem,
  type ToastOptions,
} from './toast-api';

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((options: ToastOptions): string => {
    const id =
      options.id || `toast-${String(Date.now())}-${Math.random().toString(36).slice(2, 7)}`;
    const newToast: ToastItem = {
      id,
      title: options.title,
      ...(options.description !== undefined ? { description: options.description } : {}),
      type: options.type || 'info',
      duration: options.duration ?? (options.type === 'error' ? 6000 : 4000),
    };

    setToasts((prev) => {
      const filtered = prev.filter((t) => t.id !== id);
      return [...filtered, newToast];
    });

    return id;
  }, []);

  useEffect(() => {
    setGlobalToastHandler(addToast);
    const handleDismiss = (e: Event) => {
      const customEvent = e as CustomEvent<{ id: string } | null>;
      if (customEvent.detail?.id) {
        removeToast(customEvent.detail.id);
      }
    };
    window.addEventListener(TOAST_DISMISS_EVENT, handleDismiss);
    return () => {
      setGlobalToastHandler(null);
      window.removeEventListener(TOAST_DISMISS_EVENT, handleDismiss);
    };
  }, [addToast, removeToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      <ToasterContainer toasts={toasts} onDismiss={removeToast} />
    </ToastContext.Provider>
  );
};

const ToasterContainer: React.FC<{
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}> = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm w-full pointer-events-none p-2 sm:p-0"
    >
      {toasts.map((item) => (
        <ToastCard
          key={item.id}
          item={item}
          onDismiss={() => {
            onDismiss(item.id);
          }}
        />
      ))}
    </div>
  );
};

const ToastCard: React.FC<{
  item: ToastItem;
  onDismiss: () => void;
}> = ({ item, onDismiss }) => {
  useEffect(() => {
    if (item.type === 'loading' || item.duration === 0) return;
    const timer = setTimeout(() => {
      onDismiss();
    }, item.duration);
    return () => {
      clearTimeout(timer);
    };
  }, [item, onDismiss]);

  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />,
    error: <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />,
    info: <Info className="w-5 h-5 text-brand-600 flex-shrink-0" />,
    loading: <Loader2 className="w-5 h-5 text-blue-600 animate-spin flex-shrink-0" />,
  };

  const borders = {
    success: 'border-emerald-200 border-l-emerald-500',
    error: 'border-rose-200 border-l-rose-500',
    warning: 'border-amber-200 border-l-amber-500',
    info: 'border-brand-200 border-l-brand-500',
    loading: 'border-brand-200 border-l-brand-500',
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'pointer-events-auto flex items-start gap-3 p-4 rounded-2xl border border-l-4 bg-white/95 backdrop-blur shadow-[0_18px_40px_-16px_rgba(11,18,48,0.35)] transition-all duration-200 animate-fade-up',
        borders[item.type],
      )}
    >
      {icons[item.type]}
      <div className="flex-1 min-w-0 pt-0.5">
        <p className="text-sm font-semibold text-slate-900 leading-tight">{item.title}</p>
        {item.description && (
          <p className="text-xs text-slate-500 mt-1 leading-normal break-words">
            {item.description}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Close notification"
        className="text-slate-400 hover:text-slate-700 p-1 rounded-lg transition-colors -mr-1 -mt-1"
      >
        <X size={15} />
      </button>
    </div>
  );
};
