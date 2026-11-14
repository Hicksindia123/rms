import { useState } from 'react';
import { FileText } from 'lucide-react';

import { Button } from '@/components/ui';
import { unboxingApi } from '@/features/unboxing/api';
import { toApiError } from '@/lib/api/client';

import type { GateDocument } from './api';
import { formatDate } from './format';

/** AMD-04: the gate document rows of a GS with their files (opened via short-lived signed URLs,
 * each issuance audited by the backend, G-17). */
export function GateDocumentsList({ documents }: { documents: GateDocument[] }) {
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = (fileId: string) => {
    setOpening(fileId);
    setError(null);
    unboxingApi
      .downloadUrl(fileId)
      .then((res) => {
        window.open(res.url, '_blank', 'noopener');
      })
      .catch((err: unknown) => {
        const apiErr = toApiError(err);
        console.error('Gate document download failed', { fileId, err });
        setError(`${apiErr.message}${apiErr.requestId ? ` (request id ${apiErr.requestId})` : ''}`);
      })
      .finally(() => {
        setOpening(null);
      });
  };

  if (documents.length === 0) return <span>—</span>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <ul style={{ margin: 0, paddingLeft: '1.1rem' }} data-testid="gs-gate-documents">
        {documents.map((d) => (
          <li key={d.id}>
            <strong>{d.doc_type_label}</strong>
            {[d.doc_no, d.doc_date ? formatDate(d.doc_date) : null, d.remarks]
              .filter(Boolean)
              .map((p) => ` · ${String(p)}`)
              .join('')}
            {d.files.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                {d.files.map((f, i) => (
                  <Button
                    key={f.id}
                    type="button"
                    variant="ghost"
                    size="sm"
                    isLoading={opening === f.id}
                    disabled={f.status !== 'CONFIRMED'}
                    onClick={() => {
                      open(f.id);
                    }}
                  >
                    <FileText size={14} aria-hidden="true" /> File {String(i + 1)}
                    {f.status !== 'CONFIRMED' ? ' (upload pending)' : ''}
                  </Button>
                ))}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {error ? (
        <p className="form-control__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
