import { useCallback, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Barcode,
  Calendar,
  CheckCircle2,
  Minus,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';
import { apiRequest } from '@/lib/api/client';
import { ComplianceCalendar } from './ComplianceCalendar';
import type { TodayAuditData } from './types';

function getTodayString(): string {
  const now = new Date();
  const year = String(now.getFullYear());
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function DailyAuditPage() {
  const { status } = useAuth();
  const signedIn = status === 'signed-in';

  const [auditDate, setAuditDate] = useState<string>(getTodayString);
  const [activeTab, setActiveTab] = useState<'register' | 'calendar'>('register');
  const [barcodeSearch, setBarcodeSearch] = useState('');
  const [confirmedCheckOverride, setConfirmedCheckOverride] = useState<boolean | null>(null);
  const [lateReason, setLateReason] = useState('');
  const [generalRemarks, setGeneralRemarks] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionMessage, setActionMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  // User edits over fetched data: container_id -> Partial counts
  const [overrides, setOverrides] = useState<
    Record<string, { counted_qty?: number; sellable_packaging_qty?: number; remarks?: string }>
  >({});

  // The register shown is the one for the selected date (P2-08 fix: it always loaded today's,
  // so a late entry displayed - and was gated by - today's status and counts).
  const fetcher = useCallback(() => {
    return apiRequest<TodayAuditData>(
      auditDate === getTodayString() ? '/container-audits/today' : `/container-audits/${auditDate}`,
    );
  }, [auditDate]);

  const { data, loading, error, reload } = useApiQuery<TodayAuditData>(fetcher);

  const updateLine = (
    containerId: string,
    field: 'counted_qty' | 'sellable_packaging_qty' | 'remarks',
    value: unknown,
  ) => {
    setOverrides((prev) => {
      const cur = prev[containerId] ?? {};
      return {
        ...prev,
        [containerId]: {
          ...cur,
          [field]:
            field === 'counted_qty' || field === 'sellable_packaging_qty'
              ? Math.max(0, Number(value) || 0)
              : String(value),
        },
      };
    });
  };

  const containers = data?.containers;
  const filteredContainers = useMemo(() => {
    if (!containers) return [];
    if (!barcodeSearch.trim()) return containers;
    const q = barcodeSearch.trim().toLowerCase();
    return containers.filter(
      (c) =>
        c.container_code.toLowerCase().includes(q) ||
        c.container_barcode.toLowerCase().includes(q) ||
        (c.container_name !== null && c.container_name.toLowerCase().includes(q)),
    );
  }, [containers, barcodeSearch]);

  const isPastDate = useMemo(() => {
    return auditDate < getTodayString();
  }, [auditDate]);

  const isConfirmed = data?.day.confirmed ?? false;
  const isChecked = confirmedCheckOverride ?? isConfirmed;

  const handleSaveCounts = async () => {
    if (!data) return;
    setIsSubmitting(true);
    setActionMessage(null);
    try {
      const lines = data.containers.map((c) => {
        const o = overrides[c.container_id];
        return {
          container_id: c.container_id,
          counted_qty: o?.counted_qty ?? c.counted_qty,
          sellable_packaging_qty: o?.sellable_packaging_qty ?? c.sellable_packaging_qty,
          remarks: o?.remarks ?? c.remarks ?? null,
        };
      });

      await apiRequest(`/container-audits/${auditDate}/lines`, {
        method: 'PUT',
        body: { lines },
      });
      setActionMessage({ type: 'success', text: 'Container counts saved successfully.' });
      setOverrides({});
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save counts';
      setActionMessage({ type: 'error', text: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmAudit = async () => {
    if (!data) return;
    if (!isChecked) {
      setActionMessage({
        type: 'error',
        text: 'You must check the confirmation checkbox to submit.',
      });
      return;
    }
    if (isPastDate && !lateReason.trim()) {
      setActionMessage({ type: 'error', text: 'Late reason is mandatory for past dates.' });
      return;
    }

    setIsSubmitting(true);
    setActionMessage(null);
    try {
      const lines = data.containers.map((c) => {
        const o = overrides[c.container_id];
        return {
          container_id: c.container_id,
          counted_qty: o?.counted_qty ?? c.counted_qty,
          sellable_packaging_qty: o?.sellable_packaging_qty ?? c.sellable_packaging_qty,
          remarks: o?.remarks ?? c.remarks ?? null,
        };
      });

      await apiRequest(`/container-audits/${auditDate}/confirm`, {
        method: 'POST',
        body: {
          confirmed: true,
          late_reason: isPastDate ? lateReason.trim() : null,
          remarks: generalRemarks.trim() || null,
          lines,
        },
      });
      setActionMessage({ type: 'success', text: 'Daily container audit confirmed successfully!' });
      setOverrides({});
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to confirm audit';
      setActionMessage({ type: 'error', text: msg });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!signedIn) {
    return (
      <EmptyState
        title="Sign in required"
        hint="Please sign in to access the container register."
      />
    );
  }

  if (loading && !data) {
    return <LoadingState label="Loading daily container register..." />;
  }

  if (error && !data) {
    return (
      <ErrorState error={error} onRetry={reload} title="Could not load daily container audit." />
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6 pb-28">
      {/* Header and Mode Toggle */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-foreground flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-primary" />
            Daily DMT Container Register
          </h1>
          <p className="text-xs sm:text-sm text-muted-foreground mt-1">
            Mandatory daily count of all active DMT containers & sellable packaging separation.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <Button
            variant={activeTab === 'register' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => {
              setActiveTab('register');
            }}
          >
            Daily Register
          </Button>
          <Button
            variant={activeTab === 'calendar' ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => {
              setActiveTab('calendar');
            }}
          >
            <Calendar className="w-4 h-4 mr-1.5" />
            Compliance Calendar
          </Button>
        </div>
      </div>

      {actionMessage && (
        <div
          role="alert"
          className={`p-3.5 rounded-lg border text-sm font-medium flex items-center gap-2.5 ${
            actionMessage.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-destructive/10 border-destructive/30 text-destructive'
          }`}
        >
          {actionMessage.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          )}
          <span>{actionMessage.text}</span>
        </div>
      )}

      {activeTab === 'calendar' ? (
        <ComplianceCalendar />
      ) : (
        <>
          {/* Day Status Strip */}
          <div className="bg-card border border-border rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <label
                htmlFor="audit-date"
                className="text-xs font-semibold uppercase text-muted-foreground"
              >
                Audit Date:
              </label>
              <input
                id="audit-date"
                type="date"
                value={auditDate}
                max={getTodayString()}
                onChange={(e) => {
                  // Unsaved edits belong to the previous date; never carry them over.
                  setOverrides({});
                  setConfirmedCheckOverride(null);
                  setLateReason('');
                  setAuditDate(e.target.value);
                }}
                className="bg-background border border-input rounded-md px-2.5 py-1 text-sm font-medium focus:ring-1 focus:ring-primary"
              />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Day Status:</span>
              <Badge
                variant={
                  data?.day.status === 'CONFIRMED'
                    ? 'success'
                    : data?.day.status === 'LATE'
                      ? 'warning'
                      : data?.day.status === 'MISSED'
                        ? 'danger'
                        : 'default'
                }
              >
                {data?.day.status ?? 'PENDING'}
              </Badge>
              {data?.day.confirmed_at ? (
                <span className="text-xs text-muted-foreground hidden sm:inline">
                  (Confirmed by {data.day.confirmed_by_name ?? 'Verifier'})
                </span>
              ) : null}
            </div>
          </div>

          {/* Barcode Search / Quick Jump */}
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Scan or enter container barcode / code to quick-jump..."
              value={barcodeSearch}
              onChange={(e) => {
                setBarcodeSearch(e.target.value);
              }}
              className="w-full pl-10 pr-4 py-2.5 bg-card border border-input rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            {barcodeSearch ? (
              <button
                type="button"
                onClick={() => {
                  setBarcodeSearch('');
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-foreground"
              >
                Clear
              </button>
            ) : null}
          </div>

          {/* Container Cards List */}
          <div className="space-y-4">
            {filteredContainers.length === 0 ? (
              <EmptyState
                title="No containers found"
                hint="No active DMT container matched your search term."
              />
            ) : (
              filteredContainers.map((container) => {
                const count =
                  overrides[container.container_id]?.counted_qty ?? container.counted_qty;
                const packaging =
                  overrides[container.container_id]?.sellable_packaging_qty ??
                  container.sellable_packaging_qty;
                const remarks =
                  overrides[container.container_id]?.remarks ?? container.remarks ?? '';

                return (
                  <div
                    key={container.container_id}
                    className={`bg-card border rounded-xl p-4 sm:p-5 transition-colors ${
                      barcodeSearch &&
                      container.container_barcode
                        .toLowerCase()
                        .includes(barcodeSearch.toLowerCase())
                        ? 'border-primary ring-2 ring-primary/20'
                        : 'border-border'
                    }`}
                  >
                    {/* Container Title Header */}
                    <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-border/60">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-foreground text-base">
                            {container.container_code}
                          </h3>
                          <Badge variant="neutral" className="text-xs font-mono">
                            <Barcode className="w-3 h-3 mr-1" />
                            {container.container_barcode}
                          </Badge>
                        </div>
                        {container.container_name ? (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {container.container_name}
                          </p>
                        ) : null}
                      </div>

                      {/* Yesterday Reference Count */}
                      <div className="text-right text-xs text-muted-foreground bg-muted/40 px-2.5 py-1 rounded">
                        <span>Yesterday: </span>
                        <span className="font-semibold text-foreground">
                          {String(container.yesterday_counted_qty ?? 0)} pcs
                        </span>
                        {container.yesterday_sellable_packaging_qty !== null ? (
                          <span className="ml-1 text-emerald-500">
                            ({String(container.yesterday_sellable_packaging_qty)} pkg)
                          </span>
                        ) : null}
                      </div>
                    </div>

                    {/* Steppers & Inputs Grid */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
                      {/* Counted Quantity Stepper */}
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1.5">
                          Counted DMT Pieces <span className="text-destructive">*</span>
                        </label>
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={isConfirmed || count <= 0}
                            onClick={() => {
                              updateLine(container.container_id, 'counted_qty', count - 1);
                            }}
                            className="w-12 h-11 flex items-center justify-center rounded-lg bg-muted border border-input text-foreground hover:bg-accent disabled:opacity-40 transition-colors"
                            aria-label={`Decrease count for ${container.container_code}`}
                          >
                            <Minus className="w-4 h-4" />
                          </button>
                          <input
                            type="number"
                            min="0"
                            disabled={isConfirmed}
                            value={count}
                            onChange={(e) => {
                              updateLine(container.container_id, 'counted_qty', e.target.value);
                            }}
                            className="flex-1 h-11 text-center bg-background border border-input rounded-lg font-bold text-lg text-foreground focus:ring-2 focus:ring-primary/50"
                          />
                          <button
                            type="button"
                            disabled={isConfirmed}
                            onClick={() => {
                              updateLine(container.container_id, 'counted_qty', count + 1);
                            }}
                            className="w-12 h-11 flex items-center justify-center rounded-lg bg-muted border border-input text-foreground hover:bg-accent disabled:opacity-40 transition-colors"
                            aria-label={`Increase count for ${container.container_code}`}
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {/* Sellable Packaging Stepper */}
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1.5">
                          Sellable Packaging Separated (qty)
                        </label>
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={isConfirmed || packaging <= 0}
                            onClick={() => {
                              updateLine(
                                container.container_id,
                                'sellable_packaging_qty',
                                packaging - 1,
                              );
                            }}
                            className="w-12 h-11 flex items-center justify-center rounded-lg bg-muted border border-input text-foreground hover:bg-accent disabled:opacity-40 transition-colors"
                            aria-label={`Decrease sellable packaging for ${container.container_code}`}
                          >
                            <Minus className="w-4 h-4" />
                          </button>
                          <input
                            type="number"
                            min="0"
                            disabled={isConfirmed}
                            value={packaging}
                            onChange={(e) => {
                              updateLine(
                                container.container_id,
                                'sellable_packaging_qty',
                                e.target.value,
                              );
                            }}
                            className="flex-1 h-11 text-center bg-background border border-input rounded-lg font-bold text-lg text-foreground focus:ring-2 focus:ring-primary/50"
                          />
                          <button
                            type="button"
                            disabled={isConfirmed}
                            onClick={() => {
                              updateLine(
                                container.container_id,
                                'sellable_packaging_qty',
                                packaging + 1,
                              );
                            }}
                            className="w-12 h-11 flex items-center justify-center rounded-lg bg-muted border border-input text-foreground hover:bg-accent disabled:opacity-40 transition-colors"
                            aria-label={`Increase sellable packaging for ${container.container_code}`}
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Line Remarks */}
                    <div className="mt-3">
                      <input
                        type="text"
                        placeholder="Remarks for this bin (optional)..."
                        disabled={isConfirmed}
                        value={remarks}
                        onChange={(e) => {
                          updateLine(container.container_id, 'remarks', e.target.value);
                        }}
                        className="w-full text-xs px-3 py-1.5 bg-background border border-input rounded-md text-foreground placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Past Date Late Reason Requirement */}
          {isPastDate && !isConfirmed && (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 space-y-2">
              <label className="block text-xs font-bold text-amber-400 uppercase tracking-wide">
                Late Entry Reason <span className="text-destructive">*</span>
              </label>
              <textarea
                rows={2}
                placeholder="Specify reason for late audit confirmation (required for past dates)..."
                value={lateReason}
                onChange={(e) => {
                  setLateReason(e.target.value);
                }}
                className="w-full p-2.5 text-sm bg-background border border-amber-500/40 rounded-lg text-foreground focus:ring-2 focus:ring-amber-500"
              />
            </div>
          )}

          {/* General Audit Notes */}
          {!isConfirmed && (
            <div className="bg-card border border-border rounded-xl p-4 space-y-2">
              <label className="block text-xs font-semibold text-muted-foreground uppercase">
                Overall Audit Observations / Notes (optional)
              </label>
              <textarea
                rows={2}
                placeholder="Any discrepancy, damaged bins, or general remarks..."
                value={generalRemarks}
                onChange={(e) => {
                  setGeneralRemarks(e.target.value);
                }}
                className="w-full p-2.5 text-sm bg-background border border-input rounded-lg text-foreground focus:ring-1 focus:ring-primary"
              />
            </div>
          )}

          {/* Sticky Bottom Confirmation Bar */}
          <div className="fixed bottom-0 left-0 right-0 z-30 bg-card/95 backdrop-blur border-t border-border p-4 shadow-lg">
            <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
              {/* Mandatory Confirmation Checkbox */}
              <label className="flex items-center gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  disabled={isConfirmed}
                  checked={isChecked}
                  onChange={(e) => {
                    setConfirmedCheckOverride(e.target.checked);
                  }}
                  className="w-5 h-5 rounded border-input text-primary focus:ring-primary"
                />
                <span className="text-sm font-semibold text-foreground">
                  {data?.checkbox_label ?? 'Containers Checked & Counted Daily'}
                </span>
              </label>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                {!isConfirmed && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={isSubmitting}
                    onClick={() => {
                      void handleSaveCounts();
                    }}
                  >
                    Save Draft Counts
                  </Button>
                )}

                <Button
                  variant="primary"
                  size="sm"
                  disabled={isConfirmed || !isChecked || isSubmitting}
                  onClick={() => {
                    void handleConfirmAudit();
                  }}
                  className="font-semibold"
                >
                  {isSubmitting ? (
                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 mr-1.5" />
                  )}
                  {isConfirmed ? 'Audit Confirmed' : 'Confirm Daily Audit'}
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
