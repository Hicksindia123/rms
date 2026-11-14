import { useCallback, useState } from 'react';
import { AlertCircle, Clock, ExternalLink, Filter, Search } from 'lucide-react';

import { Badge, Button, ErrorState, Input, LoadingState, Modal, Textarea } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';
import { pendencyApi } from './api';
import { ResolutionActionSelect } from './ResolutionActionSelect';
import type { ClearPendencyRequest, PendencyItem } from './types';

interface Props {
  onOpenGs: (gsId: string) => void;
}

export function PendencyRegisterPage({ onOpenGs }: Props) {
  const { me } = useAuth();
  const [statusFilter, setStatusFilter] = useState<'OPEN' | 'CLEARED' | 'ALL'>('OPEN');
  const [searchQuery, setSearchQuery] = useState('');

  const fetcher = useCallback(() => {
    const params: { status?: string } = {};
    if (statusFilter !== 'ALL') {
      params.status = statusFilter;
    }
    return pendencyApi.listPendencies(params);
  }, [statusFilter]);

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
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to clear pendency.';
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const filteredItems = (pendencies || []).filter((p) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      p.gs_no.toLowerCase().includes(q) ||
      p.party_name.toLowerCase().includes(q) ||
      (p.product_name && p.product_name.toLowerCase().includes(q)) ||
      p.reason.toLowerCase().includes(q)
    );
  });

  return (
    <div className="page" style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '1rem',
        }}
      >
        <div>
          <h1 className="page__title">Pendency (BP) Register</h1>
          <p className="page__subtitle">
            Items held in technical or commercial review (Branch Pending)
          </p>
        </div>
      </div>

      {/* Filters bar */}
      <div
        style={{
          display: 'flex',
          gap: '0.75rem',
          flexWrap: 'wrap',
          alignItems: 'center',
          backgroundColor: '#ffffff',
          padding: '0.75rem 1rem',
          borderRadius: '8px',
          border: '1px solid #e2e8f0',
          marginBottom: '1.25rem',
        }}
      >
        <div style={{ flex: '1 1 240px', position: 'relative' }}>
          <Input
            id="pendency-search"
            type="search"
            aria-label="Search by GS no., party, or product"
            placeholder="Search GS, party, or product…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
            }}
            style={{ paddingLeft: '2.25rem' }}
          />
          <Search
            size={16}
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: '0.75rem',
              top: '12px',
              color: 'var(--color-muted)',
            }}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Filter size={16} color="var(--color-muted)" />
          <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>Status:</span>
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            {(['OPEN', 'CLEARED', 'ALL'] as const).map((st) => (
              <Button
                key={st}
                type="button"
                variant={statusFilter === st ? 'primary' : 'outline'}
                size="sm"
                onClick={() => {
                  setStatusFilter(st);
                }}
              >
                {st}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {loading && !pendencies ? (
        <LoadingState label="Loading pendency register…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} title="Failed to load register" />
      ) : filteredItems.length === 0 ? (
        <div
          style={{
            textAlign: 'center',
            padding: '3rem 1rem',
            backgroundColor: '#ffffff',
            borderRadius: '8px',
            border: '1px solid #e2e8f0',
          }}
        >
          <Clock size={36} color="var(--color-muted)" style={{ margin: '0 auto 0.5rem auto' }} />
          <h3 style={{ margin: 0, fontSize: '1rem', color: '#0f172a' }}>No Pendencies Found</h3>
          <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: 'var(--color-muted)' }}>
            {searchQuery
              ? 'No items match your search term.'
              : `There are no ${statusFilter.toLowerCase()} pendencies at this time.`}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {filteredItems.map((p) => {
            const isOpen = p.status === 'OPEN';
            return (
              <div
                key={p.id}
                data-testid="pendency-row"
                style={{
                  backgroundColor: '#ffffff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  padding: '1rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  flexWrap: 'wrap',
                  gap: '1rem',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.35rem',
                    flex: '1 1 450px',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      flexWrap: 'wrap',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onOpenGs(p.gs_id);
                      }}
                      style={{
                        background: 'none',
                        border: 'none',
                        padding: 0,
                        cursor: 'pointer',
                        fontWeight: 700,
                        fontSize: '1rem',
                        color: 'var(--color-primary)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                      }}
                    >
                      {p.gs_no}
                      <ExternalLink size={14} />
                    </button>
                    <Badge variant={isOpen ? 'warning' : 'success'}>
                      {isOpen ? 'PENDING (BP)' : 'CLEARED'}
                    </Badge>
                    {p.blocks_gs && isOpen ? (
                      <Badge variant="danger">Blocks GS Transition</Badge>
                    ) : null}
                  </div>

                  <div style={{ fontSize: '0.875rem', color: '#1e293b' }}>
                    <strong>Party:</strong> {p.party_name}
                  </div>

                  <div style={{ fontSize: '0.875rem', color: '#334155' }}>
                    <strong>Item:</strong>{' '}
                    {p.product_name || (p.line_no ? `Line #${String(p.line_no)}` : 'Line —')}{' '}
                    <span style={{ fontWeight: 600 }}>(Held Qty: {p.qty})</span>
                  </div>

                  <div style={{ fontSize: '0.8125rem', color: '#475569' }}>
                    <strong>Reason:</strong> {p.reason}
                    {p.sent_to ? (
                      <span>
                        {' '}
                        &bull; <strong>Sent To:</strong> {p.sent_to}
                      </span>
                    ) : null}
                  </div>

                  <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                    Opened by <strong>{p.opened_by_name}</strong> on{' '}
                    {new Date(p.opened_at).toLocaleDateString()} &bull; Age: {p.age_days} day
                    {p.age_days === 1 ? '' : 's'} ({p.age_hours % 24}h)
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
                        <strong>Resolved to:</strong>{' '}
                        <Badge variant="info">{p.resolution_action || 'RESOLVED'}</Badge> by{' '}
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

                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      onOpenGs(p.gs_id);
                    }}
                  >
                    View Goods Slip
                  </Button>
                  {isOpen && canClearItem(p) ? (
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
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Clear Modal */}
      {selectedPendency ? (
        <Modal
          title={`Clear Pendency: ${selectedPendency.gs_no} — ${selectedPendency.product_name || (selectedPendency.line_no ? `Line #${String(selectedPendency.line_no)}` : 'Line —')}`}
          isOpen={true}
          onClose={() => {
            if (!submitting) setSelectedPendency(null);
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ margin: 0, fontSize: '0.875rem', color: '#475569' }}>
              Clearing releases <strong>{selectedPendency.qty}</strong> piece(s) from{' '}
              <code>PENDING_HOLD</code> back to active stock staging and updates the RM segregation
              revision.
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
                htmlFor="pendency-reg-resolution-action"
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
                id="pendency-reg-resolution-action"
                gsId={selectedPendency.gs_id}
                value={resolutionAction}
                onChange={setResolutionAction}
              />
            </div>

            <div>
              <label
                htmlFor="pendency-reg-clearance-notes"
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
                id="pendency-reg-clearance-notes"
                placeholder="e.g. Technical review complete; replaced by factory."
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
