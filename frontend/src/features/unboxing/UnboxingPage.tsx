import { useCallback, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  Camera,
  CheckCircle2,
  Clock,
  FileText,
  FileUp,
  Pause,
  Play,
  RotateCcw,
  Trash2,
  Video,
  XCircle,
} from 'lucide-react';

import { Button, ErrorState, LoadingState, Select } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { StatusChip } from '@/features/goods-slips/display';
import { useStatusLabels } from '@/features/goods-slips/statusLabels';
import { formatDateTime } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import { unboxingApi, type Attachment, type GsDocument, type UnboxingState } from './api';
import { CartonDocumentsSection } from './CartonDocumentsSection';
import { AttachmentThumb, VideoPlayer } from './SignedMedia';
import { useUploadQueue, type UploadItem } from './useUploadQueue';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (id: string) => void;
  /** "Next" succeeded: go to item addition (today the counting screen; P4 replaces it). */
  onNext: (id: string) => void;
}

const VIDEO_ACCEPT = 'video/mp4,video/quicktime';

function mb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

/** Step 2a Unboxing (Replacement Executive; status UNBOXING, label from GS_STATUS, AMD-08): one
 * video per carton (G-02, DEC-63: the only requirement), then ONE optional "document found in
 * carton" (type + photos, P3 / DEC-62), then Next → item addition. Document photos classified and
 * Missing Document Exceptions recorded before P3 are shown read-only. */
export function UnboxingPage({ gsId, onBack, onOpenGs, onNext }: Props) {
  const fetcher = useCallback(() => unboxingApi.state(gsId), [gsId]);
  const query = useApiQuery<UnboxingState>(fetcher);
  const state = query.data?.goods_slip.id === gsId ? query.data : null;
  const { me } = useAuth();
  const uploads = useUploadQueue(gsId, query.reload);
  const [busy, setBusy] = useState<'start' | 'complete' | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [completed, setCompleted] = useState<number | null>(null);
  const statusLabel = useStatusLabels();
  const step = statusLabel('UNBOXING');

  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Back
    </Button>
  );

  if (query.error && !state) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">{step}</h1>
        <ErrorState error={query.error} onRetry={query.reload} />
      </div>
    );
  }
  if (!state) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">{step}</h1>
        <LoadingState />
      </div>
    );
  }

  const gs = state.goods_slip;
  const c = state.checklist;
  const canPerform = state.permissions.can_perform;
  const editable = gs.status === 'UNBOXING' && canPerform;
  const videos = state.attachments.filter((a) => a.kind === 'UNBOXING_VIDEO');
  const photos = state.attachments.filter((a) => a.kind === 'DOC_PHOTO');
  const docByAttachment = new Map(state.documents.map((d) => [d.attachment_id, d]));
  const hasCartonDoc = state.gate_documents.some((d) => d.doc_source === 'CARTON');

  const run = async (kind: 'start' | 'complete') => {
    setBusy(kind);
    setActionError(null);
    try {
      if (kind === 'start') {
        query.setData(await unboxingApi.start(gsId));
      } else {
        const res = await unboxingApi.complete(gsId);
        setCompleted(res.notified_user_count);
        onNext(gsId);
      }
    } catch (err) {
      setActionError(toApiError(err));
      query.reload();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page unboxing">
      {back}
      <div className="unboxing__head">
        <div style={{ minWidth: 0 }}>
          <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
            {gs.gs_no}
          </h1>
          <p className="page__subtitle unboxing__sub">
            <StatusChip status={gs.status} />
            <span>
              {[gs.party_name, gs.station_name].filter(Boolean).join(' · ')} · {gs.carton_count}{' '}
              carton{gs.carton_count === 1 ? '' : 's'}
            </span>
          </p>
        </div>
      </div>

      <ChecklistBar checklist={c} hasCartonDoc={hasCartonDoc} />

      {gs.missing_documentation ? (
        <div className="banner" role="status" data-testid="no-party-documents">
          No documents from party were recorded at the gate; Accounts has been alerted. If a carton
          holds a document, add it below.
        </div>
      ) : null}

      {actionError ? (
        <ErrorState
          {...(actionError.code === 'G-02' ? { title: `${step} evidence incomplete (G-02)` } : {})}
          error={actionError}
        />
      ) : null}

      {gs.status === 'GATE_CREATED' ? (
        <section className="card unboxing__section">
          <p style={{ marginTop: 0 }}>
            Start when the cartons are on the table and the camera is ready. Record one continuous
            video per carton.
          </p>
          {canPerform ? (
            <Button
              type="button"
              variant="primary"
              size="lg"
              isLoading={busy === 'start'}
              onClick={() => {
                void run('start');
              }}
            >
              <Play size={18} aria-hidden="true" /> Start {step.toLowerCase()}
            </Button>
          ) : (
            <p className="page__subtitle">
              Waiting for the Inward Verifier to start {step.toLowerCase()}.
            </p>
          )}
        </section>
      ) : null}

      {gs.status !== 'GATE_CREATED' && gs.status !== 'UNBOXING' ? (
        <div className="banner banner--success" role="status" data-testid="unboxing-complete">
          <CheckCircle2 size={18} aria-hidden="true" /> {step} complete — the GS is now{' '}
          <strong>{statusLabel(gs.status)}</strong>.
          {completed !== null ? ` Accounts alerted (${String(completed)}).` : ''}{' '}
          <button
            type="button"
            className="dataview__link"
            onClick={() => {
              onOpenGs(gs.id);
            }}
          >
            Open goods slip
          </button>
        </div>
      ) : null}

      {uploads.active ? (
        <div className="banner banner--warning" role="alert" data-testid="upload-warning">
          Upload in progress — keep this screen open and the phone awake until it finishes.
        </div>
      ) : null}

      {gs.status !== 'GATE_CREATED' ? (
        <>
          <EvidenceSection
            title="Carton videos"
            icon={<Video size={18} aria-hidden="true" />}
            hint={`One continuous video per carton (.mp4 / .mov, up to ${mb(state.limits.max_video_bytes)}).`}
          >
            {editable ? (
              <VideoPicker
                boxCount={gs.carton_count}
                existingVideos={videos}
                maxBytes={state.limits.max_video_bytes}
                onFiles={(files, boxNo) => {
                  uploads.add(files, 'UNBOXING_VIDEO', boxNo);
                }}
              />
            ) : null}
            <UploadList
              items={uploads.items.filter((i) => i.kind === 'UNBOXING_VIDEO')}
              q={uploads}
            />
            {videos.map((v) => (
              <EvidenceRow
                key={v.id}
                attachment={v}
                canDelete={editable && v.uploaded_by === me?.profile.id}
                onDeleted={query.reload}
              >
                <VideoPlayer attachment={v} />
              </EvidenceRow>
            ))}
          </EvidenceSection>

          <CartonDocumentsSection
            gsId={gsId}
            documents={state.gate_documents}
            types={state.document_types}
            editable={editable}
            maxBytes={state.limits.max_document_bytes}
            onChanged={query.reload}
          />

          {photos.length > 0 ? (
            <EvidenceSection
              title="Document photos (recorded earlier)"
              icon={<Camera size={18} aria-hidden="true" />}
              hint="Captured before 20-11-2026. Shown for reference; no longer required (DEC-63)."
            >
              {photos.map((p, index) => (
                <DocumentPhoto
                  key={p.id}
                  index={index + 1}
                  attachment={p}
                  document={docByAttachment.get(p.id) ?? null}
                />
              ))}
            </EvidenceSection>
          ) : null}

          {state.exceptions.length > 0 ? <ExceptionHistory state={state} /> : null}
        </>
      ) : null}

      {gs.status === 'UNBOXING' && canPerform ? (
        <div className="sticky-submit unboxing__complete">
          {!c.video_ok && c.boxes_missing_video.length > 0 ? (
            <div
              className="banner banner--warning"
              style={{
                width: '100%',
                marginBottom: '0.75rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <Clock size={16} aria-hidden="true" />
              <span>
                <strong>Mandatory carton-wise videos:</strong> record an unboxing video for every
                carton. Carton {c.boxes_missing_video.join(', ')} pending.
              </span>
            </div>
          ) : null}
          <Button
            type="button"
            variant="primary"
            size="lg"
            disabled={!c.ready || uploads.active}
            isLoading={busy === 'complete'}
            data-testid="unboxing-next"
            onClick={() => {
              void run('complete');
            }}
          >
            Next <ArrowRight size={18} aria-hidden="true" />
          </Button>
          {!c.ready ? (
            <span className="page__subtitle" data-testid="missing-list">
              Still needed:{' '}
              {[...new Set(c.missing.map((code) => missingText(code, c)))].join(' · ')}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function missingText(code: string, c?: UnboxingState['checklist']): string {
  switch (code) {
    case 'UNBOXING_VIDEO':
    case 'VIDEO_PER_CARTON':
      if (c?.boxes_missing_video && c.boxes_missing_video.length > 0) {
        return `unboxing video for carton ${c.boxes_missing_video.join(', ')}`;
      }
      return 'a video for every carton';
    default:
      return code.toLowerCase().replace(/_/g, ' ');
  }
}

function ChecklistBar({
  checklist: c,
  hasCartonDoc,
}: {
  checklist: UnboxingState['checklist'];
  hasCartonDoc: boolean;
}) {
  // AMD-03 / AMD-08: carton-wise progress, e.g. "Carton videos 1 of 3 (carton 2, 3 missing)".
  // G-02 (DEC-63): the carton videos are the only requirement; the carton document is optional.
  const count = Math.max(1, c.carton_count);
  const missingCartons = c.boxes_missing_video;
  const videoDetail = c.video_ok
    ? `All ${String(count)} carton video${count === 1 ? '' : 's'} confirmed`
    : `Carton videos ${String(c.cartons_with_video)} of ${String(count)}${
        missingCartons.length > 0 ? ` (carton ${missingCartons.join(', ')} missing)` : ''
      }`;
  return (
    <ul className="checklist" aria-label="Unboxing checklist" data-testid="checklist">
      <li className={c.video_ok ? 'chip chip--ok' : 'chip chip--missing'}>
        {c.video_ok ? (
          <CheckCircle2 size={16} aria-hidden="true" />
        ) : (
          <XCircle size={16} aria-hidden="true" />
        )}
        <span>Video {c.video_ok ? '✔' : '✖'}</span>
        <small>{videoDetail}</small>
      </li>
      <li className={hasCartonDoc ? 'chip chip--ok' : 'chip'}>
        <FileText size={16} aria-hidden="true" />
        <span>Carton document</span>
        <small>{hasCartonDoc ? 'added' : 'optional'}</small>
      </li>
    </ul>
  );
}

function EvidenceSection({
  title,
  icon,
  hint,
  children,
}: {
  title: string;
  icon: ReactNode;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section className="card unboxing__section">
      <h2 className="unboxing__h2">
        {icon} {title}
      </h2>
      <p className="page__subtitle" style={{ marginTop: 0 }}>
        {hint}
      </p>
      {children}
    </section>
  );
}

function tooLarge(files: File[], maxBytes: number): string | null {
  const big = files.find((f) => f.size > maxBytes);
  return big ? `${big.name} is ${mb(big.size)}; the limit is ${mb(maxBytes)}.` : null;
}

function VideoPicker({
  boxCount,
  existingVideos = [],
  maxBytes,
  onFiles,
}: {
  boxCount: number;
  existingVideos?: Attachment[];
  maxBytes: number;
  onFiles: (files: File[], boxNo: number) => void;
}) {
  const recordRef = useRef<HTMLInputElement>(null);
  const chooseRef = useRef<HTMLInputElement>(null);

  // Compute set of boxes that already have a video attached
  const recordedBoxSet = useMemo(() => {
    return new Set(
      existingVideos
        .filter((v) => typeof v.box_no === 'number' && v.box_no > 0)
        .map((v) => v.box_no as number),
    );
  }, [existingVideos]);

  // First unrecorded box, fallback to 1
  const firstUnrecorded = useMemo(() => {
    const total = Math.max(1, boxCount);
    for (let i = 1; i <= total; i++) {
      if (!recordedBoxSet.has(i)) return i;
    }
    return 1;
  }, [boxCount, recordedBoxSet]);

  // The carton the user picked; after a video is queued the picker falls back to the first
  // carton still without a video (derived, no effect needed).
  const [picked, setBoxNo] = useState<string | null>(null);
  const boxNo = picked ?? String(firstUnrecorded);
  const [error, setError] = useState<string | null>(null);

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length === 0) return;
    const problem = tooLarge(files, maxBytes);
    setError(problem);
    if (problem) return;
    const targetBox = Number(boxNo) || 1;
    onFiles(files, targetBox);
    setBoxNo(null);
  };

  const totalBoxes = Math.max(1, boxCount);
  const currentBoxNum = Number(boxNo) || 1;

  return (
    <div className="picker">
      <div className="picker__box" style={{ width: '100%' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '0.5rem',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <label
            className="form-label"
            htmlFor="video-box-no"
            style={{ margin: 0, fontWeight: 600 }}
          >
            Carton{' '}
            <span style={{ color: 'var(--color-danger, #ef4444)' }}>* (one video per carton)</span>
          </label>
          <span
            style={{
              fontSize: '0.8125rem',
              color:
                recordedBoxSet.size >= totalBoxes
                  ? 'var(--color-success, #16a34a)'
                  : 'var(--color-muted, #64748b)',
            }}
          >
            <strong>
              {recordedBoxSet.size} of {totalBoxes}
            </strong>{' '}
            carton videos attached
          </span>
        </div>

        {/* Carton selector (AMD-03) */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.5rem',
            marginBottom: '0.75rem',
            padding: '0.625rem',
            background: 'var(--color-bg-subtle, #f8fafc)',
            border: '1px solid var(--color-border, #e2e8f0)',
            borderRadius: '0.5rem',
          }}
          role="group"
          aria-label="Carton video coverage selector"
        >
          {Array.from({ length: totalBoxes }, (_, i) => {
            const num = i + 1;
            const isRecorded = recordedBoxSet.has(num);
            const isSelected = currentBoxNum === num;
            return (
              <button
                key={num}
                type="button"
                onClick={() => {
                  setBoxNo(String(num));
                }}
                style={{
                  padding: '0.375rem 0.75rem',
                  borderRadius: '0.375rem',
                  fontSize: '0.8125rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.375rem',
                  border: isSelected
                    ? '2px solid var(--color-primary, #0284c7)'
                    : '1px solid var(--color-border, #cbd5e1)',
                  background: isSelected
                    ? 'var(--color-primary-light, #e0f2fe)'
                    : isRecorded
                      ? '#f0fdf4'
                      : '#ffffff',
                  color: isSelected
                    ? 'var(--color-primary-dark, #0369a1)'
                    : isRecorded
                      ? '#166534'
                      : '#334155',
                  boxShadow: isSelected ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                }}
              >
                {isRecorded ? (
                  <CheckCircle2 size={14} color="#16a34a" aria-hidden="true" />
                ) : (
                  <Boxes size={14} color={isSelected ? '#0284c7' : '#94a3b8'} aria-hidden="true" />
                )}
                <span>
                  Carton {num} of {totalBoxes}
                </span>
                {isRecorded ? (
                  <span style={{ fontSize: '0.6875rem', opacity: 0.8 }}>(Done)</span>
                ) : (
                  <span style={{ fontSize: '0.6875rem', color: '#dc2626' }}>(Pending)</span>
                )}
              </button>
            );
          })}
        </div>

        <Select
          id="video-box-no"
          value={boxNo}
          onChange={(e) => {
            setBoxNo(e.target.value);
          }}
          options={Array.from({ length: totalBoxes }, (_, i) => {
            const num = i + 1;
            const isRecorded = recordedBoxSet.has(num);
            return {
              value: String(num),
              label: `Carton ${String(num)} of ${String(totalBoxes)}${isRecorded ? ' (✔ Video Attached)' : ' (⏳ Video Pending)'}`,
            };
          })}
        />
      </div>

      <div className="picker__buttons">
        <Button
          type="button"
          variant="primary"
          onClick={() => recordRef.current?.click()}
          data-testid="record-video"
        >
          <Video size={16} aria-hidden="true" /> Record video for carton {boxNo}
        </Button>
        <Button type="button" variant="outline" onClick={() => chooseRef.current?.click()}>
          <FileUp size={16} aria-hidden="true" /> Choose file for carton {boxNo}
        </Button>
      </div>

      {/* capture="environment" opens the phone's rear-camera recorder. */}
      <input
        ref={recordRef}
        type="file"
        accept="video/*"
        capture="environment"
        hidden
        onChange={onChange}
        aria-label={`Record video for carton ${boxNo}`}
      />
      <input
        ref={chooseRef}
        type="file"
        accept={VIDEO_ACCEPT}
        hidden
        onChange={onChange}
        data-testid="video-file-input"
        aria-label={`Choose video file for carton ${boxNo}`}
      />
      {error ? (
        <p role="alert" className="form-control__error">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function UploadList({ items, q }: { items: UploadItem[]; q: ReturnType<typeof useUploadQueue> }) {
  const visible = items.filter((i) => i.phase !== 'done');
  if (visible.length === 0) return null;
  return (
    <ul className="upload-list">
      {visible.map((i) => {
        const pct = i.size > 0 ? Math.min(100, Math.round((i.loaded / i.size) * 100)) : 0;
        return (
          <li key={i.key} className="upload-item" data-testid="upload-item" data-phase={i.phase}>
            <div className="upload-item__row">
              <span className="upload-item__name">{i.fileName}</span>
              <span className="upload-item__meta">
                {i.phase === 'requesting'
                  ? 'Preparing…'
                  : i.phase === 'confirming'
                    ? 'Verifying…'
                    : i.phase === 'paused'
                      ? `Paused · ${String(pct)}%`
                      : i.phase === 'error'
                        ? 'Failed'
                        : `${String(pct)}% of ${mb(i.size)}`}
              </span>
            </div>
            <progress max={100} value={pct} aria-label={`Upload progress for ${i.fileName}`} />
            {i.error ? (
              <p role="alert" className="form-control__error" style={{ margin: '0.25rem 0 0' }}>
                {i.error}
                {i.requestId ? ` (Request ID: ${i.requestId})` : ''}
              </p>
            ) : null}
            <div className="upload-item__actions">
              {i.phase === 'uploading' ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    q.pause(i.key);
                  }}
                >
                  <Pause size={14} aria-hidden="true" /> Pause
                </Button>
              ) : null}
              {i.phase === 'paused' || i.phase === 'error' ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    q.resume(i.key);
                  }}
                >
                  {i.phase === 'paused' ? (
                    <>
                      <Play size={14} aria-hidden="true" /> Resume
                    </>
                  ) : (
                    <>
                      <RotateCcw size={14} aria-hidden="true" /> Retry
                    </>
                  )}
                </Button>
              ) : null}
              {i.phase !== 'confirming' ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void q.cancel(i.key);
                  }}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function DeleteButton({
  attachmentId,
  onDeleted,
}: {
  attachmentId: string;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        isLoading={busy}
        aria-label="Delete file"
        onClick={() => {
          if (!window.confirm('Delete this file? Its classification is removed too.')) return;
          setBusy(true);
          setError(null);
          unboxingApi.remove(attachmentId).then(onDeleted, (err: unknown) => {
            setError(toApiError(err).message);
            setBusy(false);
          });
        }}
      >
        <Trash2 size={14} aria-hidden="true" /> Delete
      </Button>
      {error ? (
        <span role="alert" className="form-control__error">
          {error}
        </span>
      ) : null}
    </>
  );
}

function EvidenceRow({
  attachment,
  canDelete,
  onDeleted,
  children,
}: {
  attachment: Attachment;
  canDelete: boolean;
  onDeleted: () => void;
  children: ReactNode;
}) {
  return (
    <div className="evidence-row" data-testid="evidence-video">
      <div className="evidence-row__meta">
        <strong>{mb(attachment.size_bytes)}</strong>
        {attachment.box_no ? <span> · Carton {attachment.box_no}</span> : null}
        <span>
          {' '}
          · {attachment.uploaded_by_name ?? '—'} · {formatDateTime(attachment.confirmed_at)}
        </span>
      </div>
      {children}
      {canDelete ? <DeleteButton attachmentId={attachment.id} onDeleted={onDeleted} /> : null}
    </div>
  );
}

/** A document photo classified before P3 (read-only history; DEC-63 retired the requirement). */
function DocumentPhoto({
  index,
  attachment,
  document,
}: {
  index: number;
  attachment: Attachment;
  document: GsDocument | null;
}) {
  const summary = document ? documentSummary(document) : [];
  return (
    <article className="doc-photo" data-testid="doc-photo-card">
      <AttachmentThumb attachment={attachment} alt={`Document photo ${String(index)}`} />
      <div className="doc-photo__body">
        <p style={{ margin: 0, fontWeight: 600 }}>
          Photo {index}{' '}
          {document ? (
            <span className="badge badge--success">{document.classification_label}</span>
          ) : (
            <span className="badge">Not classified</span>
          )}
        </p>
        {summary.length > 0 ? (
          <dl className="kv doc-photo__kv">
            {summary.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
    </article>
  );
}

/** Field label / value pairs from the label snapshot stored with the classification (G-18). */
function documentSummary(doc: GsDocument): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const [key, entry] of Object.entries(doc.labels_snapshot)) {
    if (key === 'doc_classification') continue;
    const raw = entry.value_label ?? entry.value;
    if (raw === null || raw === undefined || raw === '') continue;
    let text: string;
    if (typeof raw === 'boolean') text = raw ? 'Yes' : 'No';
    else if (typeof raw === 'string') text = raw;
    else if (typeof raw === 'number') text = String(raw);
    else text = JSON.stringify(raw);
    out.push([entry.label, text]);
  }
  return out;
}

/** DEC-03 Missing Document Exceptions recorded before DEC-63 (2026-11-20): read-only history. */
function ExceptionHistory({ state }: { state: UnboxingState }) {
  const parcels = new Map(
    state.attachments.filter((a) => a.kind === 'PARCEL_PHOTO').map((a) => [a.id, a]),
  );
  return (
    <EvidenceSection
      title="Missing Document Exception (retired)"
      icon={<FileUp size={18} aria-hidden="true" />}
      hint="Recorded before 20-11-2026. No approval is needed any more (DEC-63)."
    >
      {state.exceptions.map((e) => {
        const parcel = parcels.get(e.parcel_attachment_id);
        return (
          <div key={e.id} className="evidence-row" data-testid="exception-history">
            <div className="evidence-row__meta">
              <strong>{e.status.toLowerCase()}</strong>
              <span>
                {' '}
                · {e.requested_by_name ?? '—'} · {formatDateTime(e.requested_at)}
              </span>
            </div>
            <p style={{ margin: 0 }}>“{e.remark}”</p>
            {e.decided_by_name ? (
              <p className="page__subtitle" style={{ margin: 0 }}>
                {e.decided_by_name}
                {e.decision_remarks ? `: ${e.decision_remarks}` : ''}
              </p>
            ) : null}
            {parcel ? <AttachmentThumb attachment={parcel} alt="Parcel photo" /> : null}
          </div>
        );
      })}
    </EvidenceSection>
  );
}
