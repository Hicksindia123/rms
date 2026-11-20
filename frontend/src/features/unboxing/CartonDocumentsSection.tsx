import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { Camera, FilePlus2, FileUp, RefreshCw, Trash2 } from 'lucide-react';

import { Button, Select } from '@/components/ui';
import type { GateDocument, GateDocumentType } from '@/features/goods-slips/api';
import { GateDocumentsList } from '@/features/goods-slips/GateDocumentsList';
import { GATE_DOC_ACCEPT } from '@/features/goods-slips/gateDocs';
import { uploadDocumentFiles, type PendingFile } from '@/features/goods-slips/gateUploads';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import { unboxingApi } from './api';
import { downscaleImage } from './imageDownscale';
import '@/features/goods-slips/gateForm.css';

const CARTON_STAGE = 'S1_UNBOX';
const CARTON_SOURCE = 'CARTON';

interface Props {
  gsId: string;
  documents: GateDocument[];
  types: GateDocumentType[];
  editable: boolean;
  maxBytes: number;
  onChanged: () => void;
}

function mb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** P3 / DEC-62: ONE optional "Document found in carton" per GS: choose the type (the active party
 * document types from configuration, without "No Documents From Party") and attach photo(s). No
 * number, date or remarks. An Invoice / GST Debit Note alerts Accounts at once (backend, AMD-05).
 * Gate rows and carton rows recorded before P3 are shown read-only. */
export function CartonDocumentsSection({
  gsId,
  documents,
  types,
  editable,
  maxBytes,
  onChanged,
}: Props) {
  const [typeCode, setTypeCode] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [pickError, setPickError] = useState<string | null>(null);
  const [failed, setFailed] = useState<PendingFile[]>([]);
  const [removing, setRemoving] = useState(false);
  const key = useRef<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const chooseRef = useRef<HTMLInputElement>(null);

  const gateRows = documents.filter((d) => d.source_step !== CARTON_STAGE);
  const cartonDoc = documents.find((d) => d.doc_source === CARTON_SOURCE) ?? null;
  const legacyRows = documents.filter(
    (d) => d.source_step === CARTON_STAGE && d.doc_source !== CARTON_SOURCE,
  );
  const tooBig = files.find((f) => f.size > maxBytes);
  const typeError = fieldErrors['documents.0.doc_type_code']?.[0];

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (picked.length === 0) return;
    setPreparing(true);
    setPickError(null);
    try {
      // Photos are downscaled on the phone before upload (same as the evidence photos).
      const ready = await Promise.all(picked.map((f) => downscaleImage(f)));
      setFiles((prev) => [...prev, ...ready]);
    } catch (err) {
      console.error('Carton document photo could not be prepared', { gsId, err });
      setPickError(`The photo could not be prepared: ${toApiError(err).message}`);
    } finally {
      setPreparing(false);
    }
  };

  const upload = async (documentId: string, list: File[]) => {
    setProgress(0);
    const pending = await uploadDocumentFiles(
      gsId,
      list.map((file) => ({ documentId, file })),
      (index, percent) => {
        setProgress(Math.round(((index + percent / 100) / list.length) * 100));
      },
    );
    setProgress(null);
    setFailed(pending);
    setFiles([]);
    onChanged();
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      if (cartonDoc) {
        await upload(cartonDoc.id, files);
      } else {
        key.current ??= newIdempotencyKey();
        const row = await unboxingApi.addCartonDocument(
          gsId,
          { doc_type_code: typeCode },
          key.current,
        );
        key.current = null;
        setTypeCode('');
        await upload(row.id, files);
      }
    } catch (e) {
      const apiErr = toApiError(e);
      if (apiErr.status >= 400 && apiErr.status < 500) key.current = null;
      setError(apiErr);
      setFieldErrors(apiErr.fieldErrors);
      setProgress(null);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (docId: string) => {
    setRemoving(true);
    setError(null);
    try {
      await unboxingApi.removeCartonDocument(gsId, docId);
      setFailed([]);
      onChanged();
    } catch (e) {
      setError(toApiError(e));
    } finally {
      setRemoving(false);
    }
  };

  const fileInputs = (
    <div>
      <span className="gate-doc__label">
        Photo(s) of the document
        <span className="req-mark" aria-label="required">
          *
        </span>
      </span>
      <div className="picker__buttons">
        <Button
          type="button"
          variant="secondary"
          isLoading={preparing}
          disabled={busy}
          onClick={() => cameraRef.current?.click()}
        >
          <Camera size={16} aria-hidden="true" /> Take photo
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy || preparing}
          onClick={() => chooseRef.current?.click()}
        >
          <FileUp size={16} aria-hidden="true" /> Choose files
        </Button>
      </div>
      {/* capture="environment" opens the phone's rear camera. */}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        data-testid="carton-doc-camera-input"
        aria-label="Take a photo of the carton document"
        onChange={(e) => {
          void onPick(e);
        }}
      />
      <input
        ref={chooseRef}
        type="file"
        accept={GATE_DOC_ACCEPT}
        multiple
        hidden
        data-testid="carton-doc-file-input"
        aria-label="Choose photos of the carton document"
        onChange={(e) => {
          void onPick(e);
        }}
      />
      {files.length > 0 ? (
        <ul className="gate-doc__files" aria-label="Photos to upload">
          {files.map((f, i) => (
            <li key={`${f.name}-${String(i)}`}>
              <span className="chip">
                {f.name}{' '}
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  aria-label={`Remove photo ${f.name}`}
                  disabled={busy}
                  onClick={() => {
                    setFiles(files.filter((_, j) => j !== i));
                  }}
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {pickError ? (
        <p className="form-control__error" role="alert">
          {pickError}
        </p>
      ) : null}
      {tooBig ? (
        <p className="form-control__error" role="alert">
          {tooBig.name} is {mb(tooBig.size)}; the limit is {mb(maxBytes)}.
        </p>
      ) : null}
    </div>
  );

  return (
    <section className="card unboxing__section" aria-labelledby="carton-docs-h">
      <h2 id="carton-docs-h" className="unboxing__h2">
        <FilePlus2 size={18} aria-hidden="true" /> Document found in carton (optional)
      </h2>
      <p className="page__subtitle" style={{ margin: 0 }}>
        If a carton holds a document, choose its type and photograph it. Invoices and debit notes
        alert Accounts immediately.
      </p>

      {gateRows.length > 0 ? (
        <div>
          <h3 className="itemize__h3">Recorded at the gate</h3>
          <GateDocumentsList documents={gateRows} />
        </div>
      ) : null}

      {legacyRows.length > 0 ? (
        <div>
          <h3 className="itemize__h3">Added at carton opening earlier</h3>
          <GateDocumentsList documents={legacyRows} />
        </div>
      ) : null}

      {cartonDoc ? (
        <div className="gate-doc" data-testid="carton-document">
          <div className="gate-doc__head">
            <span>Document found in carton</span>
            {editable ? (
              <Button
                type="button"
                variant="ghost"
                isLoading={removing}
                disabled={busy}
                aria-label={`Remove ${cartonDoc.doc_type_label}`}
                onClick={() => {
                  void remove(cartonDoc.id);
                }}
              >
                <Trash2 size={18} aria-hidden="true" />
              </Button>
            ) : null}
          </div>
          <GateDocumentsList documents={[cartonDoc]} />
          {editable ? (
            <>
              {fileInputs}
              {files.length > 0 ? (
                <Button
                  type="button"
                  variant="primary"
                  isLoading={busy}
                  disabled={Boolean(tooBig) || preparing}
                  onClick={() => {
                    void save();
                  }}
                >
                  Upload {files.length === 1 ? 'photo' : 'photos'}
                </Button>
              ) : null}
            </>
          ) : null}
        </div>
      ) : editable ? (
        <div className="gate-doc" data-testid="carton-document-form">
          <div>
            <label className="gate-doc__label" htmlFor="carton-doc-type">
              Document type
              <span className="req-mark" aria-label="required">
                *
              </span>
            </label>
            <Select
              id="carton-doc-type"
              placeholder="-- Select document type --"
              options={types.map((t) => ({ value: t.code, label: t.label }))}
              value={typeCode}
              error={typeError}
              disabled={busy}
              onChange={(e) => {
                setTypeCode(e.target.value);
              }}
            />
          </div>
          {fileInputs}
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!typeCode || files.length === 0 || Boolean(tooBig) || preparing}
            onClick={() => {
              void save();
            }}
          >
            <FilePlus2 size={16} aria-hidden="true" /> Save document
          </Button>
        </div>
      ) : (
        <p className="page__subtitle" style={{ margin: 0 }}>
          No document found in a carton.
        </p>
      )}

      {progress !== null ? (
        <progress max={100} value={progress} aria-label="Document photo upload progress" />
      ) : null}

      {failed.length > 0 ? (
        <div className="banner" role="alert" style={{ flexDirection: 'column' }}>
          <strong>
            {String(failed.length)} photo(s) were not uploaded; the document is saved.
          </strong>
          <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
            {failed.map((f, i) => (
              <li key={`${f.file.name}-${String(i)}`}>
                {f.file.name}: {f.error}
              </li>
            ))}
          </ul>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              void uploadDocumentFiles(gsId, failed).then((still) => {
                setFailed(still);
                onChanged();
              });
            }}
          >
            <RefreshCw size={16} aria-hidden="true" /> Retry uploads
          </Button>
        </div>
      ) : null}

      {error && !typeError ? (
        <p className="form-control__error" role="alert">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
    </section>
  );
}
