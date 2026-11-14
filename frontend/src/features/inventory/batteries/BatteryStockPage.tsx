import { useCallback, useState } from 'react';
import { Battery, Plus, RefreshCw, CheckCircle, AlertTriangle } from 'lucide-react';
import { Button, Badge, LoadingState, ErrorState, Modal } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { batteryApi } from './api';
import { servicingApi } from '@/features/servicing/api';
import type { BatteryAdjustment, BatteryBalance, BatteryMovement, BatteryType } from './types';
import type { BatteryReconciliation } from '@/features/servicing/types';

function makeApproveKey(id: string): string {
  return `adj-app-${id}-${Date.now().toString()}`;
}

function makeReceiptKey(): string {
  return `rcpt-${Date.now().toString()}-${Math.random().toString(36).slice(2, 7)}`;
}

interface Props {
  canManage: boolean;
  canApprove: boolean;
}

export function BatteryStockPage({ canManage, canApprove }: Props) {
  const [activeTab, setActiveTab] = useState<
    'balances' | 'receipts' | 'adjustments' | 'movements' | 'reconciliation'
  >('balances');

  const [actionError, setActionError] = useState<string | null>(null);

  // Date filters for reconciliation
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');

  // Modals state
  const [showReceiptModal, setShowReceiptModal] = useState(false);
  const [receiptType, setReceiptType] = useState('');
  const [receiptQty, setReceiptQty] = useState(10);
  const [receiptRef, setReceiptRef] = useState('');
  const [receiptNotes, setReceiptNotes] = useState('');

  const [showAdjustmentModal, setShowAdjustmentModal] = useState(false);
  const [adjType, setAdjType] = useState('');
  const [adjQty, setAdjQty] = useState(1);
  const [adjReason, setAdjReason] = useState('');

  const [modalSubmitting, setModalSubmitting] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const fetcher = useCallback(async () => {
    const [bals, btypes, movs, adjs, recon] = await Promise.all([
      batteryApi.getBalances(),
      batteryApi.getTypes(),
      batteryApi.getMovements(),
      batteryApi.listAdjustments(),
      servicingApi.getBatteryReconciliation(
        fromDate || toDate ? { from: fromDate || undefined, to: toDate || undefined } : undefined,
      ),
    ]);
    return { bals, btypes, movs, adjs, recon };
  }, [fromDate, toDate]);

  const { data, loading, error: queryError, reload } = useApiQuery(fetcher);

  const balances: BatteryBalance[] = data?.bals ?? [];
  const types: BatteryType[] = data?.btypes ?? [];
  const movements: BatteryMovement[] = data?.movs ?? [];
  const adjustments: BatteryAdjustment[] = data?.adjs ?? [];
  const reconciliation: BatteryReconciliation | null = data?.recon ?? null;
  const error = queryError?.message ?? actionError;

  const handleCreateReceipt = async (e: React.FormEvent) => {
    e.preventDefault();
    const effectiveType = receiptType || types[0]?.code;
    if (!effectiveType || receiptQty <= 0 || !receiptRef.trim()) {
      setModalError('Please fill in battery type, quantity (>0), and reference');
      return;
    }
    try {
      setModalSubmitting(true);
      setModalError(null);
      const key = makeReceiptKey();
      await batteryApi.receiveBatteries(
        {
          battery_type: effectiveType,
          qty: receiptQty,
          ref: receiptRef.trim(),
          notes: receiptNotes.trim() || undefined,
        },
        key,
      );
      setShowReceiptModal(false);
      setReceiptRef('');
      setReceiptNotes('');
      reload();
    } catch (err: unknown) {
      setModalError(err instanceof Error ? err.message : 'Failed to receive batteries');
    } finally {
      setModalSubmitting(false);
    }
  };

  const handleCreateAdjustment = async (e: React.FormEvent) => {
    e.preventDefault();
    const effectiveType = adjType || types[0]?.code;
    if (!effectiveType || adjQty === 0 || !adjReason.trim()) {
      setModalError('Please fill in battery type, non-zero quantity, and mandatory reason');
      return;
    }
    try {
      setModalSubmitting(true);
      setModalError(null);
      await batteryApi.requestAdjustment({
        battery_type: effectiveType,
        qty: adjQty,
        reason: adjReason.trim(),
      });
      setShowAdjustmentModal(false);
      setAdjReason('');
      reload();
    } catch (err: unknown) {
      setModalError(err instanceof Error ? err.message : 'Failed to request adjustment');
    } finally {
      setModalSubmitting(false);
    }
  };

  const handleApproveAdjustment = async (id: string) => {
    try {
      const key = makeApproveKey(id);
      await batteryApi.approveAdjustment(id, 'Approved via Battery Stock portal', key);
      reload();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to approve adjustment');
    }
  };

  const handleRejectAdjustment = async (id: string) => {
    const reason = window.prompt('Enter rejection reason:');
    if (!reason || !reason.trim()) return;
    try {
      await batteryApi.rejectAdjustment(id, reason.trim());
      reload();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to reject adjustment');
    }
  };

  return (
    <div
      style={{
        maxWidth: '1200px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
          backgroundColor: '#fff',
          padding: '1.25rem',
          borderRadius: '8px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#0f172a' }}>
            Battery Stock & Ledger
          </h1>
          <p style={{ margin: '0.25rem 0 0', color: '#64748b', fontSize: '0.875rem' }}>
            Battery stock in BATTERY_STORE location, consumption tracking, and reconciliation
            (BR-24, G-10)
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <Button
            type="button"
            variant="secondary"
            onClick={reload}
            style={{
              minHeight: '44px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <RefreshCw size={16} />
            Refresh
          </Button>

          {canManage && (
            <>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowAdjustmentModal(true);
                }}
                style={{ minHeight: '44px', fontWeight: 600 }}
              >
                Request Adjustment
              </Button>

              <Button
                type="button"
                variant="primary"
                onClick={() => {
                  setShowReceiptModal(true);
                }}
                style={{
                  minHeight: '44px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontWeight: 600,
                }}
              >
                <Plus size={18} />
                Receive Batteries
              </Button>
            </>
          )}
        </div>
      </div>

      {error && <ErrorState error={{ message: error }} />}

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          borderBottom: '1px solid #e2e8f0',
          paddingBottom: '0.5rem',
          overflowX: 'auto',
        }}
      >
        {(
          [
            { id: 'balances', label: 'Balances' },
            { id: 'reconciliation', label: 'Reconciliation Report' },
            { id: 'movements', label: 'Consumption Ledger' },
            { id: 'adjustments', label: 'Adjustments' },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setActiveTab(tab.id);
            }}
            style={{
              minHeight: '44px',
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              fontWeight: activeTab === tab.id ? 700 : 500,
              backgroundColor: activeTab === tab.id ? '#2563eb' : 'transparent',
              color: activeTab === tab.id ? '#fff' : '#64748b',
              whiteSpace: 'nowrap',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingState />
      ) : (
        <>
          {/* TAB 1: BALANCES */}
          {activeTab === 'balances' && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: '1rem',
              }}
            >
              {balances.map((b) => (
                <div
                  key={b.battery_type_id}
                  style={{
                    backgroundColor: '#fff',
                    borderRadius: '8px',
                    padding: '1.25rem',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                    border: '1px solid #e2e8f0',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.75rem',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Battery size={22} color="#2563eb" />
                      <span style={{ fontSize: '1.125rem', fontWeight: 700, color: '#0f172a' }}>
                        {b.code}
                      </span>
                    </div>
                    <Badge variant={b.balance > 0 ? 'success' : 'danger'}>
                      {b.balance > 0 ? 'In Stock' : 'Out of Stock'}
                    </Badge>
                  </div>

                  <div style={{ fontSize: '0.8125rem', color: '#64748b' }}>{b.name}</div>

                  <div style={{ borderTop: '1px solid #f1f5f9', paddingTop: '0.75rem' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                      CURRENT BALANCE
                    </div>
                    <div
                      style={{
                        fontSize: '2rem',
                        fontWeight: 800,
                        color: b.balance > 0 ? '#0f172a' : '#ef4444',
                      }}
                    >
                      {b.balance} pcs
                    </div>
                  </div>

                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr 1fr',
                      gap: '0.5rem',
                      fontSize: '0.75rem',
                      color: '#64748b',
                      backgroundColor: '#f8fafc',
                      padding: '0.5rem',
                      borderRadius: '4px',
                    }}
                  >
                    <div>
                      <div>Received</div>
                      <strong style={{ color: '#0f172a' }}>{b.total_received}</strong>
                    </div>
                    <div>
                      <div>Consumed</div>
                      <strong style={{ color: '#0f172a' }}>{b.total_consumed}</strong>
                    </div>
                    <div>
                      <div>Adjusted</div>
                      <strong style={{ color: '#0f172a' }}>{b.total_adjusted}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* TAB 2: RECONCILIATION REPORT (WF r8) */}
          {activeTab === 'reconciliation' && reconciliation && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Date Filters & Tie-Out Banner */}
              <div
                style={{
                  backgroundColor: '#fff',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '1rem',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <div>
                    <label
                      style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: '#64748b',
                      }}
                    >
                      From Date:
                    </label>
                    <input
                      type="date"
                      value={fromDate}
                      onChange={(e) => {
                        setFromDate(e.target.value);
                      }}
                      style={{
                        minHeight: '38px',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #cbd5e1',
                      }}
                    />
                  </div>

                  <div>
                    <label
                      style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: '#64748b',
                      }}
                    >
                      To Date:
                    </label>
                    <input
                      type="date"
                      value={toDate}
                      onChange={(e) => {
                        setToDate(e.target.value);
                      }}
                      style={{
                        minHeight: '38px',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #cbd5e1',
                      }}
                    />
                  </div>
                </div>

                <div
                  style={{
                    padding: '0.5rem 1rem',
                    borderRadius: '20px',
                    fontWeight: 700,
                    fontSize: '0.9375rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    backgroundColor: reconciliation.ties_out ? '#dcfce7' : '#fee2e2',
                    color: reconciliation.ties_out ? '#15803d' : '#b91c1c',
                  }}
                >
                  {reconciliation.ties_out ? (
                    <>
                      <CheckCircle size={18} />
                      Report Ties Out Perfectly (Discrepancy: 0)
                    </>
                  ) : (
                    <>
                      <AlertTriangle size={18} />
                      Discrepancy Detected: {reconciliation.discrepancy} pcs
                    </>
                  )}
                </div>
              </div>

              {/* Summary KPIs */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                  gap: '1rem',
                }}
              >
                <div
                  style={{
                    backgroundColor: '#fff',
                    padding: '1rem',
                    borderRadius: '8px',
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                    PIECES CHECKED
                  </div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0f172a' }}>
                    {reconciliation.pieces_checked} pcs
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: '#fff',
                    padding: '1rem',
                    borderRadius: '8px',
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                    PIECES BATTERY REPLACED
                  </div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#2563eb' }}>
                    {reconciliation.pieces_with_battery_replaced} pcs
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: '#fff',
                    padding: '1rem',
                    borderRadius: '8px',
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                    BATTERIES INSTALLED
                  </div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0f172a' }}>
                    {reconciliation.batteries_installed} pcs
                  </div>
                </div>

                <div
                  style={{
                    backgroundColor: '#fff',
                    padding: '1rem',
                    borderRadius: '8px',
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                    LEDGER DEDUCTIONS
                  </div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#16a34a' }}>
                    {reconciliation.battery_stock_movements} pcs
                  </div>
                </div>
              </div>

              {/* By Type Breakdown Table */}
              <div
                style={{
                  backgroundColor: '#fff',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                }}
              >
                <h3
                  style={{
                    margin: '0 0 1rem',
                    fontSize: '1rem',
                    fontWeight: 700,
                    color: '#0f172a',
                  }}
                >
                  Reconciliation By Battery Type
                </h3>

                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    textAlign: 'left',
                    fontSize: '0.875rem',
                  }}
                >
                  <thead>
                    <tr style={{ borderBottom: '2px solid #e2e8f0', color: '#64748b' }}>
                      <th style={{ padding: '0.75rem' }}>Battery Type</th>
                      <th style={{ padding: '0.75rem' }}>Installed (Receiving Records)</th>
                      <th style={{ padding: '0.75rem' }}>Consumed (Ledger Movements)</th>
                      <th style={{ padding: '0.75rem' }}>Discrepancy</th>
                      <th style={{ padding: '0.75rem' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconciliation.by_battery_type.map((row) => (
                      <tr key={row.battery_type_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '0.75rem', fontWeight: 600, color: '#0f172a' }}>
                          {row.battery_type_code} ({row.battery_type_name})
                        </td>
                        <td style={{ padding: '0.75rem' }}>{row.batteries_installed}</td>
                        <td style={{ padding: '0.75rem' }}>{row.battery_stock_movements}</td>
                        <td
                          style={{
                            padding: '0.75rem',
                            fontWeight: 600,
                            color: row.discrepancy === 0 ? '#16a34a' : '#dc2626',
                          }}
                        >
                          {row.discrepancy}
                        </td>
                        <td style={{ padding: '0.75rem' }}>
                          <Badge variant={row.ties_out ? 'success' : 'danger'}>
                            {row.ties_out ? 'Ties Out' : 'Mismatch'}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: CONSUMPTION LEDGER */}
          {activeTab === 'movements' && (
            <div
              style={{
                backgroundColor: '#fff',
                borderRadius: '8px',
                padding: '1.25rem',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              }}
            >
              <h3
                style={{ margin: '0 0 1rem', fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}
              >
                Battery Stock Movements Ledger
              </h3>
              {movements.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                  No battery movements recorded yet.
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      textAlign: 'left',
                      fontSize: '0.875rem',
                    }}
                  >
                    <thead>
                      <tr style={{ borderBottom: '2px solid #e2e8f0', color: '#64748b' }}>
                        <th style={{ padding: '0.75rem' }}>Date & Time</th>
                        <th style={{ padding: '0.75rem' }}>Type</th>
                        <th style={{ padding: '0.75rem' }}>Movement</th>
                        <th style={{ padding: '0.75rem' }}>Qty</th>
                        <th style={{ padding: '0.75rem' }}>From Location</th>
                        <th style={{ padding: '0.75rem' }}>Reference</th>
                      </tr>
                    </thead>
                    <tbody>
                      {movements.map((m) => (
                        <tr key={m.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '0.75rem', color: '#64748b' }}>
                            {new Date(m.created_at).toLocaleString()}
                          </td>
                          <td style={{ padding: '0.75rem', fontWeight: 600 }}>
                            {m.battery_type_code}
                          </td>
                          <td style={{ padding: '0.75rem' }}>
                            <Badge variant={m.movement_type === 'CONSUME' ? 'warning' : 'info'}>
                              {m.movement_type}
                            </Badge>
                          </td>
                          <td style={{ padding: '0.75rem', fontWeight: 700 }}>{m.qty} pcs</td>
                          <td style={{ padding: '0.75rem' }}>{m.from_location || '-'}</td>
                          <td style={{ padding: '0.75rem', color: '#64748b' }}>
                            {m.reference_type || '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: ADJUSTMENTS */}
          {activeTab === 'adjustments' && (
            <div
              style={{
                backgroundColor: '#fff',
                borderRadius: '8px',
                padding: '1.25rem',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
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
                <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>
                  Battery Adjustments & Approvals
                </h3>
                {canManage && (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setShowAdjustmentModal(true);
                    }}
                    style={{ minHeight: '38px' }}
                  >
                    + Request Adjustment
                  </Button>
                )}
              </div>

              {adjustments.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                  No adjustments requested yet.
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      textAlign: 'left',
                      fontSize: '0.875rem',
                    }}
                  >
                    <thead>
                      <tr style={{ borderBottom: '2px solid #e2e8f0', color: '#64748b' }}>
                        <th style={{ padding: '0.75rem' }}>Requested At</th>
                        <th style={{ padding: '0.75rem' }}>Type</th>
                        <th style={{ padding: '0.75rem' }}>Qty</th>
                        <th style={{ padding: '0.75rem' }}>Reason</th>
                        <th style={{ padding: '0.75rem' }}>Requested By</th>
                        <th style={{ padding: '0.75rem' }}>Status</th>
                        {canApprove && <th style={{ padding: '0.75rem' }}>Action</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {adjustments.map((adj) => (
                        <tr key={adj.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '0.75rem', color: '#64748b' }}>
                            {new Date(adj.requested_at).toLocaleDateString()}
                          </td>
                          <td style={{ padding: '0.75rem', fontWeight: 600 }}>
                            {adj.battery_type_code}
                          </td>
                          <td
                            style={{
                              padding: '0.75rem',
                              fontWeight: 700,
                              color: adj.qty > 0 ? '#16a34a' : '#dc2626',
                            }}
                          >
                            {adj.qty > 0 ? `+${String(adj.qty)}` : adj.qty}
                          </td>
                          <td style={{ padding: '0.75rem' }}>{adj.reason}</td>
                          <td style={{ padding: '0.75rem' }}>{adj.requested_by_name}</td>
                          <td style={{ padding: '0.75rem' }}>
                            <Badge
                              variant={
                                adj.status === 'APPROVED'
                                  ? 'success'
                                  : adj.status === 'REJECTED'
                                    ? 'danger'
                                    : 'warning'
                              }
                            >
                              {adj.status}
                            </Badge>
                          </td>
                          {canApprove && (
                            <td style={{ padding: '0.75rem' }}>
                              {adj.status === 'PENDING' && (
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                  <Button
                                    type="button"
                                    variant="primary"
                                    onClick={() => {
                                      void handleApproveAdjustment(adj.id);
                                    }}
                                    style={{
                                      minHeight: '36px',
                                      padding: '0.25rem 0.625rem',
                                      fontSize: '0.8125rem',
                                    }}
                                  >
                                    Approve
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="secondary"
                                    onClick={() => {
                                      void handleRejectAdjustment(adj.id);
                                    }}
                                    style={{
                                      minHeight: '36px',
                                      padding: '0.25rem 0.625rem',
                                      fontSize: '0.8125rem',
                                    }}
                                  >
                                    Reject
                                  </Button>
                                </div>
                              )}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Modal: Receive Batteries */}
      {showReceiptModal && (
        <Modal
          title="Receive Batteries into Store"
          isOpen={showReceiptModal}
          onClose={() => {
            setShowReceiptModal(false);
          }}
        >
          <form
            onSubmit={(e) => {
              void handleCreateReceipt(e);
            }}
            style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}
          >
            {modalError && <ErrorState error={{ message: modalError }} />}

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Battery Type
              </label>
              <select
                value={receiptType}
                onChange={(e) => {
                  setReceiptType(e.target.value);
                }}
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              >
                {types.map((t) => (
                  <option key={t.id} value={t.code}>
                    {t.code} - {t.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Quantity Received
              </label>
              <input
                type="number"
                min={1}
                value={receiptQty}
                onChange={(e) => {
                  setReceiptQty(parseInt(e.target.value) || 0);
                }}
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Supplier / PO Reference
              </label>
              <input
                type="text"
                value={receiptRef}
                onChange={(e) => {
                  setReceiptRef(e.target.value);
                }}
                placeholder="e.g. PO-88219 / Supplier Ref"
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Notes (Optional)
              </label>
              <input
                type="text"
                value={receiptNotes}
                onChange={(e) => {
                  setReceiptNotes(e.target.value);
                }}
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
              />
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.75rem',
                marginTop: '1rem',
              }}
            >
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowReceiptModal(false);
                }}
                disabled={modalSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={modalSubmitting}
                style={{ minHeight: '44px' }}
              >
                {modalSubmitting ? 'Receiving...' : 'Confirm Receipt'}
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: Request Adjustment */}
      {showAdjustmentModal && (
        <Modal
          title="Request Battery Adjustment"
          isOpen={showAdjustmentModal}
          onClose={() => {
            setShowAdjustmentModal(false);
          }}
        >
          <form
            onSubmit={(e) => {
              void handleCreateAdjustment(e);
            }}
            style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}
          >
            {modalError && <ErrorState error={{ message: modalError }} />}

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Battery Type
              </label>
              <select
                value={adjType}
                onChange={(e) => {
                  setAdjType(e.target.value);
                }}
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              >
                {types.map((t) => (
                  <option key={t.id} value={t.code}>
                    {t.code} - {t.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Adjustment Quantity (+ for found stock, - for write-off/damage)
              </label>
              <input
                type="number"
                value={adjQty}
                onChange={(e) => {
                  setAdjQty(parseInt(e.target.value) || 0);
                }}
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              />
            </div>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.25rem',
                }}
              >
                Mandatory Reason (Audited)
              </label>
              <input
                type="text"
                value={adjReason}
                onChange={(e) => {
                  setAdjReason(e.target.value);
                }}
                placeholder="e.g. Physical inventory count correction, expired cells discarded"
                style={{
                  width: '100%',
                  minHeight: '44px',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                }}
                required
              />
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.75rem',
                marginTop: '1rem',
              }}
            >
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShowAdjustmentModal(false);
                }}
                disabled={modalSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={modalSubmitting}
                style={{ minHeight: '44px' }}
              >
                {modalSubmitting ? 'Requesting...' : 'Submit Request'}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
