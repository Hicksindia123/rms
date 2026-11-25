import { createContext, useContext } from 'react';

/**
 * Toast API (types, context, imperative `toast` helper and `useToast` hook).
 * Kept apart from Toast.tsx so that file only exports components (react-refresh).
 */

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

export interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (options: ToastOptions) => string;
  removeToast: (id: string) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export const TOAST_DISMISS_EVENT = 'rms-toast-dismiss';

let globalToastHandler: ((options: ToastOptions) => string) | null = null;

/** Registered by ToastProvider on mount, cleared on unmount. */
export function setGlobalToastHandler(handler: ((options: ToastOptions) => string) | null): void {
  globalToastHandler = handler;
}

/**
 * Imperative global toast API that can be called anywhere (even outside React render tree).
 */
export const toast = {
  show: (options: ToastOptions) => globalToastHandler?.(options) ?? '',
  success: (title: string, description?: string, options?: Partial<ToastOptions>) =>
    globalToastHandler?.({
      title,
      type: 'success',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  error: (title: string, description?: string, options?: Partial<ToastOptions>) =>
    globalToastHandler?.({
      title,
      type: 'error',
      duration: 6000,
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  warning: (title: string, description?: string, options?: Partial<ToastOptions>) =>
    globalToastHandler?.({
      title,
      type: 'warning',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  info: (title: string, description?: string, options?: Partial<ToastOptions>) =>
    globalToastHandler?.({
      title,
      type: 'info',
      ...(description !== undefined ? { description } : {}),
      ...(options ?? {}),
    }) ?? '',
  promise: async <T>(
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
    const event = new CustomEvent(TOAST_DISMISS_EVENT, { detail: { id } });
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
