import * as tus from 'tus-js-client';

import type { UploadTicket } from './api';

/**
 * Moves one file to Supabase Storage with the ticket the backend issued (P2-03, §8.8):
 *  - SIGNED_PUT: a single PUT to the signed upload URL (photos, small videos). Pausing aborts the
 *    request; resuming restarts it.
 *  - TUS: Supabase resumable upload (videos above the configured threshold) in 6 MB chunks with
 *    automatic retries. Pause / resume continue from the last acknowledged chunk.
 * The object path is fixed by the ticket (server generated); the browser never chooses it.
 */
export interface TransferHandlers {
  onProgress: (loaded: number, total: number) => void;
  onSuccess: () => void;
  onError: (message: string) => void;
}

export interface Transfer {
  readonly resumable: boolean;
  start: () => void;
  pause: () => void;
  abort: () => void;
}

const TUS_RETRY_DELAYS = [0, 3000, 5000, 10000, 20000];

export function createTransfer(
  file: Blob,
  ticket: UploadTicket,
  contentType: string,
  handlers: TransferHandlers,
): Transfer {
  return ticket.method === 'TUS'
    ? tusTransfer(file, ticket, handlers)
    : putTransfer(file, ticket.url, contentType, handlers);
}

function putTransfer(
  file: Blob,
  url: string,
  contentType: string,
  handlers: TransferHandlers,
): Transfer {
  let xhr: XMLHttpRequest | null = null;
  return {
    resumable: false,
    start() {
      const request = new XMLHttpRequest();
      xhr = request;
      request.open('PUT', url);
      request.setRequestHeader('Content-Type', contentType);
      request.setRequestHeader('x-upsert', 'false');
      request.upload.onprogress = (e) => {
        if (e.lengthComputable) handlers.onProgress(e.loaded, e.total);
      };
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) {
          handlers.onProgress(file.size, file.size);
          handlers.onSuccess();
        } else {
          handlers.onError(storageMessage(request.responseText, request.status));
        }
      };
      request.onerror = () => {
        handlers.onError('Network error while uploading. Check the connection and retry.');
      };
      request.send(file);
    },
    pause() {
      xhr?.abort();
    },
    abort() {
      xhr?.abort();
    },
  };
}

function tusTransfer(
  file: Blob,
  ticket: Extract<UploadTicket, { method: 'TUS' }>,
  handlers: TransferHandlers,
): Transfer {
  const upload = new tus.Upload(file, {
    endpoint: ticket.endpoint,
    chunkSize: ticket.chunk_size,
    retryDelays: TUS_RETRY_DELAYS,
    uploadDataDuringCreation: true,
    removeFingerprintOnSuccess: true,
    headers: { 'x-signature': ticket.token },
    metadata: {
      bucketName: ticket.bucket,
      objectName: ticket.object_path,
      contentType: ticket.content_type,
      cacheControl: '3600',
    },
    onProgress: (loaded, total) => {
      handlers.onProgress(loaded, total);
    },
    onSuccess: () => {
      handlers.onSuccess();
    },
    onError: (err) => {
      handlers.onError(err.message || 'Upload failed');
    },
  });
  return {
    resumable: true,
    start() {
      upload.start();
    },
    pause() {
      void upload.abort(false);
    },
    abort() {
      void upload.abort(true);
    },
  };
}

function storageMessage(body: string, status: number): string {
  try {
    const parsed = JSON.parse(body) as { message?: string; error?: string };
    const msg = parsed.message ?? parsed.error;
    if (msg) return `Storage rejected the upload: ${msg}`;
  } catch {
    // Not JSON: fall through to the status text below.
  }
  return `Storage rejected the upload (HTTP ${String(status)})`;
}
