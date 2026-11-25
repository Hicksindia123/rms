import { useState } from 'react';
import { Download, FileUp } from 'lucide-react';

import { Badge, Button, Checkbox, ErrorState, Textarea } from '@/components/ui';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import { mastersApi, type ProductImportResult } from './api';

const MAX_BYTES = 2_000_000; // ProductImportIn.csv_text max_length

/**
 * Product CSV import (AMD-07, DEC-36): `Item Name, Category, Sub-Category` (+ optional UOM, HSN).
 * Always previews first (dry run, nothing written); Apply sends the same text with an
 * Idempotency-Key and runs in one transaction.
 */
export function ProductImportPanel({ onApplied }: { onApplied: () => void }) {
  const [csvText, setCsvText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [createCategories, setCreateCategories] = useState(false);
  const [preview, setPreview] = useState<ProductImportResult | null>(null);
  const [applied, setApplied] = useState<ProductImportResult | null>(null);
  const [busy, setBusy] = useState<'preview' | 'apply' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);

  const reset = () => {
    setPreview(null);
    setApplied(null);
    setError(null);
    setIdemKey(newIdempotencyKey());
  };

  const readFile = async (file: File) => {
    reset();
    if (file.size > MAX_BYTES) {
      setError(toApiError(new Error('The file is larger than 2 MB.')));
      return;
    }
    setFileName(file.name);
    setCsvText(await file.text());
  };

  const run = async (mode: 'preview' | 'apply') => {
    setBusy(mode);
    setError(null);
    try {
      if (mode === 'preview') {
        setApplied(null);
        setPreview(await mastersApi.previewImport(csvText, createCategories));
      } else {
        setApplied(await mastersApi.runImport(csvText, createCategories, idemKey));
        setPreview(null);
        onApplied();
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const result = applied ?? preview;
  const writes = preview
    ? preview.new_categories.length +
      preview.new_subcategories.length +
      preview.new_products.length +
      preview.updates.length
    : 0;

  return (
    <div className="masters-panel">
      <p className="masters-row__meta">
        Columns: <strong>Item Name</strong> (or Product Name), <strong>Category</strong>,{' '}
        <strong>Sub-Category</strong> (optional); UOM and HSN are optional. Categories are matched
        by code or name, products by exact name (case and extra spaces ignored).
      </p>

      <div className="masters-import__source">
        <label className="btn btn--secondary btn--md masters-import__file">
          <FileUp size={16} aria-hidden="true" /> Choose CSV file
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void readFile(file);
              e.target.value = '';
            }}
          />
        </label>
        {fileName && <span className="masters-row__meta">{fileName}</span>}
      </div>
      <label className="masters-field">
        <span className="form-label">…or paste the CSV</span>
        <Textarea
          id="import-csv"
          rows={6}
          value={csvText}
          spellCheck={false}
          onChange={(e) => {
            setCsvText(e.target.value);
            setFileName(null);
            reset();
          }}
        />
      </label>
      <Checkbox
        id="import-create-categories"
        label="Allow new categories"
        helperText="New categories have no hazard, battery or full-opening flags. Review them afterwards."
        checked={createCategories}
        onChange={(e) => {
          setCreateCategories(e.target.checked);
          reset();
        }}
      />

      <div className="masters-import__actions">
        <Button
          type="button"
          isLoading={busy === 'preview'}
          disabled={!csvText.trim() || busy !== null}
          onClick={() => {
            void run('preview');
          }}
        >
          Preview (dry run)
        </Button>
        <Button
          type="button"
          variant="primary"
          isLoading={busy === 'apply'}
          disabled={!preview || writes === 0 || busy !== null}
          onClick={() => {
            void run('apply');
          }}
        >
          Apply import
        </Button>
      </div>

      {error && <ErrorState error={error} title="Import failed" />}
      {result && <ImportSummary result={result} />}
    </div>
  );
}

function ImportSummary({ result }: { result: ProductImportResult }) {
  const counts: Array<[string, number]> = [
    ['Rows read', result.rows_read],
    ['New categories', result.new_categories.length],
    ['New sub-categories', result.new_subcategories.length],
    ['New products', result.new_products.length],
    ['Updated products', result.updates.length],
    ['Unchanged', result.unchanged],
    ['Duplicates in file', result.duplicates_in_file],
    ['Exceptions', result.exceptions.length],
  ];

  const downloadExceptions = () => {
    const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const lines = [
      ['CSV Row', 'Item Name', 'Category', 'Sub-Category', 'Reason'].map(esc).join(','),
      ...result.exceptions.map((e) =>
        [e.row_no, e.item_name, e.category, e.sub_category, e.reason].map(esc).join(','),
      ),
    ];
    const url = URL.createObjectURL(
      new Blob([String.fromCharCode(0xfeff), lines.join(String.fromCharCode(13, 10))], {
        type: 'text/csv',
      }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'product_import_exceptions.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="masters-import__summary" aria-live="polite">
      <h2 className="masters-import__heading">
        {result.dry_run ? 'Preview — nothing written yet' : 'Import applied'}{' '}
        <Badge variant={result.dry_run ? 'info' : 'success'}>
          {result.dry_run ? 'Dry run' : 'Done'}
        </Badge>
      </h2>
      <dl className="masters-counts">
        {counts.map(([label, n]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{n}</dd>
          </div>
        ))}
      </dl>
      {result.category_changes > 0 && (
        <p className="masters-warning">
          {result.category_changes} product(s) move to another category. Category flags drive the
          hazard and full-opening guards: check the list below.
        </p>
      )}

      <Details
        title="New categories"
        items={result.new_categories.map((c) => `${c.code} — ${c.name}`)}
      />
      <Details
        title="New sub-categories"
        items={result.new_subcategories.map((s) => `${s.category_code} / ${s.code} — ${s.name}`)}
      />
      <Details
        title="New products"
        items={result.new_products.map(
          (p) =>
            `${p.code ?? '(new)'} ${p.name} → ${p.category_code} / ${p.subcategory_code ?? '—'}`,
        )}
      />
      <Details
        title="Updated products"
        items={result.updates.map(
          (u) =>
            `${u.product_code} ${u.name}: ${u.from_category} / ${u.from_subcategory ?? '—'} → ${u.to_category} / ${u.to_subcategory ?? '—'}`,
        )}
      />
      {result.exceptions.length > 0 && (
        <>
          <Details
            title="Exceptions"
            items={result.exceptions.map(
              (e) => `Row ${String(e.row_no)}: ${e.item_name || '(blank)'} — ${e.reason}`,
            )}
          />
          <Button type="button" onClick={downloadExceptions}>
            <Download size={16} aria-hidden="true" /> Download exceptions CSV
          </Button>
        </>
      )}
    </section>
  );
}

function Details({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <details className="masters-details">
      <summary>
        {title} ({items.length})
      </summary>
      <ul>
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </details>
  );
}
