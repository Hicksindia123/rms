import React from 'react';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import type { ErrorLike } from '@/components/ui';

export interface DataViewColumn<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  /** Right-align numbers. */
  align?: 'left' | 'right';
  /** Header becomes a sort button when the view has `onSort`. */
  sortable?: boolean;
}

export interface DataViewProps<T> {
  rows: T[] | null;
  rowKey: (row: T) => string;
  columns: DataViewColumn<T>[];
  /** Card body used below 768px (phones); the table is used from 768px up. */
  renderCard: (row: T) => React.ReactNode;
  onRowClick?: (row: T) => void;
  rowLabel?: (row: T) => string;
  loading?: boolean;
  error?: ErrorLike | null;
  onRetry?: () => void;
  emptyTitle: string;
  emptyHint?: string;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  /** Server-side sorting: current sort and the handler for a header click. */
  sort?: { key: string; dir: 'asc' | 'desc' };
  onSort?: (key: string) => void;
  /** Totals row (table footer on desktop, a summary card above the cards on phones). */
  totals?: Record<string, React.ReactNode>;
  totalsLabel?: string;
}

/** Responsive list: table on desktop, tappable cards on mobile; standard UX states built in. */
export function DataView<T>({
  rows,
  rowKey,
  columns,
  renderCard,
  onRowClick,
  rowLabel,
  loading = false,
  error = null,
  onRetry,
  emptyTitle,
  emptyHint,
  page = 1,
  pageSize = 25,
  total,
  onPageChange,
  sort,
  onSort,
  totals,
  totalsLabel = 'Totals',
}: DataViewProps<T>) {
  if (error) return <ErrorState error={error} {...(onRetry ? { onRetry } : {})} />;
  if (loading && !rows) return <LoadingState />;
  if (!rows || rows.length === 0) {
    return <EmptyState title={emptyTitle} {...(emptyHint ? { hint: emptyHint } : {})} />;
  }

  const pages = total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : 1;

  return (
    <div className="dataview" aria-busy={loading}>
      <div className="dataview__table-wrap">
        <table className="dataview__table">
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort?.key === c.key;
                const ariaSort = active
                  ? sort.dir === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : undefined;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    style={{ textAlign: c.align ?? 'left' }}
                    aria-sort={onSort && c.sortable ? (ariaSort ?? 'none') : undefined}
                  >
                    {onSort && c.sortable ? (
                      <button
                        type="button"
                        className="dataview__sort"
                        onClick={() => {
                          onSort(c.key);
                        }}
                      >
                        {c.header}
                        <span aria-hidden="true" className="dataview__sort-icon">
                          {active ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
                        </span>
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={onRowClick ? 'dataview__row--clickable' : undefined}
                onClick={
                  onRowClick
                    ? () => {
                        onRowClick(row);
                      }
                    : undefined
                }
              >
                {columns.map((c, i) => (
                  <td key={c.key} style={{ textAlign: c.align ?? 'left' }}>
                    {i === 0 && onRowClick ? (
                      <button
                        type="button"
                        className="dataview__link"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRowClick(row);
                        }}
                        aria-label={rowLabel ? rowLabel(row) : undefined}
                      >
                        {c.render(row)}
                      </button>
                    ) : (
                      c.render(row)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {totals ? (
            <tfoot>
              <tr className="dataview__totals">
                {columns.map((c, i) => (
                  <td key={c.key} style={{ textAlign: c.align ?? 'left' }}>
                    {totals[c.key] ?? (i === 0 ? totalsLabel : null)}
                  </td>
                ))}
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>

      {totals ? (
        <dl className="dataview__totals-card" aria-label={totalsLabel}>
          {columns
            .filter((c) => totals[c.key] !== undefined && totals[c.key] !== null)
            .map((c) => (
              <div key={c.key}>
                <dt>{c.header}</dt>
                <dd>{totals[c.key]}</dd>
              </div>
            ))}
        </dl>
      ) : null}

      <ul className="dataview__cards">
        {rows.map((row) => (
          <li key={rowKey(row)}>
            {onRowClick ? (
              <button
                type="button"
                className="dataview__card"
                onClick={() => {
                  onRowClick(row);
                }}
                aria-label={rowLabel ? rowLabel(row) : undefined}
              >
                {renderCard(row)}
              </button>
            ) : (
              <div className="dataview__card">{renderCard(row)}</div>
            )}
          </li>
        ))}
      </ul>

      {onPageChange && pages > 1 ? (
        <nav className="dataview__pager" aria-label="Pagination">
          <Button
            type="button"
            variant="secondary"
            disabled={page <= 1 || loading}
            onClick={() => {
              onPageChange(page - 1);
            }}
          >
            Previous
          </Button>
          <span>
            Page {page} of {pages}
            {total !== undefined ? ` · ${String(total)} total` : ''}
          </span>
          <Button
            type="button"
            variant="secondary"
            disabled={page >= pages || loading}
            onClick={() => {
              onPageChange(page + 1);
            }}
          >
            Next
          </Button>
        </nav>
      ) : null}
    </div>
  );
}
