/**
 * Client-side downscale of document photos before upload (P2-03): phone cameras produce 8–20 MB
 * images; the long edge is capped while staying legible ("high-resolution picture", DD r16).
 * PDFs and HEIC (which most browsers cannot decode) are uploaded unchanged.
 */
export const MAX_EDGE_PX = 2560;
const JPEG_QUALITY = 0.85;
const SMALL_ENOUGH_BYTES = 1.5 * 1024 * 1024;

export function canDownscale(type: string): boolean {
  return type === 'image/jpeg' || type === 'image/png';
}

export function scaledSize(width: number, height: number, maxEdge = MAX_EDGE_PX) {
  const longest = Math.max(width, height);
  if (longest <= maxEdge) return { width, height };
  const ratio = maxEdge / longest;
  return { width: Math.round(width * ratio), height: Math.round(height * ratio) };
}

export async function downscaleImage(file: File, maxEdge = MAX_EDGE_PX): Promise<File> {
  if (!canDownscale(file.type) || typeof createImageBitmap !== 'function') return file;
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  try {
    const target = scaledSize(bitmap.width, bitmap.height, maxEdge);
    if (target.width === bitmap.width && file.size <= SMALL_ENOUGH_BYTES) return file;
    const canvas = document.createElement('canvas');
    canvas.width = target.width;
    canvas.height = target.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, target.width, target.height);
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY);
    });
    if (!blob || blob.size >= file.size) return file;
    const base = file.name.replace(/\.[^.]+$/, '') || 'document';
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg', lastModified: Date.now() });
  } finally {
    bitmap.close();
  }
}
