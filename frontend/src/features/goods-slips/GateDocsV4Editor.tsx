import { Plus, Trash2 } from 'lucide-react';

import { Button, Select } from '@/components/ui';

import type { GateDocumentType } from './api';
import { GATE_DOC_ACCEPT, NO_DOCUMENT_CHOICE, newDocDraft, type DocDraft } from './gateDocs';

interface Props {
  /** Stable id prefix ("party" / "transport"). */
  idPrefix: string;
  /** Shown in row headings, e.g. "Party document 1". */
  rowNoun: string;
  types: GateDocumentType[];
  rows: DocDraft[];
  onChange: (rows: DocDraft[]) => void;
  /** Party list only: the configured label of the "no documents" choice and its state. */
  noDocument?: { label: string; checked: boolean; onChange: (checked: boolean) => void };
  /** Client checks by row key (missing type / missing file). */
  rowErrors: Record<string, { type?: string; files?: string }>;
  /** API errors keyed `documents.{offset + i}.{field}`. */
  serverErrors: Record<string, string[]> | undefined;
  offset: number;
  disabled: boolean;
}

/** DEC-62 (gate form v4): optional document rows, each a type + photo/PDF only (no number, date or
 * remarks). Types come from configuration (GATE_DOCUMENT / GATE_TRANSPORT_DOCUMENT). The party
 * list also offers "No Documents From Party", which replaces the rows. */
export function GateDocsV4Editor({
  idPrefix,
  rowNoun,
  types,
  rows,
  onChange,
  noDocument,
  rowErrors,
  serverErrors,
  offset,
  disabled,
}: Props) {
  const update = (i: number, patch: Partial<DocDraft>) => {
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  };
  const serverError = (i: number, field: string) =>
    serverErrors?.[`documents.${String(offset + i)}.${field}`]?.[0];
  const options = [
    ...types.map((t) => ({ value: t.code, label: t.label })),
    ...(noDocument ? [{ value: NO_DOCUMENT_CHOICE, label: noDocument.label }] : []),
  ];

  if (noDocument?.checked) {
    const id = `${idPrefix}-doc-none-type`;
    return (
      <div className="gate-docs" data-testid={`${idPrefix}-documents`}>
        <section className="gate-doc" aria-label={noDocument.label}>
          <div className="gate-doc__head">
            <span>{noDocument.label}</span>
            <Button
              type="button"
              variant="ghost"
              aria-label={`Clear ${noDocument.label}`}
              disabled={disabled}
              onClick={() => {
                noDocument.onChange(false);
              }}
            >
              <Trash2 size={18} aria-hidden="true" />
            </Button>
          </div>
          <div>
            <label className="gate-doc__label" htmlFor={id}>
              Document type
            </label>
            <Select
              id={id}
              options={options}
              value={NO_DOCUMENT_CHOICE}
              disabled={disabled}
              onChange={(e) => {
                noDocument.onChange(false);
                onChange([{ ...newDocDraft(), doc_type_code: e.target.value }]);
              }}
            />
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="gate-docs" data-testid={`${idPrefix}-documents`}>
      {rows.map((row, i) => {
        const n = String(i + 1);
        const typeId = `${idPrefix}-doc-${row.key}-type`;
        const fileId = `${idPrefix}-doc-${row.key}-files`;
        const fileError = rowErrors[row.key]?.files;
        return (
          <section key={row.key} className="gate-doc" aria-label={`${rowNoun} ${n}`}>
            <div className="gate-doc__head">
              <span>
                {rowNoun} {n}
              </span>
              <Button
                type="button"
                variant="ghost"
                aria-label={`Remove ${rowNoun.toLowerCase()} ${n}`}
                disabled={disabled}
                onClick={() => {
                  onChange(rows.filter((_, j) => j !== i));
                }}
              >
                <Trash2 size={18} aria-hidden="true" />
              </Button>
            </div>
            <div>
              <label className="gate-doc__label" htmlFor={typeId}>
                Document type
                <span className="req-mark" aria-label="required">
                  *
                </span>
              </label>
              <Select
                id={typeId}
                placeholder="-- Select document type --"
                options={options}
                value={row.doc_type_code}
                error={rowErrors[row.key]?.type ?? serverError(i, 'doc_type_code')}
                disabled={disabled}
                onChange={(e) => {
                  if (noDocument && e.target.value === NO_DOCUMENT_CHOICE) {
                    onChange([]);
                    noDocument.onChange(true);
                    return;
                  }
                  update(i, { doc_type_code: e.target.value });
                }}
              />
            </div>
            <div>
              <label className="gate-doc__label" htmlFor={fileId}>
                Photo / PDF
                <span className="req-mark" aria-label="required">
                  *
                </span>
              </label>
              <input
                id={fileId}
                className="input"
                type="file"
                accept={GATE_DOC_ACCEPT}
                multiple
                disabled={disabled}
                aria-invalid={fileError ? true : undefined}
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []);
                  update(i, { files: [...row.files, ...picked] });
                  e.target.value = '';
                }}
              />
              {fileError ? (
                <p className="form-control__error" role="alert">
                  {fileError}
                </p>
              ) : null}
              {row.files.length > 0 ? (
                <ul
                  className="gate-doc__files"
                  aria-label={`Files for ${rowNoun.toLowerCase()} ${n}`}
                >
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
      <Button
        type="button"
        variant="secondary"
        disabled={disabled}
        onClick={() => {
          onChange([...rows, newDocDraft()]);
        }}
      >
        <Plus size={16} aria-hidden="true" /> Add {rowNoun.toLowerCase()}
      </Button>
    </div>
  );
}
