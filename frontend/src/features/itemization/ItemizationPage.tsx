import { useCallback, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, FileText, Lock, Pencil, Plus, Trash2 } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { useStatusLabels } from '@/features/goods-slips/statusLabels';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  itemizationApi,
  newIdempotencyKey,
  type ItemizationState,
  type ItemLine,
  type Lot,
  type StepOption,
} from './api';
import { CsrDecisionCard } from './DecisionCards';
import {
  DocumentPanel,
  ItemLineCard,
  LineEditor,
  QtyBadges,
  QtyStepper,
  type LockedSave,
} from './LineParts';

/** DEC-64: statuses of the new flow (codes; labels come from GS_STATUS). */
const LOCKED = 'PENDING_TRANSFER_SLIP';
const HOLD = 'SALES_RETURN_HOLD';
const CATEGORISATION = 'CATEGORISATION';

interface Props {
  gsId: string;
  onBack: () => void;
}

/** "Requires approval" for options whose allowed_status is CONDITIONAL (e.g. CSR, DD r17). */
export function AllowedStatusBadge({ option }: { option: StepOption }) {
  return option.allowed_status === 'CONDITIONAL' ? (
    <Badge variant="warning">Requires approval</Badge>
  ) : null;
}

function ActionError({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="form-control__error">
      {error.message}
      {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
    </p>
  );
}

/** Steps 2b / 2c (Replacement Executive, DEC-64): item lines of all cartons (doc qty + physical
 * qty) → "Next" → popup Replacement / Complete Sales Return → categorisation (condition split per
 * line, G-19) → Lock. After the lock only Super Admin / Management edit (reason, until routing).
 * Legacy statuses (CSR approval, inspection, RM review) keep their sections. Labels: GS_STATUS. */
export function ItemizationPage({ gsId, onBack }: Props) {
  const fetcher = useCallback(() => itemizationApi.state(gsId), [gsId]);
  const query = useApiQuery<ItemizationState>(fetcher);
  const state = query.data?.goods_slip.id === gsId ? query.data : null;
  const [docsOpen, setDocsOpen] = useState(false);
  const statusLabel = useStatusLabels();
  const title = `${statusLabel('ITEMIZATION')} & ${statusLabel('CATEGORISATION')}`;

  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Back
    </Button>
  );

  if (query.error && !state) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">{title}</h1>
        <ErrorState error={query.error} onRetry={query.reload} />
      </div>
    );
  }
  if (!state) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">{title}</h1>
        <LoadingState />
      </div>
    );
  }

  const gs = state.goods_slip;
  const documents = state.evidence.filter((a) => a.kind === 'DOC_PHOTO');
  const p = state.permissions;

  return (
    <div className="page itemize">
      {back}
      <div className="unboxing__head">
        <div style={{ minWidth: 0 }}>
          <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
            {gs.gs_no}
          </h1>
          <p className="page__subtitle unboxing__sub">
            <StatusChip status={gs.status} />
            {state.category_label ? <Badge variant="info">{state.category_label}</Badge> : null}
            {gs.original_category_code && gs.original_category_code !== gs.category_code ? (
              <Badge variant="neutral">Originally {gs.original_category_code}</Badge>
            ) : null}
            {gs.party_name ?? ''}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="itemize__docs-toggle"
          onClick={() => {
            setDocsOpen((o) => !o);
          }}
          aria-expanded={docsOpen}
        >
          <FileText size={16} aria-hidden="true" /> Documents ({documents.length})
        </Button>
      </div>
      {query.error ? <ErrorState error={query.error} onRetry={query.reload} /> : null}

      <div className="itemize-layout">
        <div className="itemize-layout__main">
          {gs.status === 'RM_REVIEW' ? (
            <div className="banner banner--success" role="status">
              Submitted to {statusLabel('RM_REVIEW')}. The Replacement Manager has been notified.
            </div>
          ) : null}
          {gs.status === HOLD ? (
            <div className="banner banner--warning" role="status" data-testid="sales-return-hold">
              {state.category_label ?? statusLabel(HOLD)} recorded: {statusLabel(HOLD)}. There are
              no further steps for now.
            </div>
          ) : null}
          {gs.status === LOCKED ? (
            <div
              className="banner banner--success"
              role="status"
              data-testid="categorisation-locked"
            >
              <Lock size={16} aria-hidden="true" /> Categorisation locked
              {gs.categorisation_locked_at
                ? ` on ${formatDateTime(gs.categorisation_locked_at)}`
                : ''}
              ; the goods are booked into Inward Staging. Waiting for the transfer slip.
              {p.edit_window_closed
                ? ' Department routing has started, so the lines can no longer change.'
                : ''}
            </div>
          ) : null}
          <LinesSection state={state} onChanged={query.reload} />
          {p.can_choose_return ? (
            <ReturnChoiceSection
              state={state}
              onDone={(next) => {
                query.setData(next);
              }}
            />
          ) : null}
          {gs.status === CATEGORISATION && gs.category_code === 'RO' && p.can_categorize ? (
            <LockSection
              state={state}
              onDone={(next) => {
                query.setData(next);
              }}
            />
          ) : null}
          {gs.category_code && ![CATEGORISATION, LOCKED, HOLD].includes(gs.status) ? (
            <DecisionSection state={state} onChanged={query.reload} />
          ) : null}
          {state.lots.length > 0 ? <StockSection state={state} onChanged={query.reload} /> : null}
          {state.corrections.length > 0 ? <CorrectionsHistory state={state} /> : null}
        </div>
        <DocumentPanel
          documents={documents}
          open={docsOpen}
          onClose={() => {
            setDocsOpen(false);
          }}
        />
      </div>
    </div>
  );
}

function LinesSection({ state, onChanged }: { state: ItemizationState; onChanged: () => void }) {
  const [editing, setEditing] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<ItemLine | null>(null);
  const [removing, setRemoving] = useState<ItemLine | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const gs = state.goods_slip;
  const p = state.permissions;
  // DEC-64: the item screen records quantities only; the split is entered at categorisation.
  const withSplit = gs.status !== 'ITEMIZATION';
  const lockedEdit = p.can_edit_locked === true;
  const lockedSave = (item: ItemLine | null): LockedSave => ({
    onSubmit: async (body, reason) => {
      const key = newIdempotencyKey();
      if (item) {
        await itemizationApi.lockedUpdateLine(
          gs.id,
          item.id,
          {
            ...(body.product_id !== item.product_id ? { product_id: body.product_id } : {}),
            documented_qty: body.documented_qty,
            received_qty: body.received_qty,
            buckets: body.buckets ?? [],
            counts: body.counts ?? [],
            reason,
          },
          key,
        );
      } else {
        await itemizationApi.lockedAddLine(
          gs.id,
          {
            product_id: body.product_id,
            documented_qty: body.documented_qty,
            received_qty: body.received_qty,
            buckets: body.buckets ?? [],
            counts: body.counts ?? [],
            reason,
          },
          key,
        );
      }
    },
  });
  // Excess only where a document qty was entered (it is optional at counting, Phase 3).
  const documentedExcess = state.items
    .filter((i) => i.documented_qty > 0)
    .reduce((sum, i) => sum + i.excess_qty, 0);
  const pendingCorrection = new Set(
    state.corrections.filter((c) => c.status === 'REQUESTED').map((c) => c.gs_item_id),
  );

  const remove = async (item: ItemLine) => {
    setBusy(item.id);
    setError(null);
    try {
      await itemizationApi.deleteItem(gs.id, item.id);
      onChanged();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card unboxing__section" aria-labelledby="lines-h">
      <h2 id="lines-h" className="unboxing__h2">
        {gs.status === 'ITEMIZATION'
          ? 'Items (all cartons)'
          : gs.status === CATEGORISATION
            ? 'Categorise each line'
            : 'Counted items'}
      </h2>
      {gs.status === CATEGORISATION ? (
        <p className="page__subtitle" style={{ margin: 0 }}>
          Split each line&apos;s physically received quantity into the conditions of its product.
        </p>
      ) : null}
      <p className="page__subtitle" style={{ margin: 0 }}>
        {state.totals.lines} line(s) · received {state.totals.received_qty}
        {state.totals.documented_qty > 0
          ? ` of ${String(state.totals.documented_qty)} as per document`
          : ''}
        {state.totals.short_qty > 0 ? ` · short ${String(state.totals.short_qty)}` : ''}
        {documentedExcess > 0 ? ` · excess ${String(documentedExcess)}` : ''}
      </p>
      {state.items.length === 0 ? (
        <p className="page__subtitle">
          {p.can_edit_lines ? 'No lines yet — add the first item below.' : 'No item lines yet.'}
        </p>
      ) : (
        <ul className="item-lines">
          {state.items.map((item) =>
            editing === item.id ? (
              <li key={item.id} className="item-line">
                <LineEditor
                  gsId={gs.id}
                  initial={item}
                  withSplit={withSplit}
                  locked={lockedEdit ? lockedSave(item) : undefined}
                  onSaved={() => {
                    setEditing(null);
                    onChanged();
                  }}
                  onCancel={() => {
                    setEditing(null);
                  }}
                />
              </li>
            ) : (
              <ItemLineCard
                key={item.id}
                item={item}
                actions={
                  lockedEdit && item.removed_at ? null : lockedEdit ? (
                    <span className="item-line__actions">
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Change line ${String(item.line_no)} (after the lock)`}
                        onClick={() => {
                          setEditing(item.id);
                        }}
                      >
                        <Pencil size={16} aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Remove line ${String(item.line_no)} (after the lock)`}
                        disabled={state.items.length <= 1}
                        onClick={() => {
                          setRemoving(item);
                        }}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </Button>
                    </span>
                  ) : p.can_edit_lines ? (
                    <span className="item-line__actions">
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Edit line ${String(item.line_no)}`}
                        onClick={() => {
                          setEditing(item.id);
                        }}
                      >
                        <Pencil size={16} aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Delete line ${String(item.line_no)}`}
                        isLoading={busy === item.id}
                        onClick={() => {
                          void remove(item);
                        }}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </Button>
                    </span>
                  ) : p.can_request_correction && !pendingCorrection.has(item.id) ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setCorrecting(item);
                      }}
                    >
                      Request correction
                    </Button>
                  ) : pendingCorrection.has(item.id) ? (
                    <Badge variant="warning">Correction pending</Badge>
                  ) : null
                }
              />
            ),
          )}
        </ul>
      )}
      <ActionError error={error} />
      {p.can_edit_lines && editing === null ? (
        <div className="itemize__add">
          <h3 className="itemize__h3">Add item</h3>
          <LineEditor gsId={gs.id} withSplit={withSplit} onSaved={onChanged} />
        </div>
      ) : null}
      {lockedEdit && editing === null ? (
        adding ? (
          <div className="itemize__add">
            <h3 className="itemize__h3">Add a line (after the lock)</h3>
            <LineEditor
              gsId={gs.id}
              locked={lockedSave(null)}
              onSaved={() => {
                setAdding(false);
                onChanged();
              }}
              onCancel={() => {
                setAdding(false);
              }}
            />
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus size={16} aria-hidden="true" /> Add a line
          </Button>
        )
      ) : null}
      {removing ? (
        <LockedRemoveDialog
          gsId={gs.id}
          item={removing}
          onClose={() => {
            setRemoving(null);
          }}
          onDone={() => {
            setRemoving(null);
            onChanged();
          }}
        />
      ) : null}
      {correcting ? (
        <CorrectionDialog
          gsId={gs.id}
          item={correcting}
          onClose={() => {
            setCorrecting(null);
          }}
          onDone={() => {
            setCorrecting(null);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

/** DEC-64 (a, b): "Next" → popup Replacement / Complete Sales Return (choices and labels from
 * RETURN_CATEGORY). The choice is final: Replacement → categorisation; Complete Sales Return →
 * on hold (Q11). */
function ReturnChoiceSection({
  state,
  onDone,
}: {
  state: ItemizationState;
  onDone: (next: ItemizationState) => void;
}) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const key = useRef<{ choice: string; key: string } | null>(null);
  const choices = state.return_choices ?? [];

  const confirm = async () => {
    setBusy(true);
    setError(null);
    if (key.current?.choice !== choice) key.current = { choice, key: newIdempotencyKey() };
    try {
      const res = await itemizationApi.chooseReturn(state.goods_slip.id, choice, key.current.key);
      setOpen(false);
      onDone(res.state);
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) key.current = null;
      setError(apiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sticky-submit unboxing__complete">
      <Button
        type="button"
        variant="primary"
        size="lg"
        data-testid="items-next"
        onClick={() => {
          setOpen(true);
        }}
      >
        Next <ArrowRight size={18} aria-hidden="true" />
      </Button>
      <span className="page__subtitle" style={{ margin: 0 }}>
        {state.totals.lines} line(s) · {state.totals.received_qty} pcs received
      </span>
      {open ? (
        <Modal
          isOpen
          onClose={() => {
            setOpen(false);
          }}
          title="What is this return?"
          footer={
            <>
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  setOpen(false);
                }}
              >
                Back to items
              </Button>
              <Button
                type="button"
                variant="primary"
                isLoading={busy}
                disabled={!choice}
                data-testid="return-choice-confirm"
                onClick={() => {
                  void confirm();
                }}
              >
                Confirm
              </Button>
            </>
          }
        >
          <div role="radiogroup" aria-label="Return type" className="category-options">
            {choices.map((o) => (
              <label
                key={o.code}
                className={`category-option${choice === o.code ? ' category-option--selected' : ''}`}
              >
                <input
                  type="radio"
                  name="return-choice"
                  value={o.code}
                  checked={choice === o.code}
                  onChange={() => {
                    setChoice(o.code);
                  }}
                />
                <span className="category-option__body">
                  <span className="category-option__title">{o.label}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="page__subtitle">This choice cannot be changed later.</p>
          <ActionError error={error} />
        </Modal>
      ) : null}
    </div>
  );
}

/** DEC-64 (c): lock the categorisation. One transaction books the physical quantities into
 * Inward Staging (Q12); afterwards only Super Admin / Management can change the lines. */
function LockSection({
  state,
  onDone,
}: {
  state: ItemizationState;
  onDone: (next: ItemizationState) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const key = useRef<string | null>(null);
  const unbalanced = state.items.filter((i) => i.is_balanced === false);

  const lock = async () => {
    setBusy(true);
    setError(null);
    key.current ??= newIdempotencyKey();
    try {
      const res = await itemizationApi.lockCategorisation(state.goods_slip.id, null, key.current);
      onDone(res.state);
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) key.current = null;
      setError(apiError);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <section className="card unboxing__section" aria-labelledby="lock-h">
      <h2 id="lock-h" className="unboxing__h2">
        <Lock size={18} aria-hidden="true" /> Lock Categorisation
      </h2>
      {unbalanced.length > 0 ? (
        <p role="alert" className="form-control__error" data-testid="unbalanced-lines">
          The condition split does not match the physical quantity on line(s){' '}
          {unbalanced.map((i) => `#${String(i.line_no)}`).join(', ')}.
        </p>
      ) : null}
      <ActionError error={error} />
      {confirming ? (
        <>
          <p className="page__subtitle" style={{ margin: 0 }}>
            Locking books {state.totals.received_qty} piece(s) into Inward Staging. Afterwards only
            Super Admin or Management can change the lines.
          </p>
          <div className="line-editor__actions">
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
              }}
            >
              Keep editing
            </Button>
            <Button
              type="button"
              variant="primary"
              isLoading={busy}
              data-testid="lock-confirm"
              onClick={() => {
                void lock();
              }}
            >
              Confirm lock
            </Button>
          </div>
        </>
      ) : (
        <Button
          type="button"
          variant="primary"
          size="lg"
          disabled={state.permissions.can_lock !== true}
          data-testid="lock-categorisation"
          onClick={() => {
            setConfirming(true);
          }}
        >
          <Lock size={16} aria-hidden="true" /> Lock Categorisation
        </Button>
      )}
    </section>
  );
}

/** DEC-64 d: remove a line after the lock (reason required; a stocked line stays with qty 0). */
function LockedRemoveDialog({
  gsId,
  item,
  onClose,
  onDone,
}: {
  gsId: string;
  item: ItemLine;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const key = useRef<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    key.current ??= newIdempotencyKey();
    try {
      await itemizationApi.lockedRemoveLine(gsId, item.id, reason.trim(), key.current);
      onDone();
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) key.current = null;
      setError(apiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Remove line ${String(item.line_no)}`}
      footer={
        <>
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={reason.trim().length < 3}
            onClick={() => {
              void submit();
            }}
          >
            Remove line
          </Button>
        </>
      }
    >
      <p className="page__subtitle">
        {item.product_name}: its stock is taken out of Inward Staging. The line stays in the history
        with quantity 0.
      </p>
      <label className="form-label" htmlFor="locked-remove-reason">
        Reason (required)
      </label>
      <Textarea
        id="locked-remove-reason"
        rows={3}
        maxLength={500}
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      <ActionError error={error} />
    </Modal>
  );
}

function DecisionSection({ state, onChanged }: { state: ItemizationState; onChanged: () => void }) {
  const gs = state.goods_slip;
  const [reopenOpen, setReopenOpen] = useState(false);
  return (
    <section className="card unboxing__section" aria-labelledby="decision-h">
      <h2 id="decision-h" className="unboxing__h2">
        Categorisation &amp; approval
      </h2>
      {gs.status === 'CSR_APPROVAL_PENDING' && state.permissions.can_decide ? (
        <CsrDecisionCard
          goodsSlip={gs}
          items={state.items}
          totals={state.totals}
          categoryLabel={state.category_label}
          evidence={state.evidence}
          options={state.decision_options}
          onDecided={onChanged}
        />
      ) : gs.status === 'CSR_APPROVAL_PENDING' ? (
        <div className="banner banner--warning" role="status">
          Waiting for the Replacement Manager&apos;s decision.
        </div>
      ) : null}
      {state.decisions.length > 0 ? (
        <ul className="decision-list">
          {state.decisions.map((d) => (
            <li key={d.id} className={d.is_current ? '' : 'decision-list__old'}>
              <strong>{d.decision_label}</strong>
              {d.is_admin_action ? (
                <>
                  {' '}
                  <Badge variant="danger">Admin action</Badge>
                </>
              ) : null}
              <div className="item-line__meta">
                {d.decided_by_name ?? ''} · {formatDateTime(d.decided_at)}
              </div>
              {d.remarks ? <div>{d.remarks}</div> : null}
              {d.reopened_at ? (
                <div className="item-line__meta">
                  Reopened by {d.reopened_by_name ?? ''} · {formatDateTime(d.reopened_at)}:{' '}
                  {d.reopen_reason}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {gs.csr_commercial_path ? (
        <p className="page__subtitle">Flagged for the Complete Sales Return commercial path.</p>
      ) : null}
      {state.transfers.map((t) => (
        <div key={t.id} className="transfer-card" data-testid="transfer-card">
          <strong>{t.transfer_no}</strong> <Badge variant="info">{humanize(t.status)}</Badge>
          {t.with_packaging ? (
            <>
              {' '}
              <Badge variant="neutral">With packaging</Badge>
            </>
          ) : null}
          <div className="item-line__meta">
            {t.from_location_name} → {t.to_location_name}
            {t.stock_moved ? '' : ' · awaiting handover'}
          </div>
          <div className="item-line__meta">
            {t.lines
              .map(
                (l) =>
                  `#${String(l.line_no ?? '')} ${l.product_name ?? ''} × ${String(l.qty_sent)}`,
              )
              .join(' · ')}
          </div>
          {t.notes ? <div>{t.notes}</div> : null}
        </div>
      ))}
      {state.permissions.can_reopen ? (
        <div style={{ marginTop: '0.75rem' }}>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setReopenOpen(true);
            }}
          >
            Reopen decision
          </Button>
        </div>
      ) : null}
      {reopenOpen ? (
        <ReopenDialog
          gsId={gs.id}
          onClose={() => {
            setReopenOpen(false);
          }}
          onDone={() => {
            setReopenOpen(false);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

function StockSection({ state, onChanged }: { state: ItemizationState; onChanged: () => void }) {
  const byItem = new Map(state.items.map((i) => [i.id, i]));
  return (
    <section className="card unboxing__section" aria-labelledby="stock-h">
      <h2 id="stock-h" className="unboxing__h2">
        Stock
      </h2>
      <ul className="item-lines">
        {state.lots.map((lot) => {
          const item = lot.gs_item_id ? byItem.get(lot.gs_item_id) : undefined;
          return (
            <li key={lot.lot_id} className="item-line" data-testid="lot-row">
              <div className="item-line__name">
                {item ? `#${String(item.line_no)} ${item.product_name ?? ''}` : 'Lot'} ·{' '}
                {humanize(lot.condition_class)}
              </div>
              <div className="item-line__meta">
                {lot.balances.map((b) => `${b.location_name}: ${String(b.qty)}`).join(' · ') ||
                  'No stock'}
              </div>
              {lot.packaging_checks.map((c) => (
                <div key={c.id} className="item-line__meta">
                  Packaging {c.result_code === 'OK' ? 'OK' : `replaced × ${String(c.qty_replaced)}`}{' '}
                  · {c.by_name ?? ''} · {formatDateTime(c.at)}
                  {c.remarks ? ` · ${c.remarks}` : ''}
                </div>
              ))}
              {state.permissions.can_check_packaging && lot.total_qty > 0 ? (
                <PackagingCheckForm lot={lot} onDone={onChanged} />
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function PackagingCheckForm({ lot, onDone }: { lot: Lot; onDone: () => void }) {
  const [result, setResult] = useState<'OK' | 'REPLACED'>('OK');
  const [qty, setQty] = useState(0);
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await itemizationApi.packagingCheck(lot.lot_id, {
        result,
        qty_replaced: result === 'OK' ? 0 : qty,
        remarks: remarks.trim() || null,
      });
      setQty(0);
      setRemarks('');
      onDone();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="packaging-form">
      <div role="radiogroup" aria-label="Packaging check" className="picker__buttons">
        {(['OK', 'REPLACED'] as const).map((r) => (
          <label key={r} className="chip" style={{ cursor: 'pointer' }}>
            <input
              type="radio"
              name={`pkg-${lot.lot_id}`}
              checked={result === r}
              onChange={() => {
                setResult(r);
              }}
            />
            {r === 'OK' ? 'Packaging OK' : 'Packaging replaced'}
          </label>
        ))}
      </div>
      {result === 'REPLACED' ? (
        <QtyStepper
          id={`pkg-qty-${lot.lot_id}`}
          label="Pieces repackaged"
          value={qty}
          onChange={setQty}
        />
      ) : null}
      <Textarea
        aria-label="Packaging remarks"
        rows={1}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      <ActionError error={error} />
      <Button
        type="button"
        variant="secondary"
        isLoading={busy}
        disabled={result === 'REPLACED' && qty <= 0}
        onClick={() => {
          void submit();
        }}
      >
        Record packaging check
      </Button>
    </div>
  );
}

function CorrectionsHistory({ state }: { state: ItemizationState }) {
  return (
    <section className="card unboxing__section" aria-labelledby="corr-h">
      <h2 id="corr-h" className="unboxing__h2">
        Line corrections
      </h2>
      <ul className="decision-list">
        {state.corrections.map((c) => (
          <li key={c.id}>
            <strong>
              Line {c.line_no}: {c.old_documented_qty}/{c.old_received_qty} → {c.new_documented_qty}
              /{c.new_received_qty}
            </strong>{' '}
            <Badge
              variant={
                c.status === 'APPROVED' ? 'success' : c.status === 'REJECTED' ? 'danger' : 'warning'
              }
            >
              {humanize(c.status)}
            </Badge>
            <div>{c.reason}</div>
            <div className="item-line__meta">
              {c.requested_by_name ?? ''} · {formatDateTime(c.requested_at)}
              {c.decided_by_name ? ` · ${c.decided_by_name}` : ''}
              {c.decision_remarks ? `: ${c.decision_remarks}` : ''}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CorrectionDialog({
  gsId,
  item,
  onClose,
  onDone,
}: {
  gsId: string;
  item: ItemLine;
  onClose: () => void;
  onDone: () => void;
}) {
  const [documented, setDocumented] = useState(item.documented_qty);
  const [received, setReceived] = useState(item.received_qty);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const changed = documented !== item.documented_qty || received !== item.received_qty;
  return (
    <Modal isOpen onClose={onClose} title={`Correct line ${String(item.line_no)}`}>
      <p className="page__subtitle">
        {item.product_name} — the Replacement Manager approves the change; stock is adjusted.
      </p>
      <div className="line-editor__steppers">
        <QtyStepper
          id="corr-documented"
          label="As per document"
          value={documented}
          onChange={setDocumented}
        />
        <QtyStepper
          id="corr-received"
          label="Physically received"
          value={received}
          onChange={setReceived}
        />
      </div>
      <div style={{ margin: '0.5rem 0' }}>
        <QtyBadges documented={documented} received={received} />
      </div>
      <label className="form-label" htmlFor="corr-reason">
        Reason (mandatory)
      </label>
      <Textarea
        id="corr-reason"
        rows={2}
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      <ActionError error={error} />
      <div className="line-editor__actions">
        <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={!changed || reason.trim().length < 3}
          onClick={() => {
            setBusy(true);
            setError(null);
            itemizationApi
              .requestCorrection(gsId, item.id, {
                documented_qty: documented,
                received_qty: received,
                reason: reason.trim(),
              })
              .then(onDone, (err: unknown) => {
                setError(toApiError(err));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          Request correction
        </Button>
      </div>
    </Modal>
  );
}

function ReopenDialog({
  gsId,
  onClose,
  onDone,
}: {
  gsId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <Modal isOpen onClose={onClose} title="Reopen CSR decision">
      <label className="form-label" htmlFor="reopen-reason">
        Reason (mandatory, audited)
      </label>
      <Textarea
        id="reopen-reason"
        rows={3}
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      <ActionError error={error} />
      <div className="line-editor__actions">
        <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
          Keep decision
        </Button>
        <Button
          type="button"
          variant="danger"
          isLoading={busy}
          disabled={reason.trim().length < 3}
          onClick={() => {
            setBusy(true);
            setError(null);
            itemizationApi
              .reopen(gsId, reason.trim())
              .then(onDone, (err: unknown) => {
                setError(toApiError(err));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          Reopen
        </Button>
      </div>
    </Modal>
  );
}
