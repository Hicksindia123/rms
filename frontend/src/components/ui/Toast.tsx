import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastType = 'success' | 'error' | 'warning' | 'info' | 'loading';

export interface ToastOptions {
  id?: string | undefined;
  title: string;
  description?: string | undefined;
  type?: ToastType | undefined;
  duration?: number | undefined;
}

export interface ToastItem {
  id: string;
  title: string;
  description?: string | undefined;
  type: ToastType;
  duration: number;
}

interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (options: ToastOptions) => string;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let globalToastHandler: ((options: ToastOptions) => string) | null = null;

/**
 * Imperative global toast API that can be called anywhere (even outside React render tree).
 */
export const toast = {
  show: (options: ToastOptions) => globalToastHandler?.(options) ?? '',
  success: (title: string, description?: string | undefined, options?: Partial<ToastOptions> | undefined) =>
    globalToastHandler?.({
      title,
      type: 'success',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  error: (title: string, description?: string | undefined, options?: Partial<ToastOptions> | undefined) =>
    globalToastHandler?.({
      title,
      type: 'error',
      duration: 6000,
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  warning: (title: string, description?: string | undefined, options?: Partial<ToastOptions> | undefined) =>
    globalToastHandler?.({
      title,
      type: 'warning',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  info: (title: string, description?: string | undefined, options?: Partial<ToastOptions> | undefined) =>
    globalToastHandler?.({
      title,
      type: 'info',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  promise: async <T,>(
    promise: Promise<T>,
    msgs: {
      loading: string;
      success: string | ((data: T) => string);
      error: string | ((err: unknown) => string);
    },
  ): Promise<T> => {
    const id = globalToastHandler?.({
      title: msgs.loading,
      type: 'loading',
      duration: 30000,
    });
    try {
      const data = await promise;
      if (id) {
        toast.dismiss(id);
      }
      const title = typeof msgs.success === 'function' ? msgs.success(data) : msgs.success;
      toast.success(title);
      return data;
    } catch (err) {
      if (id) {
        toast.dismiss(id);
      }
      const title = typeof msgs.error === 'function' ? msgs.error(err) : msgs.error;
      toast.error(title);
      throw err;
    }
  },
  dismiss: (id: string) => {
    const event = new CustomEvent('rms-toast-dismiss', { detail: { id } });
    window.dispatchEvent(event);
  },
};

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      toasts: [],
      toast,
      dismiss: toast.dismiss,
    };
  }
  return {
    toasts: ctx.toasts,
    toast,
    dismiss: ctx.removeToast,
  };
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (options: ToastOptions): string => {
      const id = options.id || `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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
    },
    [],
  );

  useEffect(() => {
    globalToastHandler = addToast;
    const handleDismiss = (e: Event) => {
      const customEvent = e as CustomEvent<{ id: string }>;
      if (customEvent.detail?.id) {
        removeToast(customEvent.detail.id);
      }
    };
    window.addEventListener('rms-toast-dismiss', handleDismiss);
    return () => {
      globalToastHandler = null;
      window.removeEventListener('rms-toast-dismiss', handleDismiss);
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
        <ToastCard key={item.id} item={item} onDismiss={() => onDismiss(item.id)} />
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
    return () => clearTimeout(timer);
  }, [item, onDismiss]);

  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />,
    error: <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />,
    info: <Info className="w-5 h-5 text-sky-600 flex-shrink-0" />,
    loading: <Loader2 className="w-5 h-5 text-blue-600 animate-spin flex-shrink-0" />,
  };

  const borders = {
    success: 'border-emerald-200 bg-white shadow-card',
    error: 'border-rose-200 bg-white shadow-card',
    warning: 'border-amber-200 bg-white shadow-card',
    info: 'border-sky-200 bg-white shadow-card',
    loading: 'border-blue-200 bg-white shadow-card',
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'pointer-events-auto flex items-start gap-3 p-3.5 rounded-xl border bg-white shadow-dialog transition-all duration-200 animate-in fade-in slide-in-from-bottom-2',
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
