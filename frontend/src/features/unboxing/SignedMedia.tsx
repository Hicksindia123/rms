import { useCallback, useEffect, useState } from 'react';
import { FileText, ImageOff, Play } from 'lucide-react';

import { Button } from '@/components/ui';
import { toApiError } from '@/lib/api/client';

import { unboxingApi, type Attachment } from './api';

/**
 * Private-bucket media through short-lived signed URLs (§8.8): the URL is fetched from the API
 * (per-GS permission check, audited) right before display and re-fetched once if it has expired.
 */
function useSignedUrl(attachmentId: string, enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    unboxingApi.downloadUrl(attachmentId).then(
      (res) => {
        if (active) setUrl(res.url);
      },
      (err: unknown) => {
        if (active) setError(toApiError(err).message);
      },
    );
    return () => {
      active = false;
    };
  }, [attachmentId, enabled, attempt]);

  const refresh = useCallback(() => {
    setUrl(null);
    setError(null);
    setAttempt((a) => a + 1);
  }, []);
  return { url, error, refresh, attempt };
}

export function AttachmentThumb({ attachment, alt }: { attachment: Attachment; alt: string }) {
  const isPdf = attachment.mime_type === 'application/pdf';
  const previewable = !isPdf && !attachment.preview_unsupported;
  const { url, error, refresh, attempt } = useSignedUrl(
    attachment.id,
    attachment.status === 'CONFIRMED',
  );

  if (!previewable) {
    return (
      <a
        className="thumb thumb--icon"
        href={url ?? undefined}
        target="_blank"
        rel="noreferrer"
        aria-label={`Open ${alt}`}
      >
        {isPdf ? (
          <FileText size={28} aria-hidden="true" />
        ) : (
          <ImageOff size={28} aria-hidden="true" />
        )}
        <span>{isPdf ? 'PDF' : 'HEIC (no preview)'}</span>
      </a>
    );
  }
  if (error) {
    return (
      <button type="button" className="thumb thumb--icon" onClick={refresh} title={error}>
        <ImageOff size={24} aria-hidden="true" />
        <span>Retry</span>
      </button>
    );
  }
  if (!url) return <div className="thumb thumb--loading" aria-label="Loading preview" />;
  return (
    <a className="thumb" href={url} target="_blank" rel="noreferrer">
      <img
        src={url}
        alt={alt}
        loading="lazy"
        onError={() => {
          if (attempt < 1) refresh(); // expired signed URL → fetch a new one once
        }}
      />
    </a>
  );
}

export function VideoPlayer({ attachment }: { attachment: Attachment }) {
  const [open, setOpen] = useState(false);
  const { url, error, refresh, attempt } = useSignedUrl(attachment.id, open);
  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          setOpen(true);
        }}
      >
        <Play size={16} aria-hidden="true" /> Play video
      </Button>
    );
  }
  if (error) {
    return (
      <p role="alert" className="form-control__error">
        {error}{' '}
        <Button type="button" size="sm" variant="ghost" onClick={refresh}>
          Retry
        </Button>
      </p>
    );
  }
  if (!url) return <div className="thumb thumb--loading" aria-label="Loading video" />;
  return (
    <video
      className="evidence-video"
      src={url}
      controls
      playsInline
      preload="metadata"
      onError={() => {
        if (attempt < 1) refresh();
      }}
    />
  );
}

/** Full-width document photo for counting items against the paper (P2-04 document viewer). */
export function DocumentImage({ attachment, alt }: { attachment: Attachment; alt: string }) {
  const isPdf = attachment.mime_type === 'application/pdf';
  const previewable = !isPdf && !attachment.preview_unsupported;
  const { url, error, refresh, attempt } = useSignedUrl(
    attachment.id,
    attachment.status === 'CONFIRMED',
  );
  if (error) {
    return (
      <p role="alert" className="form-control__error">
        {error}{' '}
        <Button type="button" size="sm" variant="ghost" onClick={refresh}>
          Retry
        </Button>
      </p>
    );
  }
  if (!url) return <div className="doc-image doc-image--loading" aria-label="Loading document" />;
  if (!previewable) {
    return (
      <a className="thumb thumb--icon" href={url} target="_blank" rel="noreferrer">
        {isPdf ? (
          <FileText size={28} aria-hidden="true" />
        ) : (
          <ImageOff size={28} aria-hidden="true" />
        )}
        <span>{isPdf ? 'Open PDF' : 'Open file'}</span>
      </a>
    );
  }
  return (
    <a href={url} target="_blank" rel="noreferrer" className="doc-image">
      <img
        src={url}
        alt={alt}
        loading="lazy"
        onError={() => {
          if (attempt < 1) refresh();
        }}
      />
    </a>
  );
}
