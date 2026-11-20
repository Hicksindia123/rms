import { toApiError } from '@/lib/api/client';
import { createTransfer } from '@/features/unboxing/uploader';

import { gsApi } from './api';

/** A document file to upload to an existing document row. */
export interface UploadItem {
  documentId: string;
  file: File;
}

/** A document file that could not be uploaded (the document row itself is saved). */
export interface PendingFile extends UploadItem {
  error: string;
}

/** Per-file progress: `index` is the position in the `items` list, `percent` 0–100. */
export type UploadProgressHandler = (index: number, percent: number) => void;

async function uploadOne(
  gsId: string,
  documentId: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  const ticket = await gsApi.gateDocUploadUrl(gsId, documentId, {
    mime_type: file.type || 'application/octet-stream',
    size_bytes: file.size,
    file_name: file.name,
  });
  await new Promise<void>((resolve, reject) => {
    createTransfer(file, ticket.upload, ticket.attachment.mime_type, {
      onProgress: (loaded, total) => {
        if (total > 0) onProgress(Math.min(99, Math.round((loaded / total) * 100)));
      },
      onSuccess: resolve,
      onError: (message) => {
        reject(new Error(message));
      },
    }).start();
  });
  await gsApi.confirmUpload(ticket.attachment.id, ticket.upload.object_path);
  onProgress(100);
}

/** AMD-04: files of document rows (gate or carton opening) are uploaded after the row exists
 * (signed URL per file, then confirmed). Failures are returned for a retry, never swallowed.
 * DEC-62: `onProgress` reports each file's progress (gate summary sheet). */
export async function uploadDocumentFiles(
  gsId: string,
  items: UploadItem[],
  onProgress?: UploadProgressHandler,
): Promise<PendingFile[]> {
  const failed: PendingFile[] = [];
  for (const [index, item] of items.entries()) {
    try {
      onProgress?.(index, 0);
      await uploadOne(gsId, item.documentId, item.file, (percent) => {
        onProgress?.(index, percent);
      });
    } catch (err) {
      const apiErr = toApiError(err);
      console.error('Gate document file upload failed', { gsId, file: item.file.name, err });
      failed.push({ documentId: item.documentId, file: item.file, error: apiErr.message });
    }
  }
  return failed;
}
