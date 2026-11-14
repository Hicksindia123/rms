import { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft,
  Check,
  Minus,
  Plus,
  AlertTriangle,
  Battery,
  Sparkles,
  CheckCircle,
} from 'lucide-react';
import { Button, LoadingState, ErrorState, Badge } from '@/components/ui';
import { servicingApi } from './api';
import { batteryApi } from '@/features/inventory/batteries/api';
import type { BatchDetail, BatchLine, LineReceivePayload } from './types';
import type { BatteryType } from '@/features/inventory/batteries/types';

interface Props {
  batchId: string;
  onBack: () => void;
  onCompleted: () => void;
}

export function ReceiveBatchPage({ batchId, onBack, onCompleted }: Props) {
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [batteryTypes, setBatteryTypes] = useState<BatteryType[]>([]);
  const [activeLineId, setActiveLineId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Per line form state
  const [qtyReceiving, setQtyReceiving] = useState<number>(0);
  const [batteryCheckCode, setBatteryCheckCode] = useState<string>('');
  const [piecesChecked, setPiecesChecked] = useState<number>(0);
  const [batteriesInstalled, setBatteriesInstalled] = useState<number>(0);
  const [selectedBatteryTypeId, setSelectedBatteryTypeId] = useState<string>('');
  const [cleaningCode, setCleaningCode] = useState<string>('');
  const [evaluationNotes, setEvaluationNotes] = useState<string>('');
  const [technicianRemarks, setTechnicianRemarks] = useState<string>('');

  // Classification allocations
  const [allocFunctionalGood, setAllocFunctionalGood] = useState<number>(0);
  const [allocFunctionalRepaired, setAllocFunctionalRepaired] = useState<number>(0);
  const [allocNonGood, setAllocNonGood] = useState<number>(0);
  const [allocNonSellable, setAllocNonSellable] = useState<number>(0);

  const initLineState = useCallback((line: BatchLine, btypes: BatteryType[] = []) => {
    setActiveLineId(line.id);
    const unreceived = line.qty_allotted - line.qty_received;
    setQtyReceiving(unreceived);

    // Initial allocations default to all functional repaired
    setAllocFunctionalGood(0);
    setAllocFunctionalRepaired(unreceived);
    setAllocNonGood(0);
    setAllocNonSellable(0);

    // Battery defaults
    if (line.supports_battery) {
      setBatteryCheckCode('BATTERY_OK');
      setPiecesChecked(unreceived);
      setBatteriesInstalled(0);
      if (btypes.length > 0 && btypes[0]) {
        setSelectedBatteryTypeId(btypes[0].id);
      }
    } else {
      setBatteryCheckCode('');
      setPiecesChecked(0);
      setBatteriesInstalled(0);
    }

    // Cleaning defaults
    const dirty =
      line.source_condition_code === 'DMT_DIRTY' || line.source_condition_code === 'DMT_SCRATCHED';
    setCleaningCode(dirty ? 'CLEANED_SELLABLE' : '');
    setEvaluationNotes('');
    setTechnicianRemarks('');
  }, []);

  useEffect(() => {
    let cancelled = false;
    const fetchBatch = async () => {
      try {
        const [batchData, btypes] = await Promise.all([
          servicingApi.getBatch(batchId),
          batteryApi.getTypes(),
        ]);
        if (!cancelled) {
          setBatch(batchData);
          const activeTypes = btypes.filter((bt) => bt.is_active);
          setBatteryTypes(activeTypes);
          const pendingLine = batchData.lines.find((ln) => ln.qty_allotted - ln.qty_received > 0);
          if (pendingLine) {
            initLineState(pendingLine, activeTypes);
          }
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load batch');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void fetchBatch();
    return () => {
      cancelled = true;
    };
  }, [batchId, initLineState]);

  if (loading) return <LoadingState />;
  if (error && !batch) return <ErrorState error={{ message: error }} />;
  if (!batch) return null;

  const activeLine = batch.lines.find((ln) => ln.id === activeLineId);
  const unreceived = activeLine ? activeLine.qty_allotted - activeLine.qty_received : 0;
  const isDirtyOrScratched =
    activeLine?.source_condition_code === 'DMT_DIRTY' ||
    activeLine?.source_condition_code === 'DMT_SCRATCHED';

  // Live reconciliation meter
  const totalAllocated =
    allocFunctionalGood + allocFunctionalRepaired + allocNonGood + allocNonSellable;
  const meterMatches = totalAllocated === qtyReceiving && qtyReceiving > 0;

  // DEC-17 handler: If PERMANENT_SCRATCHES selected, force all receiving to NON_SELLABLE
  const handleCleaningChange = (code: string) => {
    setCleaningCode(code);
    if (code === 'PERMANENT_SCRATCHES') {
      setAllocFunctionalGood(0);
      setAllocFunctionalRepaired(0);
      setAllocNonGood(0);
      setAllocNonSellable(qtyReceiving);
    }
  };

  const handleQtyReceivingChange = (newQty: number) => {
    const val = Math.max(1, Math.min(unreceived, newQty));
    setQtyReceiving(val);
    if (batteryCheckCode === 'BATTERY_OK' || batteryCheckCode === 'BATTERY_REPLACED') {
      setPiecesChecked(val);
    }
    if (cleaningCode === 'PERMANENT_SCRATCHES') {
      setAllocFunctionalGood(0);
      setAllocFunctionalRepaired(0);
      setAllocNonGood(0);
      setAllocNonSellable(val);
    } else {
      setAllocFunctionalGood(0);
      setAllocFunctionalRepaired(val);
      setAllocNonGood(0);
      setAllocNonSellable(0);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeLine) return;

    if (!meterMatches) {
      setError(
        `Classification total (${String(totalAllocated)}) must equal receiving quantity (${String(qtyReceiving)})`,
      );
      return;
    }

    // G-10 guard check
    if (activeLine.supports_battery && batteryCheckCode === 'BATTERY_REPLACED') {
      if (!piecesChecked || piecesChecked <= 0 || !batteriesInstalled || batteriesInstalled <= 0) {
        setError('BATTERY_REPLACED requires pieces checked > 0 and batteries installed > 0 (G-10)');
        return;
      }
      if (!selectedBatteryTypeId) {
        setError('Please select the battery type installed');
        return;
      }
    }

    // DEC-16 check
    if (isDirtyOrScratched && !cleaningCode) {
      setError(
        'Cleaning & scratch treatment result is mandatory for dirty/scratched pieces (DEC-16)',
      );
      return;
    }

    try {
      setSubmitting(true);
      setError(null);
      const idempotencyKey = `receive-${batch.id}-${activeLine.id}-${String(Date.now())}`;

      const payload: LineReceivePayload = {
        batch_line_id: activeLine.id,
        qty_receiving: qtyReceiving,
        battery_check_code:
          activeLine.supports_battery && batteryCheckCode ? batteryCheckCode : null,
        pieces_checked: activeLine.supports_battery && batteryCheckCode ? piecesChecked : null,
        batteries_installed:
          activeLine.supports_battery && batteryCheckCode === 'BATTERY_REPLACED'
            ? batteriesInstalled
            : 0,
        battery_type_id:
          activeLine.supports_battery && batteryCheckCode === 'BATTERY_REPLACED'
            ? selectedBatteryTypeId
            : null,
        cleaning_code: cleaningCode || null,
        allocations: {
          FUNCTIONAL_GOOD: allocFunctionalGood,
          FUNCTIONAL_REPAIRED: allocFunctionalRepaired,
          NON_GOOD: allocNonGood,
          NON_SELLABLE: allocNonSellable,
        },
        evaluation_notes: evaluationNotes.trim() || null,
        technician_remarks: technicianRemarks.trim() || null,
      };

      const updated = await servicingApi.receiveBatch(
        batch.id,
        { lines: [payload] },
        idempotencyKey,
      );
      setBatch(updated);

      // Check if more lines are pending
      const nextPending = updated.lines.find((ln) => ln.qty_allotted - ln.qty_received > 0);
      if (nextPending) {
        initLineState(nextPending);
      } else {
        onCompleted();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to record technician receiving');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: '800px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Top Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Button
            type="button"
            variant="secondary"
            onClick={onBack}
            style={{
              minHeight: '44px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <ArrowLeft size={16} />
            Board
          </Button>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>
              Receive Batch: {batch.batch_no}
            </h1>
            <p style={{ margin: '0.125rem 0 0', color: '#64748b', fontSize: '0.8125rem' }}>
              Technician: <strong>{batch.technician_name}</strong> | Coordinator:{' '}
              <strong>{batch.entry_by_name}</strong>
            </p>
          </div>
        </div>

        <Badge variant={batch.status === 'COMPLETED' ? 'success' : 'info'}>{batch.status}</Badge>
      </div>

      {error && <ErrorState error={{ message: error }} />}

      {/* Batch Lines Selector */}
      <div style={{ display: 'flex', gap: '0.5rem', overflowX: 'auto', paddingBottom: '0.25rem' }}>
        {batch.lines.map((ln) => {
          const isSelected = ln.id === activeLineId;
          const isDone = ln.qty_received >= ln.qty_allotted;
          return (
            <button
              key={ln.id}
              type="button"
              onClick={() => {
                initLineState(ln);
              }}
              style={{
                minHeight: '44px',
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                border: isSelected ? '2px solid #2563eb' : '1px solid #cbd5e1',
                backgroundColor: isSelected ? '#eff6ff' : '#fff',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                whiteSpace: 'nowrap',
                fontWeight: isSelected ? 700 : 500,
                color: isSelected ? '#1e40af' : '#334155',
              }}
            >
              {isDone ? <CheckCircle size={16} color="#16a34a" /> : null}
              <span>{ln.product_name}</span>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                ({ln.qty_received}/{ln.qty_allotted})
              </span>
            </button>
          );
        })}
      </div>

      {!activeLine || unreceived <= 0 ? (
        <div
          style={{
            backgroundColor: '#fff',
            borderRadius: '8px',
            padding: '3rem 1.5rem',
            textAlign: 'center',
            boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
          }}
        >
          <CheckCircle size={48} color="#16a34a" style={{ margin: '0 auto 1rem' }} />
          <h2 style={{ margin: '0 0 0.5rem', color: '#0f172a' }}>All lines received!</h2>
          <p style={{ margin: '0 0 1.5rem', color: '#64748b', fontSize: '0.875rem' }}>
            Batch {batch.batch_no} is fully processed and stock movements are completed.
          </p>
          <Button
            type="button"
            variant="primary"
            onClick={onCompleted}
            style={{ minHeight: '44px' }}
          >
            Back to Technician Board
          </Button>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}
        >
          {/* Active Line Card */}
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: '8px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                flexWrap: 'wrap',
                gap: '0.5rem',
              }}
            >
              <div>
                <h2 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 700, color: '#0f172a' }}>
                  {activeLine.product_name} ({activeLine.product_code})
                </h2>
                <div
                  style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.35rem' }}
                >
                  <Badge variant="neutral">Category: {activeLine.category_code}</Badge>
                  {activeLine.source_condition_code && (
                    <Badge variant="warning">Source: {activeLine.source_condition_code}</Badge>
                  )}
                  {activeLine.supports_battery && <Badge variant="info">Supports Battery</Badge>}
                  {activeLine.requires_evaluation && (
                    <Badge variant="danger">Evaluation Required</Badge>
                  )}
                </div>
              </div>

              {/* Receiving Qty Stepper */}
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-end',
                  gap: '0.25rem',
                }}
              >
                <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                  RECEIVING QTY
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      handleQtyReceivingChange(qtyReceiving - 1);
                    }}
                    disabled={qtyReceiving <= 1}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Minus size={18} />
                  </Button>
                  <span
                    style={{
                      fontSize: '1.25rem',
                      fontWeight: 700,
                      minWidth: '44px',
                      textAlign: 'center',
                    }}
                  >
                    {qtyReceiving}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      handleQtyReceivingChange(qtyReceiving + 1);
                    }}
                    disabled={qtyReceiving >= unreceived}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Plus size={18} />
                  </Button>
                </div>
                <div style={{ fontSize: '0.6875rem', color: '#94a3b8' }}>
                  Max unreceived: {unreceived}
                </div>
              </div>
            </div>

            {/* Evaluation note if requires_evaluation */}
            {activeLine.requires_evaluation && (
              <div
                style={{
                  backgroundColor: '#fffbeb',
                  border: '1px solid #fef3c7',
                  borderRadius: '6px',
                  padding: '0.75rem',
                }}
              >
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    color: '#92400e',
                    marginBottom: '0.25rem',
                  }}
                >
                  Evaluation Note (Required for capillary / EO evaluation):
                </label>
                <input
                  type="text"
                  value={evaluationNotes}
                  onChange={(e) => {
                    setEvaluationNotes(e.target.value);
                  }}
                  placeholder="Record evaluation findings"
                  style={{
                    width: '100%',
                    minHeight: '44px',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #fde68a',
                  }}
                />
              </div>
            )}
          </div>

          {/* Conditional Battery Section (DEC-15, G-10) */}
          {activeLine.supports_battery && (
            <div
              style={{
                backgroundColor: '#fff',
                borderRadius: '8px',
                padding: '1.25rem',
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                display: 'flex',
                flexDirection: 'column',
                gap: '1rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Battery size={20} color="#2563eb" />
                <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>
                  Battery Check & Replacement (G-10)
                </h3>
              </div>

              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    minHeight: '44px',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="battery_check"
                    value="BATTERY_OK"
                    checked={batteryCheckCode === 'BATTERY_OK'}
                    onChange={() => {
                      setBatteryCheckCode('BATTERY_OK');
                      setPiecesChecked(qtyReceiving);
                      setBatteriesInstalled(0);
                    }}
                    style={{ width: '20px', height: '20px' }}
                  />
                  <span style={{ fontSize: '0.9375rem', fontWeight: 600 }}>
                    Battery OK (Passed)
                  </span>
                </label>

                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    minHeight: '44px',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="battery_check"
                    value="BATTERY_REPLACED"
                    checked={batteryCheckCode === 'BATTERY_REPLACED'}
                    onChange={() => {
                      setBatteryCheckCode('BATTERY_REPLACED');
                      setPiecesChecked(qtyReceiving);
                      setBatteriesInstalled(qtyReceiving);
                    }}
                    style={{ width: '20px', height: '20px' }}
                  />
                  <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#2563eb' }}>
                    Battery Replaced (Deducts Stock)
                  </span>
                </label>
              </div>

              {batteryCheckCode === 'BATTERY_OK' && (
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
                    Pieces Checked (at least 1)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={qtyReceiving}
                    value={piecesChecked}
                    onChange={(e) => {
                      setPiecesChecked(parseInt(e.target.value) || 0);
                    }}
                    style={{
                      width: '120px',
                      minHeight: '44px',
                      padding: '0.5rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                    }}
                  />
                </div>
              )}

              {batteryCheckCode === 'BATTERY_REPLACED' && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: '1rem',
                    backgroundColor: '#f0f9ff',
                    padding: '1rem',
                    borderRadius: '6px',
                  }}
                >
                  <div>
                    <label
                      style={{
                        display: 'block',
                        fontSize: '0.8125rem',
                        fontWeight: 600,
                        color: '#0369a1',
                        marginBottom: '0.25rem',
                      }}
                    >
                      Pieces Checked (min 1)
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={qtyReceiving}
                      value={piecesChecked}
                      onChange={(e) => {
                        setPiecesChecked(parseInt(e.target.value) || 0);
                      }}
                      style={{
                        width: '100%',
                        minHeight: '44px',
                        padding: '0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #bae6fd',
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
                        color: '#0369a1',
                        marginBottom: '0.25rem',
                      }}
                    >
                      Batteries Installed (min 1)
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={batteriesInstalled}
                      onChange={(e) => {
                        setBatteriesInstalled(parseInt(e.target.value) || 0);
                      }}
                      style={{
                        width: '100%',
                        minHeight: '44px',
                        padding: '0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #bae6fd',
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
                        color: '#0369a1',
                        marginBottom: '0.25rem',
                      }}
                    >
                      Battery Type
                    </label>
                    <select
                      value={selectedBatteryTypeId}
                      onChange={(e) => {
                        setSelectedBatteryTypeId(e.target.value);
                      }}
                      style={{
                        width: '100%',
                        minHeight: '44px',
                        padding: '0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #bae6fd',
                        backgroundColor: '#fff',
                      }}
                      required
                    >
                      {batteryTypes.map((bt) => (
                        <option key={bt.id} value={bt.id}>
                          {bt.code} - {bt.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Conditional Cleaning Section (DEC-16, DEC-17) */}
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: '8px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Sparkles size={20} color="#059669" />
              <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>
                Cleaning & Scratch Treatment (DEC-16, DEC-17)
              </h3>
            </div>

            {isDirtyOrScratched && (
              <div style={{ fontSize: '0.8125rem', color: '#b45309', fontWeight: 600 }}>
                * Mandatory because source lot is dirty / scratched
              </div>
            )}

            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  minHeight: '44px',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="radio"
                  name="cleaning_code"
                  value="CLEANED_SELLABLE"
                  checked={cleaningCode === 'CLEANED_SELLABLE'}
                  onChange={() => {
                    handleCleaningChange('CLEANED_SELLABLE');
                  }}
                  style={{ width: '20px', height: '20px' }}
                />
                <span style={{ fontSize: '0.9375rem', fontWeight: 600 }}>
                  Cleaned OK / Sellable
                </span>
              </label>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  minHeight: '44px',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="radio"
                  name="cleaning_code"
                  value="PERMANENT_SCRATCHES"
                  checked={cleaningCode === 'PERMANENT_SCRATCHES'}
                  onChange={() => {
                    handleCleaningChange('PERMANENT_SCRATCHES');
                  }}
                  style={{ width: '20px', height: '20px' }}
                />
                <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#dc2626' }}>
                  Permanent Scratches (Forces NON_SELLABLE)
                </span>
              </label>
            </div>
          </div>

          {/* Classification Allocations with Reconciliation Meter */}
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: '8px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '0.5rem',
              }}
            >
              <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#0f172a' }}>
                Post-Servicing Classification Allocations
              </h3>

              {/* Reconciliation Meter */}
              <div
                style={{
                  padding: '0.375rem 0.75rem',
                  borderRadius: '20px',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  backgroundColor: meterMatches ? '#dcfce7' : '#fee2e2',
                  color: meterMatches ? '#15803d' : '#b91c1c',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                }}
              >
                {meterMatches ? <Check size={16} /> : <AlertTriangle size={16} />}
                Allocated: {totalAllocated} / Receiving: {qtyReceiving}
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: '1rem',
              }}
            >
              {/* FUNCTIONAL_REPAIRED */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#0f172a', fontSize: '0.875rem' }}>
                  Functional Repaired
                </div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                  Returns to Sahil (Intermediate)
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginTop: '0.5rem',
                  }}
                >
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={
                      cleaningCode === 'PERMANENT_SCRATCHES' || allocFunctionalRepaired <= 0
                    }
                    onClick={() => {
                      setAllocFunctionalRepaired(Math.max(0, allocFunctionalRepaired - 1));
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Minus size={18} />
                  </Button>
                  <span
                    style={{
                      fontSize: '1.25rem',
                      fontWeight: 700,
                      minWidth: '40px',
                      textAlign: 'center',
                    }}
                  >
                    {allocFunctionalRepaired}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES'}
                    onClick={() => {
                      setAllocFunctionalRepaired(allocFunctionalRepaired + 1);
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Plus size={18} />
                  </Button>
                </div>
              </div>

              {/* FUNCTIONAL_GOOD */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#0f172a', fontSize: '0.875rem' }}>
                  Functional Good
                </div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                  Returns to Sahil (Intermediate)
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginTop: '0.5rem',
                  }}
                >
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES' || allocFunctionalGood <= 0}
                    onClick={() => {
                      setAllocFunctionalGood(Math.max(0, allocFunctionalGood - 1));
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Minus size={18} />
                  </Button>
                  <span
                    style={{
                      fontSize: '1.25rem',
                      fontWeight: 700,
                      minWidth: '40px',
                      textAlign: 'center',
                    }}
                  >
                    {allocFunctionalGood}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES'}
                    onClick={() => {
                      setAllocFunctionalGood(allocFunctionalGood + 1);
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Plus size={18} />
                  </Button>
                </div>
              </div>

              {/* NON_GOOD */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#0f172a', fontSize: '0.875rem' }}>
                  Non-Good (Dismantle Queue)
                </div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                  Moves to Non-Functional Store
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginTop: '0.5rem',
                  }}
                >
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES' || allocNonGood <= 0}
                    onClick={() => {
                      setAllocNonGood(Math.max(0, allocNonGood - 1));
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Minus size={18} />
                  </Button>
                  <span
                    style={{
                      fontSize: '1.25rem',
                      fontWeight: 700,
                      minWidth: '40px',
                      textAlign: 'center',
                    }}
                  >
                    {allocNonGood}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES'}
                    onClick={() => {
                      setAllocNonGood(allocNonGood + 1);
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Plus size={18} />
                  </Button>
                </div>
              </div>

              {/* NON_SELLABLE */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#b91c1c', fontSize: '0.875rem' }}>
                  Non-Sellable
                </div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                  SPM / Scrap Store (G-12)
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginTop: '0.5rem',
                  }}
                >
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES' || allocNonSellable <= 0}
                    onClick={() => {
                      setAllocNonSellable(Math.max(0, allocNonSellable - 1));
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Minus size={18} />
                  </Button>
                  <span
                    style={{
                      fontSize: '1.25rem',
                      fontWeight: 700,
                      minWidth: '40px',
                      textAlign: 'center',
                    }}
                  >
                    {allocNonSellable}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={cleaningCode === 'PERMANENT_SCRATCHES'}
                    onClick={() => {
                      setAllocNonSellable(allocNonSellable + 1);
                    }}
                    style={{ minWidth: '44px', minHeight: '44px', padding: 0 }}
                  >
                    <Plus size={18} />
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Remarks */}
          <div
            style={{
              backgroundColor: '#fff',
              borderRadius: '8px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
            }}
          >
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.375rem',
              }}
            >
              Technician Remarks / Observations (Optional)
            </label>
            <input
              type="text"
              value={technicianRemarks}
              onChange={(e) => {
                setTechnicianRemarks(e.target.value);
              }}
              placeholder="e.g. Battery terminal cleaned, switch contact refitted"
              style={{
                width: '100%',
                minHeight: '44px',
                padding: '0.5rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
              }}
            />
          </div>

          {/* Action Bar */}
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
            <div style={{ fontSize: '0.875rem', color: '#475569' }}>
              Confirm receiving: <strong>{qtyReceiving} pcs</strong>
              {activeLine.supports_battery && batteryCheckCode === 'BATTERY_REPLACED' && (
                <span> ({batteriesInstalled} batteries to deduct)</span>
              )}
            </div>

            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <Button
                type="button"
                variant="secondary"
                onClick={onBack}
                disabled={submitting}
                style={{ minHeight: '44px' }}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={submitting || !meterMatches}
                style={{
                  minHeight: '44px',
                  minWidth: '160px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '0.5rem',
                  fontWeight: 600,
                }}
              >
                <Check size={18} />
                {submitting ? 'Confirming...' : 'Confirm Receiving'}
              </Button>
            </div>
          </div>
        </form>
      )}
    </div>
  );
}
