import { toApiError } from '@/lib/api/client';
import { createTransfer } from '@/features/unboxing/uploader';

import { gsApi } from './api';

/** A document file that could not be uploaded (the document row itself is saved). */
export interface PendingFile {
  documentId: string;
  file: File;
  error: string;
}

async function uploadOne(gsId: string, documentId: string, file: File): Promise<void> {
  const ticket = await gsApi.gateDocUploadUrl(gsId, documentId, {
    mime_type: file.type || 'application/octet-stream',
    size_bytes: file.size,
    file_name: file.name,
  });
  await new Promise<void>((resolve, reject) => {
    createTransfer(file, ticket.upload, ticket.attachment.mime_type, {
      onProgress: () => undefined,
      onSuccess: resolve,
      onError: (message) => {
        reject(new Error(message));
      },
    }).start();
  });
  await gsApi.confirmUpload(ticket.attachment.id, ticket.upload.object_path);
}

/** AMD-04: files of document rows (gate or carton opening) are uploaded after the row exists
 * (signed URL per file, then confirmed). Failures are returned for a retry, never swallowed. */
export async function uploadDocumentFiles(
  gsId: string,
  items: Array<{ documentId: string; file: File }>,
): Promise<PendingFile[]> {
  const failed: PendingFile[] = [];
  for (const item of items) {
    try {
      await uploadOne(gsId, item.documentId, item.file);
    } catch (err) {
      const apiErr = toApiError(err);
      console.error('Gate document file upload failed', { gsId, file: item.file.name, err });
      failed.push({ ...item, error: apiErr.message });
    }
  }
  return failed;
}
