import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import {
  ArrowLeft,
  Boxes,
  Camera,
  CheckCircle2,
  Clock,
  FileUp,
  Pause,
  Play,
  RotateCcw,
  Trash2,
  Video,
  XCircle,
} from 'lucide-react';

import { DynamicForm } from '@/components/erp';
import { Button, ErrorState, LoadingState, Select, Textarea } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { StatusChip } from '@/features/goods-slips/display';
import { useStatusLabels } from '@/features/goods-slips/statusLabels';
import { formatDateTime } from '@/features/goods-slips/format';
import { toDynamicFormSnapshot } from '@/features/goods-slips/snapshot';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  unboxingApi,
  type Attachment,
  type GsDocument,
  type MissingDocException,
  type UnboxingState,
} from './api';
import { CartonDocumentsSection } from './CartonDocumentsSection';
import { ExceptionDecisionCard } from './ExceptionDecisionCard';
import { downscaleImage } from './imageDownscale';
import { AttachmentThumb, VideoPlayer } from './SignedMedia';
import { useUploadQueue, type UploadItem } from './useUploadQueue';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (id: string) => void;
}

const VIDEO_ACCEPT = 'video/mp4,video/quicktime';
const PHOTO_ACCEPT = 'image/jpeg,image/png,image/heic,image/heif';
const DOC_ACCEPT = `${PHOTO_ACCEPT},application/pdf`;

function mb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

/** Step-2 Carton Opening (Aman; status UNBOXING, label from GS_STATUS, AMD-08): one video per
 * carton (G-02, AMD-03), document photos + classification, more document rows (AMD-04). */
export function UnboxingPage({ gsId, onBack, onOpenGs }: Props) {
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
  const parcels = state.attachments.filter((a) => a.kind === 'PARCEL_PHOTO');
  const docByAttachment = new Map(state.documents.map((d) => [d.attachment_id, d]));

  const run = async (kind: 'start' | 'complete') => {
    setBusy(kind);
    setActionError(null);
    try {
      if (kind === 'start') {
        query.setData(await unboxingApi.start(gsId));
      } else {
        const res = await unboxingApi.complete(gsId);
        setCompleted(res.notified_user_count);
        query.reload();
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

      <ChecklistBar checklist={c} />

      {gs.missing_documentation ? (
        <div className="banner" role="status">
          {gs.gate_document_label ?? 'No Document Attached'} at the gate: photograph the parcel
          label or outer box, add a remark and request a Missing Document Exception (DEC-03).
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

          <EvidenceSection
            title="Document photos"
            icon={<Camera size={18} aria-hidden="true" />}
            hint="Photograph every paper document in the parcel, then classify each photo."
          >
            {editable ? (
              <PhotoPicker
                label="Photograph documents"
                accept={DOC_ACCEPT}
                maxBytes={state.limits.max_document_bytes}
                testId="doc-photo"
                onFiles={(files) => {
                  uploads.add(files, 'DOC_PHOTO');
                }}
              />
            ) : null}
            <UploadList items={uploads.items.filter((i) => i.kind === 'DOC_PHOTO')} q={uploads} />
            {photos.length === 0 && !editable ? (
              <p className="page__subtitle">No document photos.</p>
            ) : null}
            {photos.map((p, index) => (
              <DocumentPhoto
                key={p.id}
                index={index + 1}
                gsId={gsId}
                attachment={p}
                document={docByAttachment.get(p.id) ?? null}
                state={state}
                editable={editable}
                canDelete={editable && p.uploaded_by === me?.profile.id}
                onChanged={query.reload}
              />
            ))}
          </EvidenceSection>

          {!gs.missing_documentation ? (
            <CartonDocumentsSection
              gsId={gsId}
              documents={state.gate_documents}
              types={state.document_types}
              editable={editable}
              maxBytes={state.limits.max_document_bytes}
              onChanged={query.reload}
            />
          ) : null}

          {gs.missing_documentation ? (
            <MissingDocSection
              gsId={gsId}
              state={state}
              parcels={parcels}
              editable={editable}
              uploads={uploads}
              myId={me?.profile.id ?? null}
              onChanged={query.reload}
              onOpenGs={onOpenGs}
            />
          ) : null}
        </>
      ) : null}

      {gs.status === 'UNBOXING' && canPerform ? (
        <div className="sticky-submit unboxing__complete">
          {!c.video_ok && c.boxes_missing_video && c.boxes_missing_video.length > 0 ? (
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
            onClick={() => {
              void run('complete');
            }}
          >
            Complete {step.toLowerCase()}
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
    case 'CLASSIFIED_DOC_PHOTO':
      return 'a classified document photo';
    case 'UNCLASSIFIED_DOC_PHOTO':
      return 'classify every document photo';
    case 'MISSING_DOC_EXCEPTION':
      return 'approved Missing Document Exception';
    default:
      return code.toLowerCase().replace(/_/g, ' ');
  }
}

function ChecklistBar({ checklist: c }: { checklist: UnboxingState['checklist'] }) {
  // AMD-03 / AMD-08: carton-wise progress, e.g. "Carton videos 1 of 3 (carton 2, 3 missing)".
  const count = Math.max(1, c.carton_count);
  const missingCartons = c.boxes_missing_video;
  const videoDetail = c.video_ok
    ? `All ${String(count)} carton video${count === 1 ? '' : 's'} confirmed`
    : `Carton videos ${String(c.cartons_with_video)} of ${String(count)}${
        missingCartons.length > 0 ? ` (carton ${missingCartons.join(', ')} missing)` : ''
      }`;

  const items: Array<[string, boolean, string]> = [
    ['Video', c.video_ok, videoDetail],
    [
      'Documents',
      c.documents_ok,
      c.missing_documentation
        ? c.exception_approved
          ? 'exception approved'
          : 'exception needed'
        : `${String(c.doc_photo_count)} photo(s)`,
    ],
    [
      'Classified',
      c.classified_ok,
      `${String(c.classified_doc_photo_count)}/${String(c.doc_photo_count)}`,
    ],
  ];
  return (
    <ul className="checklist" aria-label="Carton opening checklist" data-testid="checklist">
      {items.map(([label, ok, detail]) => (
        <li key={label} className={ok ? 'chip chip--ok' : 'chip chip--missing'}>
          {ok ? (
            <CheckCircle2 size={16} aria-hidden="true" />
          ) : (
            <XCircle size={16} aria-hidden="true" />
          )}
          <span>
            {label} {ok ? '✔' : '✖'}
          </span>
          <small>{detail}</small>
        </li>
      ))}
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

  const [boxNo, setBoxNo] = useState<string>(String(firstUnrecorded));
  const [error, setError] = useState<string | null>(null);

  // When uploads complete or change, if currently selected box is recorded and others are pending, auto-advance
  useEffect(() => {
    if (recordedBoxSet.has(Number(boxNo))) {
      const total = Math.max(1, boxCount);
      for (let i = 1; i <= total; i++) {
        if (!recordedBoxSet.has(i)) {
          setBoxNo(String(i));
          break;
        }
      }
    }
  }, [recordedBoxSet, boxCount]);

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length === 0) return;
    const problem = tooLarge(files, maxBytes);
    setError(problem);
    if (problem) return;
    const targetBox = Number(boxNo) || 1;
    onFiles(files, targetBox);
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
                onClick={() => setBoxNo(String(num))}
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

function PhotoPicker({
  label,
  accept,
  maxBytes,
  testId,
  multiple = true,
  onFiles,
}: {
  label: string;
  accept: string;
  maxBytes: number;
  testId: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const cameraRef = useRef<HTMLInputElement>(null);
  const chooseRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);

  const onChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (picked.length === 0) return;
    setPreparing(true);
    try {
      const files = await Promise.all(picked.map((f) => downscaleImage(f)));
      const problem = tooLarge(files, maxBytes);
      setError(problem);
      if (!problem) onFiles(files);
    } catch (err) {
      setError(`The photo could not be prepared: ${toApiError(err).message}`);
    } finally {
      setPreparing(false);
    }
  };

  return (
    <div className="picker">
      <div className="picker__buttons">
        <Button
          type="button"
          variant="primary"
          isLoading={preparing}
          onClick={() => cameraRef.current?.click()}
        >
          <Camera size={16} aria-hidden="true" /> {label}
        </Button>
        <Button type="button" variant="outline" onClick={() => chooseRef.current?.click()}>
          <FileUp size={16} aria-hidden="true" /> Choose files
        </Button>
      </div>
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple={multiple}
        hidden
        onChange={(e) => {
          void onChange(e);
        }}
        aria-label={label}
      />
      <input
        ref={chooseRef}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => {
          void onChange(e);
        }}
        data-testid={`${testId}-file-input`}
        aria-label={`${label}: choose files`}
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

function DocumentPhoto({
  index,
  gsId,
  attachment,
  document,
  state,
  editable,
  canDelete,
  onChanged,
}: {
  index: number;
  gsId: string;
  attachment: Attachment;
  document: GsDocument | null;
  state: UnboxingState;
  editable: boolean;
  canDelete: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const formSnapshot = useMemo(() => toDynamicFormSnapshot(state.form_snapshot), [state]);
  const initial = useMemo<Record<string, unknown>>(
    () => document?.values ?? { items_verified: false, challan_qty_matched: false },
    [document],
  );

  const save = async (values: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      if (document) await unboxingApi.updateDocument(gsId, document.id, values);
      else await unboxingApi.classify(gsId, attachment.id, values);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

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
            <span className="badge badge--warning">Not classified</span>
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
        {editable && !editing ? (
          <div className="upload-item__actions">
            <Button
              type="button"
              size="sm"
              variant={document ? 'outline' : 'primary'}
              onClick={() => {
                setEditing(true);
              }}
            >
              {document ? 'Edit classification' : 'Classify'}
            </Button>
            {canDelete ? <DeleteButton attachmentId={attachment.id} onDeleted={onChanged} /> : null}
          </div>
        ) : null}
        {editing ? (
          <div className="doc-photo__form" data-testid="classification-form">
            {error && Object.keys(error.fieldErrors).length === 0 ? (
              <ErrorState error={error} />
            ) : null}
            <DynamicForm
              formSnapshot={formSnapshot}
              initialValues={initial}
              onSubmit={save}
              isSubmitting={saving}
              submitLabel="Save classification"
              serverErrors={error?.fieldErrors}
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
            >
              Cancel
            </Button>
          </div>
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

function MissingDocSection({
  gsId,
  state,
  parcels,
  editable,
  uploads,
  myId,
  onChanged,
  onOpenGs,
}: {
  gsId: string;
  state: UnboxingState;
  parcels: Attachment[];
  editable: boolean;
  uploads: ReturnType<typeof useUploadQueue>;
  myId: string | null;
  onChanged: () => void;
  onOpenGs: (id: string) => void;
}) {
  const [parcelId, setParcelId] = useState<string>('');
  const [remark, setRemark] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const live = state.exceptions.find((e) => e.status === 'REQUESTED' || e.status === 'APPROVED');
  const history = state.exceptions.filter((e) => e !== live);
  const selected = parcelId || parcels[0]?.id || '';

  const request = async () => {
    setBusy(true);
    setError(null);
    try {
      await unboxingApi.requestException(gsId, selected, remark);
      setRemark('');
      onChanged();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <EvidenceSection
      title="Missing documents (DEC-03)"
      icon={<FileUp size={18} aria-hidden="true" />}
      hint="Photograph the parcel label or outer box, explain what was (not) received, and request the Replacement Manager's exception."
    >
      {editable && !live ? (
        <PhotoPicker
          label="Photograph parcel"
          accept={PHOTO_ACCEPT}
          maxBytes={state.limits.max_document_bytes}
          testId="parcel-photo"
          multiple={false}
          onFiles={(files) => {
            uploads.add(files, 'PARCEL_PHOTO');
          }}
        />
      ) : null}
      <UploadList items={uploads.items.filter((i) => i.kind === 'PARCEL_PHOTO')} q={uploads} />
      <div className="evidence-grid">
        {parcels.map((p) => (
          <label key={p.id} className="parcel-option">
            {editable && !live ? (
              <input
                type="radio"
                name="parcel-photo"
                checked={selected === p.id}
                onChange={() => {
                  setParcelId(p.id);
                }}
              />
            ) : null}
            <AttachmentThumb attachment={p} alt="Parcel photo" />
            {editable && !live && p.uploaded_by === myId ? (
              <DeleteButton attachmentId={p.id} onDeleted={onChanged} />
            ) : null}
          </label>
        ))}
      </div>

      {live ? (
        <div
          className={live.status === 'APPROVED' ? 'banner banner--success' : 'banner'}
          role="status"
          data-testid="exception-status"
        >
          Missing Document Exception <strong>{live.status.toLowerCase()}</strong>
          {live.decided_by_name ? ` by ${live.decided_by_name}` : ''} — “{live.remark}”
          {live.decision_remarks ? ` (${live.decision_remarks})` : ''}
        </div>
      ) : null}
      {history.map((e: MissingDocException) => (
        <p key={e.id} className="page__subtitle">
          Earlier request {e.status.toLowerCase()}
          {e.decided_by_name ? ` by ${e.decided_by_name}` : ''}: {e.decision_remarks ?? e.remark}
        </p>
      ))}

      {editable && !live ? (
        <div className="form-group">
          <label className="form-label" htmlFor="exception-remark">
            Remark (required)
          </label>
          <Textarea
            id="exception-remark"
            rows={3}
            value={remark}
            onChange={(e) => {
              setRemark(e.target.value);
            }}
          />
          {error ? (
            <p role="alert" className="form-control__error">
              {error.message}
              {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
            </p>
          ) : null}
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!selected || !remark.trim()}
            onClick={() => {
              void request();
            }}
            style={{ marginTop: '0.5rem' }}
          >
            Request Missing Document Exception
          </Button>
        </div>
      ) : null}

      {live?.status === 'REQUESTED' && state.permissions.can_approve_exception ? (
        <ExceptionDecisionCard exception={live} onDecided={onChanged} onOpenGs={onOpenGs} />
      ) : null}
    </EvidenceSection>
  );
}
