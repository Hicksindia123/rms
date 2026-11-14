import { useCallback } from 'react';

import { Badge, Button, Drawer, ErrorState, LoadingState } from '@/components/ui';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { inventoryApi } from './api';
import { gsRef, itemTitle } from './rules';
import type { Balance, StockCard, StockRow } from './types';

interface Props {
  row: StockRow;
  canAssign: boolean;
  canRequestAdjustment: boolean;
  reloadToken: number;
  onClose: () => void;
  onAssign: (row: StockRow) => void;
  onRequestAdjustment: (card: StockCard, balance: Balance) => void;
  onOpenTransfer: (transferId: string) => void;
}

/** Stock card: the lot's balances, custody assignments and its full movement path. */
export function StockCardDrawer({
  row,
  canAssign,
  canRequestAdjustment,
  reloadToken,
  onClose,
  onAssign,
  onRequestAdjustment,
  onOpenTransfer,
}: Props) {
  const fetcher = useCallback(
    () => inventoryApi.stockCard(row.lot_id),
    // reloadToken forces a refetch after a command on this lot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [row.lot_id, reloadToken],
  );
  const { data: card, error, loading, reload } = useApiQuery<StockCard>(fetcher);

  return (
    <Drawer
      isOpen
      onClose={onClose}
      title={`Stock card · ${itemTitle(row)}`}
      subtitle={`${gsRef(row)} · ${humanize(row.condition_class)}`}
      footer={
        canAssign && row.assignment_codes.length > 0 ? (
          <Button
            type="button"
            variant="primary"
            style={{ minHeight: 44 }}
            onClick={() => {
              onAssign(row);
            }}
          >
            Custody assignment
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !card ? (
        <LoadingState label="Loading stock card…" />
      ) : card ? (
        <div style={{ display: 'grid', gap: '1.25rem' }}>
          <section aria-label="Lot details">
            <dl className="kv">
              {card.product_name ? <Kv k="Product" v={card.product_name} /> : null}
              {card.part_type ? <Kv k="Part type" v={card.part_type} /> : null}
              {card.pcb_model_name ? (
                <Kv
                  k="PCB model / supplier"
                  v={`${card.pcb_model_name} / ${card.pcb_supplier_name ?? '—'}`}
                />
              ) : null}
              {card.container_code ? (
                <Kv
                  k="Container"
                  v={[card.container_code, card.partition_code].filter(Boolean).join(' / ')}
                />
              ) : null}
              <Kv k="Condition" v={humanize(card.condition_class)} />
              {card.source_condition_code ? (
                <Kv
                  k="Inspected as"
                  v={card.source_condition_label ?? humanize(card.source_condition_code)}
                />
              ) : null}
              {card.lineage.length > 1 ? (
                <Kv k="Derived from" v={`${String(card.lineage.length - 1)} earlier lot(s)`} />
              ) : null}
            </dl>
          </section>

          <section aria-label="Current balances">
            <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Where it is now</h3>
            {card.balances.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--color-muted)' }}>
                No stock left in any location.
              </p>
            ) : (
              <ul
                style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}
              >
                {card.balances.map((b) => (
                  <li
                    key={b.location_id}
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '0.5rem',
                    }}
                  >
                    <span>
                      {b.location_name} · <strong>{b.qty}</strong>
                    </span>
                    {canRequestAdjustment &&
                    b.location_class !== 'TRANSIT' &&
                    card.item_kind !== 'BATTERY' ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        style={{ minHeight: 44 }}
                        onClick={() => {
                          onRequestAdjustment(card, b);
                        }}
                      >
                        Report count difference
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {card.assignments.length > 0 ? (
            <section aria-label="Custody assignments">
              <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Custody assignments</h3>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {card.assignments.map((a) => (
                  <li key={a.id}>
                    {a.assignment_label} · {a.qty} → {a.to_location_name}
                    {a.transfer_no && a.transfer_id ? (
                      <>
                        {' '}
                        (
                        <button
                          type="button"
                          className="dataview__link"
                          style={{ minHeight: 44 }}
                          onClick={() => {
                            if (a.transfer_id) onOpenTransfer(a.transfer_id);
                          }}
                        >
                          {a.transfer_no}
                        </button>
                        )
                      </>
                    ) : null}
                    <p className="timeline__meta">
                      {a.created_by_name ?? '—'} · {formatDateTime(a.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-label="Movement history">
            <h3 style={{ margin: '0 0 0.75rem', fontSize: '1rem' }}>Movement history</h3>
            {card.movements.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--color-muted)' }}>No movements recorded.</p>
            ) : (
              <ol className="timeline">
                {card.movements.map((m) => (
                  <li
                    key={m.id}
                    className={`timeline__item${m.is_ancestor ? ' timeline__item--ancestor' : ''}`}
                  >
                    <div
                      style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '0.5rem',
                        alignItems: 'center',
                      }}
                    >
                      <Badge variant={m.is_ancestor ? 'neutral' : 'info'}>
                        {humanize(m.movement_type)}
                      </Badge>
                      <strong>{m.qty}</strong>
                      <span>
                        {m.from_location_name ?? '—'} → {m.to_location_name ?? '—'}
                      </span>
                    </div>
                    <p className="timeline__meta">
                      {formatDateTime(m.created_at)} · {m.created_by_name ?? 'System'}
                      {m.reference_no ? ` · ${m.reference_no}` : ''}
                      {m.is_ancestor ? ` · earlier lot (${humanize(m.lot_condition_class)})` : ''}
                    </p>
                    {m.reason ? <p className="timeline__meta">{m.reason}</p> : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt style={{ color: 'var(--color-muted)', fontSize: '0.8125rem' }}>{k}</dt>
      <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{v}</dd>
    </div>
  );
}
