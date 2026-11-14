import { Plus, Trash2 } from 'lucide-react';

import { Button, Input, Select, Textarea } from '@/components/ui';

import type { GateDocumentType } from './api';
import { GATE_DOC_ACCEPT, newDocDraft, type DocDraft } from './gateDocs';

interface Props {
  types: GateDocumentType[];
  rows: DocDraft[];
  onChange: (rows: DocDraft[]) => void;
  /** API field errors, keyed `documents.{i}.{field}` or `documents`. */
  errors: Record<string, string[]> | undefined;
  /** Business date: document dates cannot be later. */
  maxDate: string | undefined;
  disabled: boolean;
}

/** AMD-04: "Add document" rows at the gate: type, number, date, remarks and files per row.
 * Types and which fields each requires come from the GATE_DOCUMENT configuration. */
export function GateDocumentsEditor({ types, rows, onChange, errors, maxDate, disabled }: Props) {
  const update = (i: number, patch: Partial<DocDraft>) => {
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  };
  const err = (i: number, field: string) => errors?.[`documents.${String(i)}.${field}`]?.[0];
  const listError = errors?.documents?.[0];

  return (
    <div className="gate-docs" data-testid="gate-documents">
      {rows.map((row, i) => {
        const type = types.find((t) => t.code === row.doc_type_code);
        const required = new Set(type?.required_fields ?? []);
        const n = String(i + 1);
        const mark = (field: 'doc_no' | 'doc_date' | 'remarks') =>
          required.has(field) ? ' *' : '';
        return (
          <section key={row.key} className="gate-doc" aria-label={`Document ${n}`}>
            <div className="gate-doc__head">
              <span>Document {n}</span>
              <Button
                type="button"
                variant="ghost"
                aria-label={`Remove document ${n}`}
                disabled={disabled}
                onClick={() => {
                  onChange(rows.filter((_, j) => j !== i));
                }}
              >
                <Trash2 size={18} aria-hidden="true" />
              </Button>
            </div>
            <div>
              <label className="gate-doc__label" htmlFor={`doc-${row.key}-type`}>
                Document type *
              </label>
              <Select
                id={`doc-${row.key}-type`}
                placeholder="-- Select document type --"
                options={types.map((t) => ({ value: t.code, label: t.label }))}
                value={row.doc_type_code}
                error={err(i, 'doc_type_code')}
                disabled={disabled}
                onChange={(e) => {
                  update(i, { doc_type_code: e.target.value });
                }}
              />
            </div>
            <div className="gate-doc__grid">
              <div>
                <label className="gate-doc__label" htmlFor={`doc-${row.key}-no`}>
                  Document no.{mark('doc_no')}
                </label>
                <Input
                  id={`doc-${row.key}-no`}
                  value={row.doc_no}
                  maxLength={100}
                  autoComplete="off"
                  error={err(i, 'doc_no')}
                  disabled={disabled}
                  onChange={(e) => {
                    update(i, { doc_no: e.target.value });
                  }}
                />
              </div>
              <div>
                <label className="gate-doc__label" htmlFor={`doc-${row.key}-date`}>
                  Document date{mark('doc_date')}
                </label>
                <Input
                  id={`doc-${row.key}-date`}
                  type="date"
                  value={row.doc_date}
                  max={maxDate}
                  error={err(i, 'doc_date')}
                  disabled={disabled}
                  onChange={(e) => {
                    update(i, { doc_date: e.target.value });
                  }}
                />
              </div>
            </div>
            <div>
              <label className="gate-doc__label" htmlFor={`doc-${row.key}-remarks`}>
                Remarks{mark('remarks')}
              </label>
              <Textarea
                id={`doc-${row.key}-remarks`}
                rows={2}
                maxLength={1000}
                value={row.remarks}
                error={err(i, 'remarks')}
                disabled={disabled}
                onChange={(e) => {
                  update(i, { remarks: e.target.value });
                }}
              />
            </div>
            <div>
              <label className="gate-doc__label" htmlFor={`doc-${row.key}-files`}>
                Photo / PDF of the document
              </label>
              <input
                id={`doc-${row.key}-files`}
                className="input"
                type="file"
                accept={GATE_DOC_ACCEPT}
                multiple
                disabled={disabled}
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []);
                  update(i, { files: [...row.files, ...picked] });
                  e.target.value = '';
                }}
              />
              {row.files.length > 0 ? (
                <ul className="gate-doc__files" aria-label={`Files for document ${n}`}>
                  {row.files.map((f, k) => (
                    <li key={`${f.name}-${String(k)}`}>
                      <span className="chip">
                        {f.name}{' '}
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-label={`Remove file ${f.name}`}
                          disabled={disabled}
                          onClick={() => {
                            update(i, { files: row.files.filter((_, m) => m !== k) });
                          }}
                        >
                          ×
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </section>
        );
      })}
      {listError ? (
        <p className="form-control__error" role="alert">
          {listError}
        </p>
      ) : null}
      <Button
        type="button"
        variant="secondary"
        disabled={disabled}
        onClick={() => {
          onChange([...rows, newDocDraft()]);
        }}
      >
        <Plus size={16} aria-hidden="true" /> Add document
      </Button>
    </div>
  );
}
