import { useCallback, useState } from 'react';
import { Download, Search } from 'lucide-react';

import { DataView, type DataViewColumn } from '@/components/erp';
import { Badge, Button, Input, Select } from '@/components/ui';
import { humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';
import { inventoryApi } from './api';
import { VIEW_CONDITIONS, VIEW_LABELS, gsRef, itemTitle } from './rules';
import type { InventoryLookups, StockFilters, StockPage, StockRow, StockView } from './types';

interface Props {
  view: StockView;
  lookups: InventoryLookups;
  /** Bumped by the page after a command so the list reloads. */
  reloadToken: number;
  onOpen: (row: StockRow) => void;
  onAssign: (row: StockRow) => void;
}

/** One custody-segregated stock view (BR-30): filters, export, table / mobile cards. */
export function StockViewPanel({ view, lookups, reloadToken, onOpen, onAssign }: Props) {
  const [draft, setDraft] = useState<StockFilters>({});
  const [filters, setFilters] = useState<StockFilters>({});
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<ApiError | null>(null);

  const fetcher = useCallback(
    () => inventoryApi.stock(view, filters, page),
    // reloadToken forces a refetch after commands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, filters, page, reloadToken],
  );
  const { data, error, loading, reload } = useApiQuery<StockPage>(fetcher);

  const set = (patch: StockFilters) => {
    setDraft((d) => ({ ...d, ...patch }));
  };
  const apply = () => {
    setFilters(Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== '' && v != null)));
    setPage(1);
  };
  const exportCsv = () => {
    setExporting(true);
    setExportError(null);
    inventoryApi
      .exportCsv(view, filters)
      .catch((err: unknown) => {
        setExportError(toApiError(err));
      })
      .finally(() => {
        setExporting(false);
      });
  };

  const canAssignRow = (r: StockRow) => lookups.can_assign && r.assignment_codes.length > 0;
  const columns: DataViewColumn<StockRow>[] = [
    { key: 'item', header: 'Item', render: (r) => itemTitle(r) },
    { key: 'gs', header: 'GS / line', render: (r) => gsRef(r) },
    ...(view === 'SPARE_PARTS'
      ? [
          {
            key: 'pcb',
            header: 'PCB model / supplier',
            render: (r: StockRow) =>
              r.pcb_model_name ? `${r.pcb_model_name} / ${r.pcb_supplier_name ?? '—'}` : '—',
          },
          {
            key: 'container',
            header: 'Container',
            render: (r: StockRow) =>
              [r.container_code, r.partition_code].filter(Boolean).join(' / ') || '—',
          },
        ]
      : [
          {
            key: 'condition',
            header: 'Condition',
            render: (r: StockRow) => <ConditionBadge row={r} />,
          },
        ]),
    { key: 'location', header: 'Location', render: (r) => r.location_name },
    { key: 'qty', header: 'Qty', align: 'right', render: (r) => r.qty },
    {
      key: 'age',
      header: 'Age',
      align: 'right',
      render: (r) => (r.age_days === null ? '—' : `${String(r.age_days)} d`),
    },
    ...(view === 'FUNCTIONAL'
      ? [{ key: 'next', header: 'Next action', render: (r: StockRow) => r.next_action_text ?? '—' }]
      : []),
    ...(view === 'IN_TRANSIT'
      ? [
          {
            key: 'transfer',
            header: 'Transfer',
            render: (r: StockRow) =>
              r.transfer_no ? `${r.transfer_no} → ${r.transfer_to_name ?? ''}` : '—',
          },
        ]
      : []),
    ...(lookups.can_assign
      ? [
          {
            key: 'actions',
            header: 'Custody',
            render: (r: StockRow) =>
              canAssignRow(r) ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  style={{ minHeight: 44 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onAssign(r);
                  }}
                >
                  Assign
                </Button>
              ) : null,
          },
        ]
      : []),
  ];

  const conditions = VIEW_CONDITIONS[view];
  return (
    <section aria-label={VIEW_LABELS[view]}>
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        {view !== 'SPARE_PARTS' && view !== 'BATTERIES' ? (
          <div>
            <label className="form-label" htmlFor={`${view}-q`}>
              Search GS / product
            </label>
            <Input
              id={`${view}-q`}
              value={draft.q ?? ''}
              onChange={(e) => {
                set({ q: e.target.value });
              }}
            />
          </div>
        ) : null}
        {view !== 'SPARE_PARTS' && view !== 'BATTERIES' && lookups.products.length > 0 ? (
          <div>
            <label className="form-label" htmlFor={`${view}-product`}>
              Product
            </label>
            <Select
              id={`${view}-product`}
              placeholder="All products"
              value={draft.product_id ?? ''}
              options={lookups.products.map((p) => ({ value: p.id, label: p.name }))}
              onChange={(e) => {
                set({ product_id: e.target.value });
              }}
            />
          </div>
        ) : null}
        {conditions ? (
          <div>
            <label className="form-label" htmlFor={`${view}-condition`}>
              Condition
            </label>
            <Select
              id={`${view}-condition`}
              placeholder="All conditions"
              value={draft.condition_class ?? ''}
              options={conditions.map((c) => ({ value: c, label: humanize(c) }))}
              onChange={(e) => {
                set({ condition_class: e.target.value });
              }}
            />
          </div>
        ) : null}
        {view === 'FUNCTIONAL' ? (
          <div>
            <label className="form-label" htmlFor={`${view}-age`}>
              Older than (days)
            </label>
            <Input
              id={`${view}-age`}
              type="number"
              min={0}
              inputMode="numeric"
              value={draft.min_age_days ?? ''}
              onChange={(e) => {
                set({
                  min_age_days: e.target.value === '' ? undefined : Number(e.target.value),
                });
              }}
            />
          </div>
        ) : null}
        {view === 'SPARE_PARTS' ? (
          <>
            <RefSelect
              id="parts-type"
              label="Part type"
              all="All part types"
              value={draft.part_type}
              options={lookups.part_types.map((o) => ({ value: o.code, label: o.label }))}
              onChange={(v) => {
                set({ part_type: v });
              }}
            />
            <RefSelect
              id="parts-model"
              label="PCB model"
              all="All models"
              value={draft.pcb_model_id}
              options={lookups.pcb_models.map((o) => ({ value: o.id, label: o.name }))}
              onChange={(v) => {
                set({ pcb_model_id: v });
              }}
            />
            <RefSelect
              id="parts-supplier"
              label="PCB supplier"
              all="All suppliers"
              value={draft.pcb_supplier_id}
              options={lookups.pcb_suppliers.map((o) => ({ value: o.id, label: o.name }))}
              onChange={(v) => {
                set({ pcb_supplier_id: v });
              }}
            />
            <RefSelect
              id="parts-container"
              label="Container"
              all="All containers"
              value={draft.container_id}
              options={lookups.containers.map((o) => ({ value: o.id, label: o.name }))}
              onChange={(v) => {
                set({ container_id: v });
              }}
            />
            <RefSelect
              id="parts-partition"
              label="Partition"
              all="All partitions"
              value={draft.partition_id}
              options={lookups.partitions.map((o) => ({ value: o.id, label: o.name }))}
              onChange={(v) => {
                set({ partition_id: v });
              }}
            />
          </>
        ) : null}
        {view === 'BATTERIES' ? (
          <RefSelect
            id="battery-type"
            label="Battery type"
            all="All battery types"
            value={draft.battery_type_id}
            options={lookups.battery_types.map((o) => ({ value: o.id, label: o.name }))}
            onChange={(v) => {
              set({ battery_type_id: v });
            }}
          />
        ) : null}
        <div className="filters__actions">
          <Button type="submit" variant="primary" style={{ minHeight: 44 }}>
            <Search size={16} aria-hidden="true" /> Apply
          </Button>
          {lookups.can_export ? (
            <Button
              type="button"
              variant="secondary"
              style={{ minHeight: 44 }}
              disabled={exporting}
              onClick={exportCsv}
            >
              <Download size={16} aria-hidden="true" /> {exporting ? 'Exporting…' : 'Export CSV'}
            </Button>
          ) : null}
        </div>
      </form>
      {exportError ? (
        <p role="alert" className="form-error">
          Export failed: {exportError.message}
          {exportError.requestId ? ` (Request ID: ${exportError.requestId})` : ''}
        </p>
      ) : null}
      {data ? (
        <p className="stat-row" aria-live="polite">
          <span>
            <strong>{data.total}</strong> lot{data.total === 1 ? '' : 's'}
          </span>
          <span>
            <strong>{data.total_qty}</strong> pieces
          </span>
        </p>
      ) : null}
      <DataView<StockRow>
        rows={data?.items ?? null}
        rowKey={(r) => `${r.lot_id}:${r.location_id}`}
        columns={columns}
        loading={loading}
        error={error}
        onRetry={reload}
        onRowClick={onOpen}
        rowLabel={(r) => `Open stock card: ${itemTitle(r)} ${gsRef(r)}`}
        emptyTitle={`No stock in ${VIEW_LABELS[view]}`}
        emptyHint="Adjust the filters, or the stock has moved on."
        page={page}
        pageSize={data?.page_size ?? 25}
        {...(data ? { total: data.total } : {})}
        onPageChange={setPage}
        renderCard={(r) => (
          <div style={{ display: 'grid', gap: '0.25rem', textAlign: 'left' }}>
            <strong>{itemTitle(r)}</strong>
            <span style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>
              {gsRef(r)} · {r.location_name}
            </span>
            <span style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <ConditionBadge row={r} />
              <Badge variant="neutral">Qty {r.qty}</Badge>
              {r.age_days !== null ? <Badge variant="neutral">{r.age_days} d</Badge> : null}
            </span>
            {r.next_action_text ? (
              <span style={{ fontSize: '0.875rem' }}>{r.next_action_text}</span>
            ) : null}
            {r.transfer_no ? (
              <span style={{ fontSize: '0.875rem' }}>
                {r.transfer_no} → {r.transfer_to_name}
              </span>
            ) : null}
          </div>
        )}
      />
    </section>
  );
}

function ConditionBadge({ row }: { row: Pick<StockRow, 'condition_class' | 'is_pending'> }) {
  const variant =
    row.condition_class === 'FUNCTIONAL_GOOD' || row.condition_class === 'FUNCTIONAL_REPAIRED'
      ? 'success'
      : row.condition_class === 'HAZARD'
        ? 'danger'
        : row.condition_class === 'AS_RECEIVED' || row.condition_class === 'SALVAGED'
          ? 'info'
          : 'warning';
  return (
    <Badge variant={variant}>
      {humanize(row.condition_class)}
      {row.is_pending ? ' · Pending (BP)' : ''}
    </Badge>
  );
}

function RefSelect({
  id,
  label,
  all,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  all: string;
  value: string | undefined;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="form-label" htmlFor={id}>
        {label}
      </label>
      <Select
        id={id}
        placeholder={all}
        value={value ?? ''}
        options={options}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
    </div>
  );
}
