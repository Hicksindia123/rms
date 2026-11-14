import { useCallback, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';
import { pendencyApi } from './api';
import { ResolutionActionSelect } from './ResolutionActionSelect';
import type { ClearPendencyRequest, PendencyItem } from './types';

interface Props {
  gsId: string;
  onCleared?: () => void;
}

export function PendencyTab({ gsId, onCleared }: Props) {
  const { me } = useAuth();
  const fetcher = useCallback(() => pendencyApi.listPendencies({ gs_id: gsId }), [gsId]);
  const { data: pendencies, error, loading, reload } = useApiQuery<PendencyItem[]>(fetcher);

  const [selectedPendency, setSelectedPendency] = useState<PendencyItem | null>(null);
  const [resolutionAction, setResolutionAction] = useState('SEND_REPAIRED');
  const [clearNotes, setClearNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canClearItem = (item: PendencyItem) => {
    if (item.status !== 'OPEN') return false;
    const isRM =
      !!me && (me.profile.is_super_admin || me.roles.some((r) => r.code === 'REPLACEMENT_MANAGER'));
    const isOpener = !!me && item.opened_by === me.profile.id;
    return isRM || isOpener;
  };

  const handleOpenClearModal = (item: PendencyItem) => {
    setSelectedPendency(item);
    setResolutionAction('SEND_REPAIRED');
    setClearNotes('');
    setSubmitError(null);
  };

  const handleConfirmClear = async () => {
    if (!selectedPendency) return;
    if (!clearNotes.trim()) {
      setSubmitError('Please enter notes or explanation for clearing this pendency.');
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const payload: ClearPendencyRequest = {
        resolution_action: resolutionAction,
        notes: clearNotes.trim(),
      };
      await pendencyApi.clearPendency(selectedPendency.id, payload);
      setSelectedPendency(null);
      reload();
      onCleared?.();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to clear pendency.';
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && !pendencies) {
    return <LoadingState label="Loading pendencies…" />;
  }

  if (error) {
    return <ErrorState error={error} onRetry={reload} title="Failed to load pendencies" />;
  }

  if (!pendencies || pendencies.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--color-muted)' }}>
        <CheckCircle2
          size={36}
          color="var(--color-success)"
          style={{ margin: '0 auto 0.5rem auto' }}
        />
        <h3 style={{ margin: 0, fontSize: '1rem', color: '#0f172a' }}>No Pendencies</h3>
        <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem' }}>
          No items have been held in Pending (BP) for this Goods Slip.
        </p>
      </div>
    );
  }

  const openCount = pendencies.filter((p) => p.status === 'OPEN').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {openCount > 0 ? (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: '#f5f3ff',
            border: '1px solid #ddd6fe',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            color: '#5b21b6',
            fontSize: '0.875rem',
          }}
        >
          <Clock size={18} />
          <div>
            <strong>
              {openCount} Open Pendenc{openCount === 1 ? 'y' : 'ies'} (BP)
            </strong>
            <p style={{ margin: 0, fontSize: '0.8125rem', color: '#6d28d9' }}>
              Pending pieces are physically held in segregation. Clear them once technical review or
              repair decision is reached.
            </p>
          </div>
        </div>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {pendencies.map((p) => {
          const isOpen = p.status === 'OPEN';
          return (
            <div
              key={p.id}
              style={{
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '1rem',
                backgroundColor: '#ffffff',
                boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                display: 'flex',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '1rem',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.35rem',
                  flex: '1 1 300px',
                }}
              >
                <div
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}
                >
                  <Badge variant={isOpen ? 'warning' : 'success'}>
                    {isOpen ? 'PENDING (BP)' : 'CLEARED'}
                  </Badge>
                  {p.blocks_gs && isOpen ? (
                    <Badge variant="danger">Blocks GS Transition</Badge>
                  ) : null}
                  <strong style={{ fontSize: '0.9375rem' }}>
                    {p.product_name || (p.line_no ? `Line #${String(p.line_no)}` : 'Line —')}
                  </strong>
                  <span style={{ fontSize: '0.8125rem', color: '#64748b' }}>
                    (Qty: <strong>{p.qty}</strong>)
                  </span>
                </div>

                <div style={{ fontSize: '0.875rem', color: '#334155', marginTop: '0.25rem' }}>
                  <strong>Reason:</strong> {p.reason}
                </div>
                {p.sent_to ? (
                  <div style={{ fontSize: '0.8125rem', color: '#64748b' }}>
                    <strong>Sent To:</strong> {p.sent_to}
                  </div>
                ) : null}

                <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '0.25rem' }}>
                  Opened by <strong>{p.opened_by_name}</strong> on{' '}
                  {new Date(p.opened_at).toLocaleDateString()} (Age: {p.age_days}d{' '}
                  {p.age_hours % 24}h)
                </div>

                {!isOpen && p.cleared_at ? (
                  <div
                    style={{
                      marginTop: '0.5rem',
                      padding: '0.5rem 0.75rem',
                      backgroundColor: '#f8fafc',
                      borderLeft: '3px solid #22c55e',
                      borderRadius: '0 4px 4px 0',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <div>
                      <strong>Resolution:</strong> {p.resolution_action || 'RESOLVED'} by{' '}
                      <strong>{p.cleared_by_name}</strong> on{' '}
                      {new Date(p.cleared_at).toLocaleDateString()}
                    </div>
                    {p.clearance_notes ? (
                      <div style={{ marginTop: '0.25rem', color: '#475569' }}>
                        <em>"{p.clearance_notes}"</em>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {isOpen && canClearItem(p) ? (
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      handleOpenClearModal(p);
                    }}
                  >
                    Clear Pendency
                  </Button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {/* Clear Modal */}
      {selectedPendency ? (
        <Modal
          title={`Clear Pendency: ${selectedPendency.product_name || (selectedPendency.line_no ? `Line #${String(selectedPendency.line_no)}` : 'Line —')}`}
          isOpen={true}
          onClose={() => {
            if (!submitting) setSelectedPendency(null);
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ margin: 0, fontSize: '0.875rem', color: '#475569' }}>
              Clearing this pendency releases <strong>{selectedPendency.qty}</strong> piece(s) from{' '}
              <code>PENDING_HOLD</code> back to inventory staging and re-assigns them to the chosen
              action.
            </p>

            {submitError ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.5rem 0.75rem',
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '4px',
                  color: '#b91c1c',
                  fontSize: '0.8125rem',
                }}
              >
                <AlertCircle size={16} />
                <span>{submitError}</span>
              </div>
            ) : null}

            <div>
              <label
                htmlFor="pendency-resolution-action"
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Resolution Action <span style={{ color: '#ef4444' }}>*</span>
              </label>
              <ResolutionActionSelect
                id="pendency-resolution-action"
                gsId={gsId}
                value={resolutionAction}
                onChange={setResolutionAction}
              />
            </div>

            <div>
              <label
                htmlFor="pendency-clearance-notes"
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Clearance Notes / Reason <span style={{ color: '#ef4444' }}>*</span>
              </label>
              <Textarea
                id="pendency-clearance-notes"
                placeholder="e.g. Repaired in-house, ready to send repaired to customer."
                value={clearNotes}
                onChange={(e) => {
                  setClearNotes(e.target.value);
                }}
                rows={3}
              />
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.5rem',
                marginTop: '0.5rem',
              }}
            >
              <Button
                type="button"
                variant="ghost"
                disabled={submitting}
                onClick={() => {
                  setSelectedPendency(null);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                disabled={submitting}
                onClick={() => {
                  void handleConfirmClear();
                }}
              >
                {submitting ? 'Clearing…' : 'Confirm Clearance'}
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
