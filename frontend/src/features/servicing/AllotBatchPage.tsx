import { useEffect, useState } from 'react';
import { ArrowLeft, Check, Minus, Plus } from 'lucide-react';
import { Button, LoadingState, ErrorState, Badge } from '@/components/ui';
import { servicingApi } from './api';
import type { IntermediateLot, Technician } from './types';

interface Props {
  currentUserName: string;
  onBack: () => void;
  onCreated: (batchId: string) => void;
}

export function AllotBatchPage({ currentUserName, onBack, onCreated }: Props) {
  const [lots, setLots] = useState<IntermediateLot[]>([]);
  const [technicians, setTechnicians] = useState<Technician[]>([]);
  const [selectedTechId, setSelectedTechId] = useState<string>('');
  const [selectedLots, setSelectedLots] = useState<Record<string, number>>({});
  const [notes, setNotes] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([servicingApi.getIntermediateLots(), servicingApi.getTechnicians()])
      .then(([lotsData, techsData]) => {
        if (!active) return;
        setLots(lotsData);
        setTechnicians(techsData);
        if (techsData.length > 0) {
          const rajKumar = techsData.find((t) => t.display_name.includes('Raj Kumar'));
          const chosen = rajKumar ?? techsData[0];
          if (chosen) setSelectedTechId(chosen.id);
        }
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Failed to load allotment data');
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const handleToggleLot = (lot: IntermediateLot) => {
    setSelectedLots((prev) => {
      if (prev[lot.lot_id] !== undefined) {
        const entries = Object.entries(prev).filter(([k]) => k !== lot.lot_id);
        return Object.fromEntries(entries);
      }
      return { ...prev, [lot.lot_id]: lot.available_qty };
    });
  };

  const handleQtyChange = (lotId: string, maxQty: number, delta: number) => {
    setSelectedLots((prev) => {
      const current = prev[lotId] ?? 0;
      const updated = Math.max(1, Math.min(maxQty, current + delta));
      return { ...prev, [lotId]: updated };
    });
  };

  const totalPieces = Object.values(selectedLots).reduce((acc, q) => acc + q, 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTechId) {
      setError('Please select a technician');
      return;
    }
    const lines = Object.entries(selectedLots).map(([lot_id, qty]) => ({
      lot_id,
      qty,
    }));
    if (lines.length === 0) {
      setError('Please select at least one lot to allot');
      return;
    }

    try {
      setSubmitting(true);
      setError(null);
      const idempotencyKey = `allot-${String(Date.now())}-${Math.random().toString(36).slice(2, 9)}`;
      const batch = await servicingApi.allotBatch(
        {
          technician_id: selectedTechId,
          notes: notes.trim() || undefined,
          lines,
        },
        idempotencyKey,
      );
      onCreated(batch.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to allot technician batch');
      setSubmitting(false);
    }
  };

  if (loading) return <LoadingState />;

  return (
    <div
      style={{
        maxWidth: '900px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Top back bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <Button
          type="button"
          variant="secondary"
          onClick={onBack}
          style={{ minHeight: '44px', display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <ArrowLeft size={16} />
          Back to Board
        </Button>
        <h1 style={{ margin: 0, fontSize: '1.375rem', fontWeight: 700, color: '#0f172a' }}>
          Allot Technician Batch
        </h1>
      </div>

      {error && <ErrorState error={{ message: error }} />}

      <form
        onSubmit={(e) => {
          void handleSubmit(e);
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}
      >
        {/* Info card */}
        <div
          style={{
            backgroundColor: '#fff',
            borderRadius: '8px',
            padding: '1.25rem',
            boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: '1rem',
          }}
        >
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.375rem',
              }}
            >
              Technician (Raj Kumar Ji)
            </label>
            <select
              value={selectedTechId}
              onChange={(e) => {
                setSelectedTechId(e.target.value);
              }}
              style={{
                width: '100%',
                minHeight: '44px',
                padding: '0.5rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '0.9375rem',
                backgroundColor: '#fff',
              }}
              required
            >
              {technicians.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.display_name}
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
                marginBottom: '0.375rem',
              }}
            >
              Data Entry Performed By (Technician Coordinator)
            </label>
            <div
              style={{
                minHeight: '44px',
                padding: '0.625rem 0.75rem',
                borderRadius: '6px',
                backgroundColor: '#f1f5f9',
                border: '1px solid #e2e8f0',
                color: '#334155',
                fontSize: '0.9375rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
              }}
            >
              {currentUserName} (Logged in)
            </div>
          </div>

          <div style={{ gridColumn: '1 / -1' }}>
            <label
              style={{
                display: 'block',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#475569',
                marginBottom: '0.375rem',
              }}
            >
              Allotment Notes (Optional)
            </label>
            <input
              type="text"
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
              }}
              placeholder="e.g. Priority repair, batch for Raj Kumar Ji"
              style={{
                width: '100%',
                minHeight: '44px',
                padding: '0.5rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '0.9375rem',
              }}
            />
          </div>
        </div>

        {/* Lot selection card */}
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 700, color: '#0f172a' }}>
                Intermediate Store Available Lots
              </h2>
              <p style={{ margin: '0.25rem 0 0', color: '#64748b', fontSize: '0.8125rem' }}>
                Pick lots to transfer to Raj Kumar Ji&apos;s Technician Bench (auto-accepted SoD
                bypass DEC-34)
              </p>
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#0369a1' }}>
              Total Allotment: {totalPieces} pcs
            </div>
          </div>

          {lots.length === 0 ? (
            <div style={{ padding: '2rem 1rem', textAlign: 'center', color: '#64748b' }}>
              No lots currently available in Intermediate Store for allotment.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {lots.map((lot) => {
                const isSelected = selectedLots[lot.lot_id] !== undefined;
                const qty = selectedLots[lot.lot_id] ?? 0;

                return (
                  <div
                    key={lot.lot_id}
                    style={{
                      border: isSelected ? '2px solid #2563eb' : '1px solid #e2e8f0',
                      backgroundColor: isSelected ? '#eff6ff' : '#f8fafc',
                      borderRadius: '8px',
                      padding: '1rem',
                      display: 'flex',
                      flexWrap: 'wrap',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '1rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {
                          handleToggleLot(lot);
                        }}
                        id={`lot-${lot.lot_id}`}
                        style={{
                          width: '22px',
                          height: '22px',
                          marginTop: '0.25rem',
                          cursor: 'pointer',
                        }}
                      />
                      <label htmlFor={`lot-${lot.lot_id}`} style={{ cursor: 'pointer' }}>
                        <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '1rem' }}>
                          {lot.product_name} ({lot.product_code})
                        </div>
                        <div
                          style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: '0.5rem',
                            marginTop: '0.25rem',
                          }}
                        >
                          {lot.gs_no && <Badge variant="info">GS: {lot.gs_no}</Badge>}
                          <Badge variant="neutral">{lot.condition_class}</Badge>
                          {lot.source_condition_code && (
                            <Badge variant="warning">{lot.source_condition_code}</Badge>
                          )}
                          {lot.requires_evaluation && (
                            <Badge variant="danger">Requires Evaluation</Badge>
                          )}
                        </div>
                        <div
                          style={{ fontSize: '0.8125rem', color: '#64748b', marginTop: '0.25rem' }}
                        >
                          Available in store: <strong>{lot.available_qty} pcs</strong>
                        </div>
                      </label>
                    </div>

                    {isSelected && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => {
                            handleQtyChange(lot.lot_id, lot.available_qty, -1);
                          }}
                          disabled={qty <= 1}
                          style={{
                            minWidth: '44px',
                            minHeight: '44px',
                            padding: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <Minus size={18} />
                        </Button>

                        <div
                          style={{
                            minWidth: '50px',
                            textAlign: 'center',
                            fontWeight: 700,
                            fontSize: '1.125rem',
                            color: '#0f172a',
                          }}
                        >
                          {qty}
                        </div>

                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => {
                            handleQtyChange(lot.lot_id, lot.available_qty, 1);
                          }}
                          disabled={qty >= lot.available_qty}
                          style={{
                            minWidth: '44px',
                            minHeight: '44px',
                            padding: 0,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <Plus size={18} />
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Submit Bar */}
        <div
          style={{
            backgroundColor: '#fff',
            borderRadius: '8px',
            padding: '1.25rem',
            boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '1rem',
          }}
        >
          <div style={{ fontSize: '0.9375rem', color: '#475569' }}>
            Selected: <strong>{Object.keys(selectedLots).length} lots</strong> ({totalPieces} total
            pieces)
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
              disabled={submitting || totalPieces === 0}
              style={{
                minHeight: '44px',
                minWidth: '150px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                fontWeight: 600,
              }}
            >
              <Check size={18} />
              {submitting ? 'Allotting...' : `Allot ${String(totalPieces)} Pieces`}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
