import { useCallback, useEffect, useState } from 'react';
import { Plus, Search, X } from 'lucide-react';

import { DataView } from '@/components/erp';
import { Badge, Button, Checkbox, Input } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { gsApi, type GsListItem, type Page } from './api';
import { FlagIcons, StatusChip } from './display';
import { age, formatDateTime, humanize } from './format';

interface Props {
  /** P4-01: filters from the URL (dashboard click-through), e.g. `#/gs?status=INSPECTION`. */
  initialStatuses?: string[];
  initialDateFrom?: string | null;
  initialDateTo?: string | null;
  initialFlags?: string[];
  onClearFilters?: () => void;
  canCreate: boolean;
  onOpen: (id: string) => void;
  onNew: () => void;
}

const NO_FILTERS: string[] = [];

export function GoodsSlipListPage({
  initialStatuses = NO_FILTERS,
  initialDateFrom = null,
  initialDateTo = null,
  initialFlags = NO_FILTERS,
  onClearFilters,
  canCreate,
  onOpen,
  onNew,
}: Props) {
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [missingDocsOnly, setMissingDocsOnly] = useState(
    initialFlags.includes('missing_documentation'),
  );
  const urlFilters = [
    ...initialStatuses.map(humanize),
    ...(initialDateFrom || initialDateTo
      ? [
          initialDateFrom === initialDateTo
            ? `Created ${initialDateFrom ?? ''}`
            : `Created ${initialDateFrom ?? '…'} – ${initialDateTo ?? '…'}`,
        ]
      : []),
  ];
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query.trim());
      setPage(1);
    }, 300);
    return () => {
      clearTimeout(t);
    };
  }, [query]);

  const fetcher = useCallback(
    () =>
      gsApi.list({
        page,
        ...(debounced ? { q: debounced } : {}),
        ...(missingDocsOnly ? { flag: ['missing_documentation'] } : {}),
        ...(initialStatuses.length ? { status: initialStatuses } : {}),
        ...(initialDateFrom ? { date_from: initialDateFrom } : {}),
        ...(initialDateTo ? { date_to: initialDateTo } : {}),
      }),
    [page, debounced, missingDocsOnly, initialStatuses, initialDateFrom, initialDateTo],
  );
  const { data, error, loading, reload: load } = useApiQuery<Page<GsListItem>>(fetcher);

  return (
    <div className="page">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '0.75rem',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1 className="page__title">Goods Slips</h1>
          <p className="page__subtitle">Gate inward consignments</p>
        </div>
        {canCreate ? (
          <Button type="button" variant="primary" onClick={onNew}>
            <Plus size={16} aria-hidden="true" /> New Goods Slip
          </Button>
        ) : null}
      </div>

      <div
        style={{
          display: 'flex',
          gap: '0.75rem',
          flexWrap: 'wrap',
          alignItems: 'center',
          marginBottom: '1rem',
        }}
      >
        <div style={{ flex: '1 1 240px', position: 'relative' }}>
          <Input
            id="gs-search"
            type="search"
            aria-label="Search by GS number or party"
            placeholder="Search GS no. or party"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            style={{ paddingLeft: '2.25rem' }}
          />
          <Search
            size={16}
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: '0.75rem',
              top: '14px',
              color: 'var(--color-muted)',
            }}
          />
        </div>
        <Checkbox
          id="gs-filter-missing-docs"
          label="Missing documentation only"
          checked={missingDocsOnly}
          onChange={(e) => {
            setMissingDocsOnly(e.target.checked);
            setPage(1);
          }}
        />
      </div>

      {urlFilters.length > 0 ? (
        <div
          role="group"
          aria-label="Active filters"
          style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}
        >
          {urlFilters.map((f) => (
            <Badge key={f} variant="info">
              {f}
            </Badge>
          ))}
          {onClearFilters ? (
            <Button type="button" variant="secondary" onClick={onClearFilters}>
              Clear filters <X size={14} aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      ) : null}

      <DataView<GsListItem>
        rows={data?.items ?? null}
        rowKey={(r) => r.id}
        loading={loading}
        error={error}
        onRetry={load}
        emptyTitle={
          debounced || missingDocsOnly || urlFilters.length
            ? 'No goods slips match the filters'
            : 'No goods slips yet'
        }
        {...(canCreate && !debounced ? { emptyHint: 'Create one from "New Goods Slip".' } : {})}
        onRowClick={(r) => {
          onOpen(r.id);
        }}
        rowLabel={(r) => `Open ${r.gs_no}`}
        page={page}
        pageSize={data?.page_size ?? 25}
        {...(data ? { total: data.total } : {})}
        onPageChange={setPage}
        columns={[
          { key: 'gs_no', header: 'GS No.', render: (r) => r.gs_no },
          {
            key: 'party',
            header: 'Party',
            render: (r) => (
              <>
                {r.party_name}
                {r.party_is_provisional ? (
                  <span style={{ color: 'var(--color-muted)' }}> (provisional)</span>
                ) : null}
              </>
            ),
          },
          { key: 'station', header: 'Station', render: (r) => r.station_name },
          { key: 'cartons', header: 'Cartons', align: 'right', render: (r) => r.carton_count },
          {
            key: 'status',
            header: 'Status',
            render: (r) => (
              <div style={{ display: 'inline-flex', gap: '0.35rem', alignItems: 'center' }}>
                <StatusChip status={r.status} />
                {r.has_open_pendency ? <Badge variant="warning">Pending (BP)</Badge> : null}
              </div>
            ),
          },
          { key: 'flags', header: 'Flags', render: (r) => <FlagIcons flags={r} /> },
          {
            key: 'created',
            header: 'Created',
            render: (r) => (
              <span title={formatDateTime(r.created_at)}>{age(r.created_at)} ago</span>
            ),
          },
        ]}
        renderCard={(r) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: '0.5rem',
                alignItems: 'center',
              }}
            >
              <strong style={{ wordBreak: 'break-all' }}>{r.gs_no}</strong>
              <div style={{ display: 'inline-flex', gap: '0.35rem', alignItems: 'center' }}>
                <StatusChip status={r.status} />
                {r.has_open_pendency ? <Badge variant="warning">Pending (BP)</Badge> : null}
              </div>
            </div>
            <span>
              {r.party_name}
              {r.party_is_provisional ? (
                <span style={{ color: 'var(--color-muted)' }}> (provisional)</span>
              ) : null}
            </span>
            <span
              style={{
                display: 'flex',
                gap: '0.5rem',
                alignItems: 'center',
                color: 'var(--color-muted)',
                fontSize: '0.8125rem',
              }}
            >
              {r.station_name ? <span>{r.station_name}</span> : null}
              <span>
                {String(r.carton_count)} carton{r.carton_count === 1 ? '' : 's'}
              </span>
              <span>{age(r.created_at)} ago</span>
              <FlagIcons flags={r} />
            </span>
          </div>
        )}
      />
    </div>
  );
}
