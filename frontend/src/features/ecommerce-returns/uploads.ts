import { createTransfer } from '@/features/unboxing/uploader';

import { ecomApi } from './api';
import type { FormConfig, Media, MediaUpload } from './types';

/** Upload one file to its signed URL (PUT, or TUS for large videos) and confirm it against
 * storage. Same mechanics as the offline attachments; errors are thrown, never swallowed. */
export async function uploadAndConfirm(
  returnId: string,
  ticket: MediaUpload,
  file: File,
  onProgress: (percent: number) => void,
): Promise<Media> {
  await new Promise<void>((resolve, reject) => {
    createTransfer(file, ticket.upload, ticket.media.mime_type, {
      onProgress: (loaded, total) => {
        if (total > 0) onProgress(Math.min(99, Math.round((loaded / total) * 100)));
      },
      onSuccess: resolve,
      onError: (message) => {
        reject(new Error(message));
      },
    }).start();
  });
  const confirmed = await ecomApi.confirm(returnId, ticket.media.id, ticket.upload.object_path);
  onProgress(100);
  return confirmed;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${String(Math.max(1, Math.round(bytes / 1024)))} KB`;
}

/** Browsers often leave `type` empty for .mov / .heic; fall back to the extension. */
export function mimeOf(file: File, allowed: { mime_types: string[] }): string {
  if (file.type) return file.type.toLowerCase();
  const ext = file.name.toLowerCase().split('.').pop() ?? '';
  const byExt: Record<string, string> = {
    mp4: 'video/mp4',
    mov: 'video/quicktime',
    qt: 'video/quicktime',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    heic: 'image/heic',
    heif: 'image/heif',
  };
  const guess = byExt[ext] ?? '';
  return allowed.mime_types.includes(guess) ? guess : '';
}

/** Client-side mirror of the server rules (the server checks again). */
export function checkVideo(file: File | null, cfg: FormConfig): string | null {
  if (!file) return 'The package opening video is required';
  if (!cfg.video.mime_types.includes(mimeOf(file, cfg.video))) {
    return `Choose a video file (${cfg.video.extensions.map((e) => `.${e}`).join(', ')})`;
  }
  if (file.size <= 0) return 'The video file is empty';
  if (file.size > cfg.video.max_bytes) {
    return `The video is ${formatBytes(file.size)}; the limit is ${formatBytes(cfg.video.max_bytes)}`;
  }
  return null;
}

export function checkImages(files: File[], cfg: FormConfig): string | null {
  for (const f of files) {
    if (!cfg.images.mime_types.includes(mimeOf(f, cfg.images))) {
      return `${f.name}: choose an image (${cfg.images.extensions.map((e) => `.${e}`).join(', ')})`;
    }
    if (f.size > cfg.images.max_bytes_each) {
      return `${f.name} is ${formatBytes(f.size)}; each image can be at most ${formatBytes(cfg.images.max_bytes_each)}`;
    }
  }
  const total = files.reduce((n, f) => n + f.size, 0);
  if (total > cfg.images.max_total_bytes) {
    return `Images total ${formatBytes(total)}; the limit is ${formatBytes(cfg.images.max_total_bytes)} together`;
  }
  return null;
}
