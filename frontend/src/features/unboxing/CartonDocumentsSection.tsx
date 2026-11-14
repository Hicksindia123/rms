import { useRef, useState } from 'react';
import { FilePlus2, RefreshCw, Trash2 } from 'lucide-react';

import { Button, Input, Select, Textarea } from '@/components/ui';
import type { GateDocument, GateDocumentType } from '@/features/goods-slips/api';
import { GateDocumentsList } from '@/features/goods-slips/GateDocumentsList';
import { GATE_DOC_ACCEPT } from '@/features/goods-slips/gateDocs';
import { uploadDocumentFiles, type PendingFile } from '@/features/goods-slips/gateUploads';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import { unboxingApi } from './api';
import '@/features/goods-slips/gateForm.css';

const CARTON_STAGE = 'S1_UNBOX';

interface Props {
  gsId: string;
  documents: GateDocument[];
  types: GateDocumentType[];
  editable: boolean;
  maxBytes: number;
  onChanged: () => void;
}

const EMPTY = { doc_type_code: '', doc_no: '', doc_date: '', remarks: '' };

/** AMD-04 / AMD-05: documents found inside the cartons are added as more document rows (same model
 * as the gate). An Invoice / Debit Note row alerts Accounts at once; the backend never alerts twice
 * for the same document. Gate rows are shown read-only. */
export function CartonDocumentsSection({
  gsId,
  documents,
  types,
  editable,
  maxBytes,
  onChanged,
}: Props) {
  const [draft, setDraft] = useState(EMPTY);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [failed, setFailed] = useState<PendingFile[]>([]);
  const [removing, setRemoving] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const type = types.find((t) => t.code === draft.doc_type_code);
  const required = new Set(type?.required_fields ?? []);
  const gateRows = documents.filter((d) => d.source_step !== CARTON_STAGE);
  const cartonRows = documents.filter((d) => d.source_step === CARTON_STAGE);
  const tooBig = files.find((f) => f.size > maxBytes);
  const err = (field: string) => fieldErrors[`documents.0.${field}`]?.[0];

  const add = async () => {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    key.current ??= newIdempotencyKey();
    try {
      const row = await unboxingApi.addCartonDocument(
        gsId,
        {
          doc_type_code: draft.doc_type_code,
          doc_no: draft.doc_no.trim() || null,
          doc_date: draft.doc_date || null,
          remarks: draft.remarks.trim() || null,
        },
        key.current,
      );
      key.current = null;
      setFailed(
        await uploadDocumentFiles(
          gsId,
          files.map((file) => ({ documentId: row.id, file })),
        ),
      );
      setDraft(EMPTY);
      setFiles([]);
      onChanged();
    } catch (e) {
      const apiErr = toApiError(e);
      if (apiErr.status >= 400 && apiErr.status < 500) key.current = null;
      setError(apiErr);
      setFieldErrors(apiErr.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (docId: string) => {
    setRemoving(docId);
    setError(null);
    try {
      await unboxingApi.removeCartonDocument(gsId, docId);
      onChanged();
    } catch (e) {
      setError(toApiError(e));
    } finally {
      setRemoving(null);
    }
  };

  return (
    <section className="card unboxing__section" aria-labelledby="carton-docs-h">
      <h2 id="carton-docs-h" className="unboxing__h2">
        <FilePlus2 size={18} aria-hidden="true" /> Documents found in the cartons
      </h2>
      <p className="page__subtitle" style={{ margin: 0 }}>
        Add every invoice, debit note, challan or slip found inside a carton. Invoices and debit
        notes alert Accounts immediately.
      </p>

      {gateRows.length > 0 ? (
        <div>
          <h3 className="itemize__h3">Recorded at the gate</h3>
          <GateDocumentsList documents={gateRows} />
        </div>
      ) : null}

      <div>
        <h3 className="itemize__h3">Added at carton opening</h3>
        {cartonRows.length === 0 ? (
          <p className="page__subtitle" style={{ margin: 0 }}>
            None yet.
          </p>
        ) : (
          <div data-testid="carton-documents">
            <GateDocumentsList documents={cartonRows} />
            {editable
              ? cartonRows.map((d) => (
                  <Button
                    key={d.id}
                    type="button"
                    variant="ghost"
                    size="sm"
                    isLoading={removing === d.id}
                    aria-label={`Remove ${d.doc_type_label} ${d.doc_no ?? ''}`.trim()}
                    onClick={() => {
                      void remove(d.id);
                    }}
                  >
                    <Trash2 size={14} aria-hidden="true" /> Remove {d.doc_type_label}
                    {d.doc_no ? ` ${d.doc_no}` : ''}
                  </Button>
                ))
              : null}
          </div>
        )}
      </div>

      {failed.length > 0 ? (
        <div className="banner" role="alert" style={{ flexDirection: 'column' }}>
          <strong>{String(failed.length)} file(s) were not uploaded; the document is saved.</strong>
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

      {editable ? (
        <div className="gate-doc" data-testid="carton-document-form">
          <div>
            <label className="gate-doc__label" htmlFor="carton-doc-type">
              Document type *
            </label>
            <Select
              id="carton-doc-type"
              placeholder="-- Select document type --"
              options={types.map((t) => ({ value: t.code, label: t.label }))}
              value={draft.doc_type_code}
              error={err('doc_type_code')}
              disabled={busy}
              onChange={(e) => {
                setDraft({ ...draft, doc_type_code: e.target.value });
              }}
            />
          </div>
          <div className="gate-doc__grid">
            <div>
              <label className="gate-doc__label" htmlFor="carton-doc-no">
                Document no.{required.has('doc_no') ? ' *' : ''}
              </label>
              <Input
                id="carton-doc-no"
                value={draft.doc_no}
                maxLength={100}
                autoComplete="off"
                error={err('doc_no')}
                disabled={busy}
                onChange={(e) => {
                  setDraft({ ...draft, doc_no: e.target.value });
                }}
              />
            </div>
            <div>
              <label className="gate-doc__label" htmlFor="carton-doc-date">
                Document date{required.has('doc_date') ? ' *' : ''}
              </label>
              <Input
                id="carton-doc-date"
                type="date"
                value={draft.doc_date}
                max={today}
                error={err('doc_date')}
                disabled={busy}
                onChange={(e) => {
                  setDraft({ ...draft, doc_date: e.target.value });
                }}
              />
            </div>
          </div>
          <div>
            <label className="gate-doc__label" htmlFor="carton-doc-remarks">
              Remarks{required.has('remarks') ? ' *' : ''}
            </label>
            <Textarea
              id="carton-doc-remarks"
              rows={2}
              maxLength={1000}
              value={draft.remarks}
              error={err('remarks')}
              disabled={busy}
              onChange={(e) => {
                setDraft({ ...draft, remarks: e.target.value });
              }}
            />
          </div>
          <div>
            <label className="gate-doc__label" htmlFor="carton-doc-files">
              Photo / PDF of the document
            </label>
            <input
              id="carton-doc-files"
              className="input"
              type="file"
              accept={GATE_DOC_ACCEPT}
              multiple
              disabled={busy}
              onChange={(e) => {
                setFiles([...files, ...Array.from(e.target.files ?? [])]);
                e.target.value = '';
              }}
            />
            {files.length > 0 ? (
              <ul className="gate-doc__files">
                {files.map((f, i) => (
                  <li key={`${f.name}-${String(i)}`}>
                    <span className="chip">{f.name}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {tooBig ? (
              <p className="form-control__error" role="alert">
                {tooBig.name} is larger than the upload limit.
              </p>
            ) : null}
          </div>
          {error && Object.keys(fieldErrors).length === 0 ? (
            <p className="form-control__error" role="alert">
              {error.message}
              {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
            </p>
          ) : null}
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!draft.doc_type_code || Boolean(tooBig)}
            onClick={() => {
              void add();
            }}
          >
            <FilePlus2 size={16} aria-hidden="true" /> Add document
          </Button>
        </div>
      ) : null}
    </section>
  );
}
