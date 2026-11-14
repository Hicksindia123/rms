import { useCallback, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  History,
  Lock,
  Minus,
  Plus,
  Printer,
  Unlock,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError } from '@/lib/api/client';

import { rmActionsApi } from './api';
import type { RmActionsResponse } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenSlip: (gsId: string) => void;
}

export function RmSegregationPage({ gsId, onBack, onOpenSlip }: Props) {
  const fetcher = useCallback(() => rmActionsApi.getActions(gsId), [gsId]);
  const { data, loading, error: queryError, reload } = useApiQuery<RmActionsResponse>(fetcher);

  // Form state: user modifications keyed by `${line.gs_item_id}:${action_code}`
  const [allocations, setAllocations] = useState<Record<string, number>>({});
  const [overrideUnlocked, setOverrideUnlocked] = useState<Record<string, boolean>>({});
  const [overrideReason, setOverrideReason] = useState('');
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [activeOverrideItemId, setActiveOverrideItemId] = useState<string | null>(null);
  const [revisionReason, setRevisionReason] = useState('');
  const [pendencyReasons, setPendencyReasons] = useState<Record<string, string>>({});
  const [historyOpen, setHistoryOpen] = useState(false);

  const [saving, setSaving] = useState(false);
  const [finalising, setFinalising] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const getAllocation = useCallback(
    (itemId: string, actionCode: string) => {
      const key = `${itemId}:${actionCode}`;
      if (allocations[key] !== undefined) {
        return allocations[key];
      }
      if (!data) return 0;
      const line = data.lines.find((l) => l.gs_item_id === itemId);
      const current = line?.current_actions.find((ca) => ca.action_code === actionCode);
      return current ? current.qty : 0;
    },
    [data, allocations],
  );

  const updateQty = (itemId: string, actionCode: string, delta: number) => {
    const key = `${itemId}:${actionCode}`;
    const cur = getAllocation(itemId, actionCode);
    const next = Math.max(0, cur + delta);
    setAllocations((prev) => ({ ...prev, [key]: next }));
  };

  const getLineTotal = useCallback(
    (itemId: string) => {
      if (!data) return 0;
      return data.options.reduce((sum, opt) => sum + getAllocation(itemId, opt.code), 0);
    },
    [data, getAllocation],
  );

  const allLinesReconciled = useMemo(() => {
    if (!data) return false;
    return data.lines.every((line) => getLineTotal(line.gs_item_id) === line.received_qty);
  }, [data, getLineTotal]);

  const handleSave = async (isFinalise = false) => {
    if (!data) return;
    setSaveError(null);
    setActionSuccess(null);

    // Build payload
    const linesPayload = data.lines.map((line) => {
      const lineActions = data.options.map((opt) => ({
        action_code: opt.code,
        qty: getAllocation(line.gs_item_id, opt.code),
      }));
      return {
        gs_item_id: line.gs_item_id,
        actions: lineActions,
      };
    });

    const pendDetails: Record<string, { reason: string; sent_to: string }> = {};
    for (const line of data.lines) {
      const pQty = getAllocation(line.gs_item_id, 'PENDING_BP');
      if (pQty > 0) {
        pendDetails[line.gs_item_id] = {
          reason: pendencyReasons[line.gs_item_id] || 'Sent to Repair Team for checking',
          sent_to: 'Repair Team',
        };
      }
    }

    try {
      if (isFinalise) {
        setFinalising(true);
        // Save first
        await rmActionsApi.saveActions(gsId, {
          lines: linesPayload,
          reason: revisionReason || undefined,
          override_reason: overrideReason || undefined,
          pendency_details: pendDetails,
        });
        await rmActionsApi.finaliseActions(gsId);
        reload();
        setActionSuccess('RM Actions finalised! GS advanced to Handover.');
      } else {
        setSaving(true);
        const res = await rmActionsApi.saveActions(gsId, {
          lines: linesPayload,
          reason: revisionReason || undefined,
          override_reason: overrideReason || undefined,
          pendency_details: pendDetails,
        });
        reload();
        setActionSuccess(`Saved revision ${String(res.current_revision_no)}!`);
      }
    } catch (err) {
      setSaveError(toApiError(err).message);
    } finally {
      setSaving(false);
      setFinalising(false);
    }
  };

  if (loading && !data) {
    return <LoadingState label="Loading RM segregation details…" />;
  }

  if (queryError && !data) {
    return <ErrorState title="Failed to load RM actions" error={queryError} onRetry={reload} />;
  }

  if (!data) return null;

  return (
    <div className="page" style={{ paddingBottom: '9rem' }}>
      {/* Header bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Button type="button" variant="ghost" onClick={onBack}>
            <ArrowLeft size={16} aria-hidden="true" /> Back
          </Button>
          <div>
            <h1 className="page__title" style={{ margin: 0 }}>
              RM Item Segregation
            </h1>
            <p className="page__subtitle" style={{ margin: 0 }}>
              Step-3 a) Replacement Manager action allocation & segregation
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <Badge variant="neutral">GS: {data.gs_no}</Badge>
          <Badge variant="info">Revision #{String(data.current_revision_no)}</Badge>
          {data.has_open_pendency && (
            <Badge variant="warning">
              <Clock size={12} style={{ marginRight: '0.25rem', verticalAlign: 'middle' }} />
              Pending (BP) Held
            </Badge>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setHistoryOpen(true);
            }}
          >
            <History size={14} style={{ marginRight: '0.25rem' }} /> History (
            {String(data.revision_history.length)})
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              onOpenSlip(data.gs_id);
            }}
          >
            <Printer size={14} style={{ marginRight: '0.25rem' }} /> Print Replacement Slip
          </Button>
        </div>
      </div>

      {/* Post-handover reason alert */}
      {data.requires_reason_for_revision && (
        <div
          style={{
            padding: '1rem',
            backgroundColor: '#eff6ff',
            border: '1px solid #bfdbfe',
            borderRadius: '8px',
            marginBottom: '1.25rem',
          }}
        >
          <div
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}
          >
            <AlertTriangle size={18} color="#2563eb" />
            <strong style={{ color: '#1e40af' }}>
              Post-Handover Revision (Technical Return / Discrepancy)
            </strong>
          </div>
          <p style={{ margin: 0, fontSize: '0.875rem', color: '#1e3a8a', marginBottom: '0.5rem' }}>
            Handover to store has occurred. Revising actions now requires a mandatory reason and
            will notify Accounts and Store teams if CN or replacement piece counts change.
          </p>
          <input
            type="text"
            placeholder="Reason for revision (mandatory post-handover)..."
            value={revisionReason}
            onChange={(e) => {
              setRevisionReason(e.target.value);
            }}
            style={{
              width: '100%',
              padding: '0.5rem 0.75rem',
              borderRadius: '6px',
              border: '1px solid #93c5fd',
              fontSize: '0.875rem',
            }}
          />
        </div>
      )}

      {/* Success & Error alerts */}
      {actionSuccess && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.75rem 1rem',
            backgroundColor: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: '6px',
            color: '#166534',
            marginBottom: '1rem',
          }}
        >
          <CheckCircle2 size={16} />
          <span>{actionSuccess}</span>
        </div>
      )}

      {saveError && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.75rem 1rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            color: '#991b1b',
            marginBottom: '1rem',
          }}
        >
          <AlertTriangle size={16} />
          <span>{saveError}</span>
        </div>
      )}

      {/* Main Segregation Cards per Item */}
      <div style={{ display: 'grid', gap: '1.5rem' }}>
        {data.lines.map((line) => {
          const lineTotal = getLineTotal(line.gs_item_id);
          const isReconciled = lineTotal === line.received_qty;
          const isUnlocked = overrideUnlocked[line.gs_item_id] ?? false;
          const notAllowedLocked = line.not_allowed_qty > 0 && !isUnlocked;
          const pendingVal = getAllocation(line.gs_item_id, 'PENDING_BP');

          return (
            <div
              key={line.gs_item_id}
              data-testid="rm-line"
              data-line-no={line.line_no}
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '1.25rem',
                boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              }}
            >
              {/* Line Header */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  flexWrap: 'wrap',
                  gap: '0.75rem',
                  borderBottom: '1px solid #f1f5f9',
                  paddingBottom: '0.75rem',
                  marginBottom: '1rem',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        backgroundColor: '#f1f5f9',
                        padding: '0.15rem 0.4rem',
                        borderRadius: '4px',
                      }}
                    >
                      Line #{String(line.line_no)}
                    </span>
                    <strong style={{ fontSize: '1rem', color: '#0f172a' }}>
                      {line.product_name}
                    </strong>
                    <span style={{ fontSize: '0.8125rem', color: '#64748b' }}>
                      ({line.product_code})
                    </span>
                  </div>
                  <div style={{ fontSize: '0.8125rem', color: '#475569', marginTop: '0.25rem' }}>
                    Received Qty: <strong>{line.received_qty}</strong> &bull; Allowed Qty:{' '}
                    <strong>{line.allowed_qty}</strong> &bull; Rejected Qty:{' '}
                    <strong style={{ color: line.not_allowed_qty > 0 ? '#b91c1c' : '#475569' }}>
                      {line.not_allowed_qty}
                    </strong>
                  </div>
                </div>

                {/* Inspection Rejection Banner & DEC-33 Override */}
                {line.not_allowed_qty > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      backgroundColor: isUnlocked ? '#f0fdf4' : '#fffbeb',
                      border: `1px solid ${isUnlocked ? '#bbf7d0' : '#fde68a'}`,
                      borderRadius: '6px',
                      padding: '0.4rem 0.75rem',
                      fontSize: '0.8125rem',
                    }}
                  >
                    {isUnlocked ? (
                      <>
                        <Unlock size={14} color="#16a34a" />
                        <span style={{ color: '#166534', fontWeight: 600 }}>
                          DEC-33 RM Override Active
                        </span>
                      </>
                    ) : (
                      <>
                        <Lock size={14} color="#d97706" />
                        <span style={{ color: '#b45309' }}>
                          Locked: {line.not_allowed_qty} rejected at inspection
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          style={{ color: '#2563eb', padding: '0.2rem 0.4rem', height: 'auto' }}
                          onClick={() => {
                            setActiveOverrideItemId(line.gs_item_id);
                            setShowOverrideModal(true);
                          }}
                        >
                          Unlock with RM Override
                        </Button>
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* Inspection breakdown details */}
              <div
                style={{
                  display: 'flex',
                  gap: '0.5rem',
                  flexWrap: 'wrap',
                  marginBottom: '1rem',
                  fontSize: '0.75rem',
                  color: '#64748b',
                }}
              >
                <span>Inspection allocations:</span>
                {line.allocations.map((alloc) => (
                  <span
                    key={alloc.condition_code}
                    style={{
                      backgroundColor: '#f8fafc',
                      border: '1px solid #e2e8f0',
                      padding: '0.15rem 0.4rem',
                      borderRadius: '4px',
                    }}
                  >
                    {alloc.condition_label || alloc.condition_code}: <strong>{alloc.qty}</strong>
                  </span>
                ))}
              </div>

              {/* Action Steppers Grid (Mobile-first, 56px touch targets) */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                  gap: '1rem',
                  marginBottom: '1rem',
                }}
              >
                {data.options.map((opt) => {
                  const val = getAllocation(line.gs_item_id, opt.code);
                  const isNotAllowedOpt = opt.code === 'NOT_ALLOWED';
                  const isLockedField = isNotAllowedOpt && notAllowedLocked;

                  return (
                    <div
                      key={opt.code}
                      style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '6px',
                        padding: '0.75rem',
                        backgroundColor: isLockedField ? '#f8fafc' : '#ffffff',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: '0.5rem',
                        }}
                      >
                        <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>{opt.label}</span>
                        {isLockedField && (
                          <span title="Locked from inspection rejection count">
                            <Lock size={12} color="#94a3b8" />
                          </span>
                        )}
                      </div>

                      {/* 56px Stepper */}
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '0.5rem',
                        }}
                      >
                        <button
                          type="button"
                          disabled={isLockedField || val <= 0}
                          onClick={() => {
                            updateQty(line.gs_item_id, opt.code, -1);
                          }}
                          aria-label={`Decrease ${opt.label}`}
                          style={{
                            minWidth: '56px',
                            minHeight: '48px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            backgroundColor: '#f1f5f9',
                            border: '1px solid #cbd5e1',
                            borderRadius: '6px',
                            cursor: isLockedField || val <= 0 ? 'not-allowed' : 'pointer',
                            opacity: isLockedField || val <= 0 ? 0.4 : 1,
                          }}
                        >
                          <Minus size={18} />
                        </button>

                        <div
                          style={{
                            fontWeight: 700,
                            fontSize: '1.25rem',
                            minWidth: '40px',
                            textAlign: 'center',
                          }}
                        >
                          {val}
                        </div>

                        <button
                          type="button"
                          disabled={isLockedField || lineTotal >= line.received_qty}
                          onClick={() => {
                            updateQty(line.gs_item_id, opt.code, 1);
                          }}
                          aria-label={`Increase ${opt.label}`}
                          style={{
                            minWidth: '56px',
                            minHeight: '48px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            backgroundColor: '#f1f5f9',
                            border: '1px solid #cbd5e1',
                            borderRadius: '6px',
                            cursor:
                              isLockedField || lineTotal >= line.received_qty
                                ? 'not-allowed'
                                : 'pointer',
                            opacity: isLockedField || lineTotal >= line.received_qty ? 0.4 : 1,
                          }}
                        >
                          <Plus size={18} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Pending Reason Input if PENDING_BP > 0 */}
              {pendingVal > 0 && (
                <div
                  style={{
                    marginTop: '0.75rem',
                    padding: '0.75rem',
                    backgroundColor: '#faf5ff',
                    border: '1px solid #e9d5ff',
                    borderRadius: '6px',
                  }}
                >
                  <label
                    htmlFor={`pending-reason-${line.gs_item_id}`}
                    style={{
                      display: 'block',
                      fontSize: '0.8125rem',
                      fontWeight: 600,
                      color: '#6b21a8',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Pendency (BP) Reason &mdash; {pendingVal} piece(s) held for technical review:
                  </label>
                  <input
                    id={`pending-reason-${line.gs_item_id}`}
                    type="text"
                    placeholder="e.g. Sent to Repair Team for internal diagnosis..."
                    value={pendencyReasons[line.gs_item_id] || 'Sent to Repair Team for checking'}
                    onChange={(e) => {
                      const val = e.target.value;
                      setPendencyReasons((prev) => ({
                        ...prev,
                        [line.gs_item_id]: val,
                      }));
                    }}
                    style={{
                      width: '100%',
                      padding: '0.4rem 0.6rem',
                      borderRadius: '4px',
                      border: '1px solid #d8b4fe',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>
              )}

              {/* Line Reconciliation Status */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: '0.75rem',
                  paddingTop: '0.5rem',
                  borderTop: '1px solid #f1f5f9',
                  fontSize: '0.8125rem',
                }}
              >
                <span style={{ color: '#64748b' }}>
                  Line total: <strong>{lineTotal}</strong> of <strong>{line.received_qty}</strong>{' '}
                  allocated
                </span>
                {isReconciled ? (
                  <Badge variant="success">
                    <CheckCircle2 size={12} style={{ marginRight: '0.25rem' }} /> Reconciled
                  </Badge>
                ) : lineTotal > line.received_qty ? (
                  <Badge variant="danger">Over-allocated by +{lineTotal - line.received_qty}</Badge>
                ) : (
                  <Badge variant="warning">
                    Under-allocated: {line.received_qty - lineTotal} remaining
                  </Badge>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Override Rejection Modal (DEC-33) */}
      {showOverrideModal && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: '8px',
              padding: '1.5rem',
              maxWidth: '480px',
              width: '100%',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
            }}
          >
            <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '1.125rem', fontWeight: 700 }}>
              Override Inspection Rejections (DEC-33)
            </h2>
            <p style={{ fontSize: '0.875rem', color: '#475569', marginBottom: '1rem' }}>
              Goods rejected by Inward Verification are locked to &quot;Not Allowed&quot;. As
              Replacement Manager, you may unlock and reallocate them to allowed actions (Send New,
              Send Repaired, CN) only by providing a documented commercial goodwill or policy
              override reason.
            </p>
            <label
              htmlFor="rm-override-reason"
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                marginBottom: '0.25rem',
              }}
            >
              RM Override Reason (mandatory)
            </label>
            <textarea
              id="rm-override-reason"
              rows={3}
              placeholder="e.g. Verified commercial goodwill approval from Director; allow CN replacement."
              value={overrideReason}
              onChange={(e) => {
                setOverrideReason(e.target.value);
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '0.875rem',
                marginBottom: '1rem',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setShowOverrideModal(false);
                  setActiveOverrideItemId(null);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                disabled={overrideReason.trim().length < 5}
                onClick={() => {
                  if (activeOverrideItemId) {
                    setOverrideUnlocked((prev) => ({ ...prev, [activeOverrideItemId]: true }));
                  }
                  setShowOverrideModal(false);
                }}
              >
                Confirm & Unlock
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* History Drawer */}
      {historyOpen && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            zIndex: 1000,
            display: 'flex',
            justifyContent: 'flex-end',
          }}
          onClick={() => {
            setHistoryOpen(false);
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '420px',
              backgroundColor: '#fff',
              height: '100%',
              padding: '1.5rem',
              overflowY: 'auto',
              boxShadow: '-4px 0 12px rgba(0,0,0,0.15)',
            }}
            onClick={(e) => {
              e.stopPropagation();
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '1rem',
              }}
            >
              <h2 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 700 }}>Revision History</h2>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setHistoryOpen(false);
                }}
              >
                Close
              </Button>
            </div>
            {data.revision_history.length === 0 ? (
              <p style={{ color: '#64748b' }}>No past revisions saved yet.</p>
            ) : (
              <div style={{ display: 'grid', gap: '1rem' }}>
                {data.revision_history.map((rev) => (
                  <div
                    key={rev.revision_no}
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: '6px',
                      padding: '0.75rem',
                      backgroundColor: '#f8fafc',
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                      Revision #{String(rev.revision_no)}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.2rem' }}>
                      By {rev.decided_by_name} on {new Date(rev.decided_at).toLocaleString()}
                    </div>
                    {rev.reason && (
                      <div
                        style={{
                          fontSize: '0.8125rem',
                          color: '#334155',
                          marginTop: '0.35rem',
                          fontStyle: 'italic',
                        }}
                      >
                        &quot;{rev.reason}&quot;
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Sticky Bottom Action Bar */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          backgroundColor: '#ffffff',
          borderTop: '1px solid #e2e8f0',
          padding: '0.75rem 1rem',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.5rem',
          justifyContent: 'space-between',
          alignItems: 'center',
          boxShadow: '0 -2px 10px rgba(0,0,0,0.06)',
          zIndex: 100,
        }}
      >
        <div>
          {allLinesReconciled ? (
            <Badge variant="success">
              <CheckCircle2 size={14} style={{ marginRight: '0.25rem' }} /> All Lines Fully
              Reconciled
            </Badge>
          ) : (
            <Badge variant="warning">
              <AlertTriangle size={14} style={{ marginRight: '0.25rem' }} /> Line Allocations
              Incomplete
            </Badge>
          )}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
          <Button
            type="button"
            variant="outline"
            disabled={saving || finalising || !allLinesReconciled}
            onClick={() => {
              void handleSave(false);
            }}
          >
            {saving ? 'Saving Revision…' : 'Save Draft Revision'}
          </Button>

          <Button
            type="button"
            variant="primary"
            disabled={saving || finalising || !allLinesReconciled}
            onClick={() => {
              void handleSave(true);
            }}
          >
            {finalising ? 'Finalising…' : 'Finalise & Advance'}
          </Button>
        </div>
      </div>
    </div>
  );
}
