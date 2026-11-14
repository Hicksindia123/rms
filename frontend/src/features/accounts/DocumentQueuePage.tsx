import { useCallback, useState } from 'react';
import { CheckCheck, FileText } from 'lucide-react';

import { DataView } from '@/components/erp';
import { Button, Select } from '@/components/ui';
import { formatDateTime } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError } from '@/lib/api/client';
import { unboxingApi } from '@/features/unboxing/api';

import { accountsApi, type OptionItem, type QueueDocument, type QueueItem } from './api';

/**
 * Accounts Document Queue (WF r3 "Dashboard and Alert system for Accounts team", BR-06, DEC-05):
 * GS whose Step-2 documents are classified and not yet acknowledged. Desktop table, phone cards.
 */
export function DocumentQueuePage({ onOpenGs }: { onOpenGs: (gsId: string) => void }) {
  const [page, setPage] = useState(1);
  const [classification, setClassification] = useState('');
  const [ackError, setAckError] = useState<string | null>(null);
  const [acking, setAcking] = useState<string | null>(null);

  const fetcher = useCallback(
    () => accountsApi.queue(page, classification),
    [page, classification],
  );
  const query = useApiQuery(fetcher);
  const optionsFetcher = useCallback(() => accountsApi.classifications(), []);
  const options = useApiQuery<OptionItem[]>(optionsFetcher);

  const acknowledge = async (gsId: string) => {
    setAcking(gsId);
    setAckError(null);
    try {
      await accountsApi.acknowledge(gsId);
      query.reload();
    } catch (err) {
      const e = toApiError(err);
      setAckError(`${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`);
    } finally {
      setAcking(null);
    }
  };

  const ackButton = (row: QueueItem) => (
    <Button
      type="button"
      size="sm"
      variant="primary"
      isLoading={acking === row.gs_id}
      onClick={(e) => {
        e.stopPropagation();
        void acknowledge(row.gs_id);
      }}
      aria-label={`Acknowledge documents of ${row.gs_no}`}
    >
      <CheckCheck size={14} aria-hidden="true" /> Acknowledge
    </Button>
  );

  return (
    <div className="page">
      <h1 className="page__title">Accounts Document Queue</h1>
      <p className="page__subtitle">
        Documents classified at unboxing that Accounts has not acknowledged yet.
      </p>
      <div className="queue-filter">
        <label className="form-label" htmlFor="queue-classification">
          Document type
        </label>
        <Select
          id="queue-classification"
          value={classification}
          onChange={(e) => {
            setClassification(e.target.value);
            setPage(1);
          }}
          options={[
            { value: '', label: 'All types' },
            ...(options.data ?? []).map((o) => ({ value: o.code, label: o.label })),
          ]}
        />
      </div>
      {ackError ? (
        <p role="alert" className="form-control__error">
          {ackError}
        </p>
      ) : null}
      <DataView<QueueItem>
        rows={query.data?.items ?? null}
        rowKey={(r) => r.gs_id}
        loading={query.loading}
        error={query.error}
        onRetry={query.reload}
        emptyTitle="No documents waiting"
        emptyHint="New documents appear here (and in the bell) when unboxing is completed."
        page={page}
        pageSize={query.data?.page_size ?? 25}
        {...(query.data ? { total: query.data.total } : {})}
        onPageChange={setPage}
        columns={[
          {
            key: 'gs',
            header: 'GS No.',
            render: (r) => (
              <button
                type="button"
                className="dataview__link"
                onClick={() => {
                  onOpenGs(r.gs_id);
                }}
              >
                {r.gs_no}
              </button>
            ),
          },
          { key: 'party', header: 'Party', render: (r) => r.party_name ?? '—' },
          {
            key: 'docs',
            header: 'Documents',
            render: (r) => <DocumentList docs={r.documents} />,
          },
          { key: 'unboxed', header: 'Unboxed', render: (r) => formatDateTime(r.unboxed_at) },
          { key: 'ack', header: '', render: ackButton },
        ]}
        renderCard={(r) => (
          <div className="queue-card" data-testid="queue-card">
            <div className="queue-card__head">
              <strong style={{ wordBreak: 'break-all' }}>{r.gs_no}</strong>
              <span className="page__subtitle">{formatDateTime(r.unboxed_at)}</span>
            </div>
            <p style={{ margin: '0.25rem 0' }}>{r.party_name ?? '—'}</p>
            <DocumentList docs={r.documents} />
            <div style={{ marginTop: '0.5rem' }}>{ackButton(r)}</div>
          </div>
        )}
      />
    </div>
  );
}

function DocumentList({ docs }: { docs: QueueDocument[] }) {
  return (
    <ul className="queue-docs">
      {docs.map((d) => (
        <li key={d.id}>
          <span className="badge badge--info">
            {d.classification_label ?? d.classification_code}
          </span>{' '}
          {[
            d.doc_no,
            d.doc_date,
            d.amount !== null ? `Amount ${d.amount}` : null,
            d.buyer_gstin ? `Buyer ${d.buyer_gstin}` : null,
            d.seller_gstin ? `Seller ${d.seller_gstin}` : null,
            d.qty_matched === null ? null : d.qty_matched ? 'Qty matched' : 'Qty NOT matched',
            d.party_claim_text,
            d.remarks,
          ]
            .filter(Boolean)
            .join(' · ')}{' '}
          <OpenDocument attachmentId={d.attachment_id} />
        </li>
      ))}
    </ul>
  );
}

/** Opens the photo / PDF through a fresh short-lived signed URL (per-GS check, audited). */
function OpenDocument({ attachmentId }: { attachmentId: string }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={(e) => {
          e.stopPropagation();
          setError(null);
          // Open the tab synchronously (popup blockers), then point it at the signed URL.
          const tab = window.open('', '_blank');
          unboxingApi.downloadUrl(attachmentId).then(
            (res) => {
              if (tab) tab.location.href = res.url;
              else window.location.assign(res.url);
            },
            (err: unknown) => {
              tab?.close();
              setError(toApiError(err).message);
            },
          );
        }}
      >
        <FileText size={14} aria-hidden="true" /> View
      </Button>
      {error ? (
        <span role="alert" className="form-control__error">
          {error}
        </span>
      ) : null}
    </>
  );
}
