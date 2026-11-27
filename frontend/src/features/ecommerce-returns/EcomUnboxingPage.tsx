/**
 * DEC-76: E-Commerce unboxing by the unboxing / verifier user.
 *
 * Every return the E-Commerce Executive finished is shown at a glance, per platform and per day.
 * For each order the user splits the received pieces: Good / Fresh → Store (the store acknowledges
 * them), Production / Repair (back to the store after repair) or Damaged / Wastage. Submitting the
 * selected orders of ONE platform creates one E-Commerce Action Sheet (order ids, Qty Received,
 * Qty Issue CN) for Accounts. A "Different Product" is not in the product master: all its pieces
 * are wastage. The server enforces every rule again; labels come from configuration (rule e).
 */
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { ChevronRight, PackageOpen, RefreshCw, Wrench } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  QtyStepper,
  Select,
  Textarea,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';
import '@/features/goods-slips/gateForm.css';

import { settlementApi } from './api';
import type { RepairRow, UnboxingQueue, UnboxingRow } from './types';

interface Props {
  canEdit: boolean;
  onOpen: (returnId: string) => void;
  onOpenSheet: (sheetId: string) => void;
}

interface Draft {
  include: boolean;
  good: number;
  repair: number;
  wastage: number;
  repairLoc: string;
  note: string;
}

function defaultDraft(r: UnboxingRow): Draft {
  return {
    include: true,
    good: r.is_company_product ? r.qty : 0,
    repair: 0,
    wastage: r.is_company_product ? 0 : r.qty,
    repairLoc: '',
    note: '',
  };
}

function problemOf(r: UnboxingRow, d: Draft): string | null {
  if (d.good + d.repair + d.wastage !== r.qty) {
    return `Store + repair + wastage must be ${String(r.qty)}`;
  }
  if (d.repair > 0 && !d.repairLoc) return 'Choose the repair department';
  return null;
}

export const EcomUnboxingPage: React.FC<Props> = ({ canEdit, onOpen, onOpenSheet }) => {
  const fetcher = useCallback(() => settlementApi.unboxing(), []);
  const query = useApiQuery<UnboxingQueue>(fetcher);
  const [platform, setPlatform] = useState<string>('');
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [repairing, setRepairing] = useState<RepairRow | null>(null);
  const submitKey = useRef(newIdempotencyKey());

  const data = query.data;
  const platforms = useMemo(() => {
    const counts = new Map<string, { label: string; n: number }>();
    for (const r of data?.rows ?? []) {
      const c = counts.get(r.platform_code) ?? { label: r.platform_label, n: 0 };
      c.n += 1;
      counts.set(r.platform_code, c);
    }
    return [...counts.entries()].map(([code, v]) => ({ code, ...v }));
  }, [data]);
  const active = platforms.some((p) => p.code === platform) ? platform : (platforms[0]?.code ?? '');
  const rows = useMemo(
    () => (data?.rows ?? []).filter((r) => r.platform_code === active),
    [data, active],
  );
  const byDate = useMemo(() => {
    const groups = new Map<string, UnboxingRow[]>();
    for (const r of rows) {
      const list = groups.get(r.entry_date) ?? [];
      list.push(r);
      groups.set(r.entry_date, list);
    }
    return [...groups.entries()];
  }, [rows]);

  const draftOf = (r: UnboxingRow): Draft => drafts[r.return_id] ?? defaultDraft(r);
  const setDraft = (r: UnboxingRow, patch: Partial<Draft>) => {
    setDrafts((prev) => ({
      ...prev,
      [r.return_id]: { ...(prev[r.return_id] ?? defaultDraft(r)), ...patch },
    }));
  };
  const label = (code: string, fallback: string) =>
    data?.buckets.find((b) => b.code === code)?.label ?? fallback;

  const chosen = rows.filter((r) => draftOf(r).include);
  const problems = chosen.map((r) => problemOf(r, draftOf(r))).filter(Boolean);
  const cnTotal = chosen.reduce((sum, r) => sum + r.cn_qty, 0);
  const activeLabel = platforms.find((p) => p.code === active)?.label ?? '';

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const sheet = await settlementApi.unbox(
        active,
        chosen.map((r) => {
          const d = draftOf(r);
          return {
            return_id: r.return_id,
            good_qty: d.good,
            repair_qty: d.repair,
            wastage_qty: d.wastage,
            repair_location_id: d.repair > 0 ? d.repairLoc : null,
            note: d.note.trim() || null,
          };
        }),
        submitKey.current,
      );
      submitKey.current = newIdempotencyKey();
      setDrafts({});
      onOpenSheet(sheet.id);
    } catch (err) {
      console.error('Unboxing failed', { platform: active, err });
      setError(toApiError(err));
      submitKey.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-unboxing">
      <PageHeader
        title="E-Commerce Unboxing"
        subtitle="Split each order's pieces between the store, repair and wastage. One platform per action sheet."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />

      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the returns" />
      ) : !data ? (
        <LoadingState label="Loading returns…" />
      ) : (
        <>
          {data.rows.length === 0 ? (
            <EmptyState
              title="Nothing to unbox"
              hint="Returns appear here after the E-Commerce Executive records the ticket outcome or the portal check."
            />
          ) : (
            <>
              <div className="gate-return-type" role="tablist" aria-label="Platform">
                {platforms.map((p) => (
                  <button
                    key={p.code}
                    type="button"
                    role="tab"
                    aria-selected={active === p.code}
                    aria-checked={active === p.code}
                    className="gate-return-type__option"
                    data-testid={`unbox-platform-${p.code}`}
                    onClick={() => {
                      setPlatform(p.code);
                    }}
                  >
                    {p.label} ({p.n})
                  </button>
                ))}
              </div>

              {byDate.map(([day, list]) => (
                <section
                  key={day}
                  className="space-y-3"
                  aria-label={`Returns of ${formatDate(day)}`}
                >
                  <h2 className="m-0 text-sm font-semibold text-slate-600 dark:text-slate-300">
                    {formatDate(day)} · {list.length} order(s)
                  </h2>
                  <ul className="m-0 list-none space-y-3 p-0">
                    {list.map((r) => {
                      const d = draftOf(r);
                      const problem = d.include ? problemOf(r, d) : null;
                      return (
                        <li
                          key={r.return_id}
                          className={`space-y-3 rounded-xl border bg-white p-4 shadow-sm dark:bg-slate-900 ${
                            problem
                              ? 'border-red-300 dark:border-red-800'
                              : 'border-slate-200 dark:border-slate-800'
                          }`}
                          data-testid={`unbox-${r.return_no}`}
                        >
                          <div className="flex items-start gap-3">
                            {canEdit ? (
                              <input
                                type="checkbox"
                                className="mt-1 h-6 w-6 shrink-0"
                                aria-label={`Include ${r.return_no}`}
                                checked={d.include}
                                onChange={(e) => {
                                  setDraft(r, { include: e.target.checked });
                                }}
                              />
                            ) : null}
                            <button
                              type="button"
                              className="flex min-h-[44px] min-w-0 flex-1 items-center gap-3 border-0 bg-transparent p-0 text-left"
                              onClick={() => {
                                onOpen(r.return_id);
                              }}
                            >
                              <div className="min-w-0 flex-1 space-y-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-semibold">Order {r.order_id}</span>
                                  <Badge variant={r.cn_qty > 0 ? 'warning' : 'success'}>
                                    {r.resolution_label} · {r.resolution_qty}
                                  </Badge>
                                  {r.cn_qty > 0 ? (
                                    <Badge variant="info">Qty Issue CN {r.cn_qty}</Badge>
                                  ) : null}
                                </div>
                                <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                                  {r.return_no} · {r.product_text} · Received {r.qty}
                                </div>
                                {r.resolution_note ? (
                                  <div className="break-words text-xs text-slate-500">
                                    “{r.resolution_note}”
                                  </div>
                                ) : null}
                                {r.store_name ? (
                                  <div className="text-xs text-slate-500">
                                    Store: {r.store_name}
                                  </div>
                                ) : null}
                              </div>
                              <ChevronRight
                                className="h-5 w-5 shrink-0 text-slate-400"
                                aria-hidden="true"
                              />
                            </button>
                          </div>

                          {canEdit && d.include ? (
                            <div className="space-y-3">
                              {r.is_company_product ? (
                                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                  <QtyField
                                    label={label('TO_STORE', 'Store')}
                                    value={d.good}
                                    max={r.qty}
                                    tone="success"
                                    testId="unbox-good"
                                    onChange={(v) => {
                                      setDraft(r, { good: v });
                                    }}
                                  />
                                  <QtyField
                                    label={label('TO_REPAIR', 'Repair')}
                                    value={d.repair}
                                    max={r.qty}
                                    tone="warning"
                                    testId="unbox-repair"
                                    onChange={(v) => {
                                      setDraft(r, { repair: v });
                                    }}
                                  />
                                  <QtyField
                                    label={label('WASTAGE', 'Wastage')}
                                    value={d.wastage}
                                    max={r.qty}
                                    tone="danger"
                                    testId="unbox-wastage"
                                    onChange={(v) => {
                                      setDraft(r, { wastage: v });
                                    }}
                                  />
                                </div>
                              ) : (
                                <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
                                  Not our product: all {r.qty} piece(s) are recorded as{' '}
                                  {label('WASTAGE', 'wastage')}.
                                </p>
                              )}
                              {d.repair > 0 ? (
                                <Select
                                  id={`repair-loc-${r.return_id}`}
                                  aria-label="Repair department"
                                  placeholder="-- Repair department --"
                                  options={data.repair_locations.map((l) => ({
                                    value: l.id,
                                    label: l.name,
                                  }))}
                                  value={d.repairLoc}
                                  onChange={(e) => {
                                    setDraft(r, { repairLoc: e.target.value });
                                  }}
                                />
                              ) : null}
                              <Textarea
                                aria-label={`Note for ${r.return_no}`}
                                placeholder="Note (optional)"
                                rows={1}
                                maxLength={300}
                                value={d.note}
                                onChange={(e) => {
                                  setDraft(r, { note: e.target.value });
                                }}
                              />
                              {problem ? (
                                <p className="form-control__error m-0" role="alert">
                                  {problem}
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </>
          )}

          <RepairSection
            repairs={data.repairs}
            canEdit={canEdit}
            onOpen={onOpen}
            onRecord={setRepairing}
          />
        </>
      )}

      {error ? <ErrorState error={error} title="Could not create the action sheet" /> : null}

      {canEdit && data && rows.length > 0 ? (
        <div className="sticky bottom-[4.5rem] z-20 rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-xl shadow-slate-900/10 backdrop-blur sm:bottom-3 sm:p-4 dark:border-slate-800 dark:bg-slate-950/95">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <p className="m-0 flex-1 text-sm">
              <strong>{activeLabel}</strong> · {chosen.length} order(s) · Qty Issue CN {cnTotal}
              {problems.length > 0 ? (
                <span className="text-red-600"> · fix {problems.length} order(s)</span>
              ) : null}
            </p>
            <Button
              type="button"
              className="min-h-[44px]"
              disabled={busy || chosen.length === 0 || problems.length > 0}
              data-testid="unbox-submit"
              onClick={() => {
                void submit();
              }}
            >
              <PackageOpen className="h-4 w-4" aria-hidden="true" /> Create action sheet
            </Button>
          </div>
        </div>
      ) : null}

      {repairing ? (
        <RepairBackModal
          row={repairing}
          onClose={() => {
            setRepairing(null);
          }}
          onDone={() => {
            setRepairing(null);
            query.reload();
          }}
        />
      ) : null}
    </div>
  );
};

function QtyField({
  label,
  value,
  max,
  tone,
  testId,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  tone: 'success' | 'warning' | 'danger';
  testId: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1" data-testid={testId}>
      <span className="block text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
      <QtyStepper value={value} max={max} tone={tone} label={label} onChange={onChange} />
    </div>
  );
}

function RepairSection({
  repairs,
  canEdit,
  onOpen,
  onRecord,
}: {
  repairs: RepairRow[];
  canEdit: boolean;
  onOpen: (returnId: string) => void;
  onRecord: (r: RepairRow) => void;
}) {
  return (
    <section className="space-y-3" aria-label="Pieces at repair">
      <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
        <Wrench className="h-4 w-4" aria-hidden="true" /> At repair ({repairs.length})
      </h2>
      {repairs.length === 0 ? (
        <p className="m-0 text-sm text-slate-500">No E-Commerce piece is at a repair department.</p>
      ) : (
        <ul className="m-0 list-none space-y-2 p-0">
          {repairs.map((r) => (
            <li
              key={r.repair_id}
              className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-3 sm:flex-row sm:items-center dark:border-slate-800 dark:bg-slate-900"
              data-testid={`repair-${r.return_no}`}
            >
              <button
                type="button"
                className="min-h-[44px] min-w-0 flex-1 border-0 bg-transparent p-0 text-left"
                onClick={() => {
                  onOpen(r.return_id);
                }}
              >
                <div className="font-semibold">
                  {r.platform_label} · Order {r.order_id}
                </div>
                <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                  {r.product_text} · {r.qty_sent} pc(s) at {r.location_name} since{' '}
                  {formatDateTime(r.sent_at)}
                </div>
              </button>
              {canEdit ? (
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  data-testid="repair-record"
                  onClick={() => {
                    onRecord(r);
                  }}
                >
                  Record back from repair
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RepairBackModal({
  row,
  onClose,
  onDone,
}: {
  row: RepairRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const [ok, setOk] = useState(row.qty_sent);
  const [note, setNote] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const scrap = row.qty_sent - ok;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await settlementApi.repairReturn(
        row.repair_id,
        { qty_ok: ok, qty_scrap: scrap, note: note.trim() || null },
        key.current,
      );
      onDone();
    } catch (err) {
      console.error('Recording the repair return failed', { repairId: row.repair_id, err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Back from repair · Order ${row.order_id}`}
      footer={
        <>
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            className="min-h-[44px]"
            disabled={busy}
            data-testid="repair-save"
            onClick={() => {
              void save();
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
          {row.qty_sent} pc(s) sent to {row.location_name}. OK pieces go to the store (the store
          acknowledges them); the rest are scrapped.
        </p>
        <div className="space-y-1">
          <span className="block text-xs font-medium">OK (to the store)</span>
          <QtyStepper
            value={ok}
            max={row.qty_sent}
            tone="success"
            label="OK pieces"
            onChange={setOk}
          />
        </div>
        <p className="m-0 text-sm">Scrap: {scrap}</p>
        <Textarea
          aria-label="Note"
          placeholder="Note (optional)"
          rows={2}
          maxLength={300}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
        {error ? <ErrorState error={error} title="Could not save" /> : null}
      </div>
    </Modal>
  );
}
