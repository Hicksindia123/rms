import { useCallback, useEffect, useRef, useState } from 'react';

import { toApiError } from '@/lib/api/client';

import { unboxingApi, type UploadKind } from './api';
import { createTransfer, type Transfer } from './uploader';

export type UploadPhase = 'requesting' | 'uploading' | 'paused' | 'confirming' | 'error' | 'done';

export interface UploadItem {
  key: string;
  kind: UploadKind;
  fileName: string;
  size: number;
  loaded: number;
  phase: UploadPhase;
  error: string | null;
  requestId: string | null;
  attachmentId: string | null;
  resumable: boolean;
}

interface Entry {
  file: File;
  kind: UploadKind;
  boxNo: number | undefined;
  transfer: Transfer | null;
  objectPath: string | null;
}

/**
 * Upload pipeline per file: request a ticket (backend validates kind / MIME / size) → transfer
 * (signed PUT or TUS) → confirm (backend re-checks path, size and MIME). `onUploaded` runs after a
 * successful confirmation so the screen reloads the authoritative checklist.
 */
export function useUploadQueue(gsId: string, onUploaded: () => void) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const entries = useRef(new Map<string, Entry>());
  const onUploadedRef = useRef(onUploaded);
  useEffect(() => {
    onUploadedRef.current = onUploaded;
  }, [onUploaded]);

  const patch = useCallback((key: string, change: Partial<UploadItem>) => {
    setItems((list) => list.map((i) => (i.key === key ? { ...i, ...change } : i)));
  }, []);

  const confirm = useCallback(
    async (key: string, attachmentId: string, objectPath: string | null) => {
      patch(key, { phase: 'confirming' });
      try {
        await unboxingApi.confirm(attachmentId, objectPath ?? undefined);
        patch(key, { phase: 'done', error: null });
        entries.current.delete(key);
        onUploadedRef.current();
      } catch (err) {
        const e = toApiError(err);
        patch(key, { phase: 'error', error: e.message, requestId: e.requestId });
      }
    },
    [patch],
  );

  const transfer = useCallback(
    (key: string) => {
      const entry = entries.current.get(key);
      if (!entry?.transfer) return;
      patch(key, { phase: 'uploading', error: null });
      entry.transfer.start();
    },
    [patch],
  );

  const begin = useCallback(
    async (key: string) => {
      const entry = entries.current.get(key);
      if (!entry) return;
      patch(key, { phase: 'requesting', error: null, requestId: null });
      try {
        const ticket = await unboxingApi.uploadUrl(gsId, {
          kind: entry.kind,
          mime_type: entry.file.type,
          size_bytes: entry.file.size,
          file_name: entry.file.name,
          ...(entry.boxNo ? { box_no: entry.boxNo } : {}),
        });
        const attachmentId = ticket.attachment.id;
        entry.objectPath = ticket.upload.object_path;
        entry.transfer = createTransfer(entry.file, ticket.upload, entry.file.type, {
          onProgress: (loaded) => {
            patch(key, { loaded });
          },
          onSuccess: () => {
            void confirm(key, attachmentId, entry.objectPath);
          },
          onError: (message) => {
            patch(key, { phase: 'error', error: message });
          },
        });
        patch(key, { attachmentId, resumable: entry.transfer.resumable });
        transfer(key);
      } catch (err) {
        const e = toApiError(err);
        patch(key, { phase: 'error', error: e.message, requestId: e.requestId });
      }
    },
    [gsId, patch, confirm, transfer],
  );

  const add = useCallback(
    (files: File[], kind: UploadKind, boxNo?: number) => {
      const added: UploadItem[] = files.map((file) => {
        const key = `${kind}-${crypto.randomUUID()}`;
        entries.current.set(key, { file, kind, boxNo, transfer: null, objectPath: null });
        return {
          key,
          kind,
          fileName: file.name,
          size: file.size,
          loaded: 0,
          phase: 'requesting',
          error: null,
          requestId: null,
          attachmentId: null,
          resumable: false,
        };
      });
      setItems((list) => [...list, ...added]);
      for (const a of added) void begin(a.key);
    },
    [begin],
  );

  const pause = useCallback(
    (key: string) => {
      entries.current.get(key)?.transfer?.pause();
      patch(key, { phase: 'paused' });
    },
    [patch],
  );

  /** Resume a paused transfer, or retry whichever stage failed. */
  const resume = useCallback(
    (key: string) => {
      const entry = entries.current.get(key);
      const item = items.find((i) => i.key === key);
      if (!entry || !item) return;
      if (!item.attachmentId || !entry.transfer) {
        void begin(key);
      } else if (item.loaded >= item.size && item.phase === 'error') {
        void confirm(key, item.attachmentId, entry.objectPath);
      } else {
        transfer(key);
      }
    },
    [items, begin, confirm, transfer],
  );

  /** Stop and discard: the PENDING row is deleted (the worker would remove it after 24 h). */
  const cancel = useCallback(
    async (key: string) => {
      const entry = entries.current.get(key);
      entry?.transfer?.abort();
      const item = items.find((i) => i.key === key);
      entries.current.delete(key);
      setItems((list) => list.filter((i) => i.key !== key));
      if (item?.attachmentId && item.phase !== 'done') {
        try {
          await unboxingApi.remove(item.attachmentId);
        } catch (err) {
          console.warn('Pending upload could not be discarded', toApiError(err).message);
        }
      }
    },
    [items],
  );

  const clearDone = useCallback(() => {
    setItems((list) => list.filter((i) => i.phase !== 'done'));
  }, []);

  const active = items.some((i) => i.phase !== 'done' && i.phase !== 'error');

  // Closing or reloading the tab would cut an upload off: ask first while one is running.
  useEffect(() => {
    if (!active) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => {
      window.removeEventListener('beforeunload', handler);
    };
  }, [active]);

  return { items, add, pause, resume, cancel, clearDone, active };
}
