import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Edit,
  ExternalLink,
  FileCheck,
  FileText,
  History,
  Package,
  Plus,
  Printer,
  RefreshCw,
  RotateCcw,
  Trash2,
  Video,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { formatDateTime } from '@/features/goods-slips/format';
import { newIdempotencyKey } from '@/features/itemization/api';
import { toApiError, type ApiError } from '@/lib/api/client';

import { rmReviewApi } from './api';
import { RmAddLineModal, RmChangeProductModal, RmRemoveLineModal } from './RmReviewModals';
import type {
  RmApproveResult,
  RmReviewData,
  RmReviewItem,
} from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenTransfer?: (transferId: string) => void;
}

export function RmReviewPage({ gsId, onBack, onOpenTransfer }: Props) {
  const [data, setData] = useState<RmReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  // Edit Item modal state
  const [editingItem, setEditingItem] = useState<RmReviewItem | null>(null);
  const [editDocQty, setEditDocQty] = useState<number>(0);
  const [editRecvQty, setEditRecvQty] = useState<number>(0);
  const [editBuckets, setEditBuckets] = useState<Record<string, number>>({});
  const [editCounts, setEditCounts] = useState<Record<string, number>>({});
  const [editRemarks, setEditRemarks] = useState<string>('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<ApiError | null>(null);

  // Send Back modal state
  const [sendBackOpen, setSendBackOpen] = useState(false);
  const [sendBackRemarks, setSendBackRemarks] = useState('');
  const [sendingBack, setSendingBack] = useState(false);
  const [sendBackError, setSendBackError] = useState<ApiError | null>(null);

  // Approve state
  const [approveOpen, setApproveOpen] = useState(false);
  const [approveRemarks, setApproveRemarks] = useState('');
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<ApiError | null>(null);
  const [approveResult, setApproveResult] = useState<RmApproveResult | null>(null);

  // Show revisions accordion
  const [showRevisions, setShowRevisions] = useState(false);

  // DEC-54 G1: Add Line, Change Product, Remove Line states
  const [addLineOpen, setAddLineOpen] = useState(false);
  const [changingItem, setChangingItem] = useState<RmReviewItem | null>(null);
  const [removingItem, setRemovingItem] = useState<{ item: RmReviewItem; lineNo: number } | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await rmReviewApi.getReviewData(gsId);
      setData(res);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [gsId]);

  if (loading && !data) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={loadData} />;
  if (!data) return null;

  const gs = data.goods_slip;
  // DEC-54: After approval (or once transfer slip exists): read-only
  const isReviewable = data.can_review && gs.status === 'RM_REVIEW' && !data.transfer_slip;

  const openEditModal = (item: RmReviewItem) => {
    setEditingItem(item);
    setEditDocQty(item.documented_qty);
    setEditRecvQty(item.received_qty);

    const bMap: Record<string, number> = {};
    for (const b of item.allowed_buckets) {
      const existing = item.buckets.find((x) => x.field_code === b.field_code);
      bMap[b.field_code] = existing ? existing.qty : 0;
    }
    setEditBuckets(bMap);

    const cMap: Record<string, number> = {};
    for (const c of item.counts) {
      cMap[c.count_type] = c.count_value;
    }
    setEditCounts(cMap);

    setEditRemarks('');
    setEditError(null);
  };

  const handleSaveEdit = async () => {
    if (!editingItem) return;
    try {
      setSavingEdit(true);
      setEditError(null);

      const bucketPayload = editingItem.allowed_buckets.map((b) => ({
        field_code: b.field_code,
        qty: editBuckets[b.field_code] ?? 0,
      }));
      const countPayload = Object.entries(editCounts).map(([code, val]) => ({
        count_type: code,
        count_value: val,
      }));

      await rmReviewApi.editItem(
        gsId,
        editingItem.item_id,
        {
          documented_qty: editDocQty,
          received_qty: editRecvQty,
          buckets: bucketPayload,
          counts: countPayload,
          remarks: editRemarks.trim() || null,
        },
        newIdempotencyKey(),
      );

      setEditingItem(null);
      await loadData();
    } catch (err) {
      setEditError(toApiError(err));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleSendBack = async () => {
    if (sendBackRemarks.trim().length < 3) {
      setSendBackError({ message: 'A remark of at least 3 characters is required to send back' } as ApiError);
      return;
    }
    try {
      setSendingBack(true);
      setSendBackError(null);
      await rmReviewApi.sendBack(
        gsId,
        { remarks: sendBackRemarks.trim() },
        newIdempotencyKey(),
      );
      setSendBackOpen(false);
      await loadData();
    } catch (err) {
      setSendBackError(toApiError(err));
    } finally {
      setSendingBack(false);
    }
  };

  const handleApprove = async () => {
    try {
      setApproving(true);
      setApproveError(null);
      const res = await rmReviewApi.approve(
        gsId,
        { remarks: approveRemarks.trim() || null },
        newIdempotencyKey(),
      );
      setApproveResult(res);
      setApproveOpen(false);
      await loadData();
    } catch (err) {
      setApproveError(toApiError(err));
    } finally {
      setApproving(false);
    }
  };

  const currentEditBucketTotal = Object.values(editBuckets).reduce((a, b) => a + (Number(b) || 0), 0);
  const isEditConserved = currentEditBucketTotal === editRecvQty;

  return (
    <div className="page" style={{ maxWidth: '1200px', margin: '0 auto', padding: '1rem' }}>
      {/* Navigation header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
        <Button type="button" variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} /> Back
        </Button>
      </div>

      {/* Top Banner & Title */}
      <div
        className="card"
        style={{
          padding: '1.25rem',
          marginBottom: '1rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>
              RM Review: {gs.gs_no}
            </h1>
            <StatusChip status={gs.status} />
          </div>
          <div style={{ marginTop: '0.5rem', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
            Party: <strong>{gs.party_name || 'N/A'}</strong> &bull; Station: <strong>{gs.station_name || 'N/A'}</strong> &bull; Transporter: <strong>{gs.transporter_name || 'N/A'}</strong> &bull; Docket: <strong>{gs.docket_no || 'N/A'}</strong>
          </div>
          <div style={{ marginTop: '0.25rem', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
            Counted By: <strong>{gs.counted_by_name || 'Inward Verifier'}</strong> &bull; Cartons: <strong>{gs.carton_count}</strong> &bull; Inwarded: {formatDateTime(gs.created_at)}
          </div>
        </div>

        {/* Global actions for RM */}
        {isReviewable && (
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setSendBackRemarks('');
                setSendBackError(null);
                setSendBackOpen(true);
              }}
            >
              <RotateCcw size={16} style={{ marginRight: '6px' }} />
              Send Back
            </Button>

            <Button
              type="button"
              variant="primary"
              disabled={!data.all_conserved}
              onClick={() => {
                setApproveRemarks('');
                setApproveError(null);
                setApproveOpen(true);
              }}
            >
              <CheckCircle2 size={16} style={{ marginRight: '6px' }} />
              Approve &amp; Handover
            </Button>
          </div>
        )}
      </div>

      {/* Transfer Slip Note Banner (if approved or transfer exists) */}
      {(data.transfer_slip || approveResult) && (
        <div
          role="status"
          style={{
            padding: '1rem',
            borderRadius: '8px',
            backgroundColor: '#ecfdf5',
            border: '1px solid #10b981',
            marginBottom: '1rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.75rem',
          }}
        >
          <div>
            <div style={{ fontWeight: 600, color: '#065f46', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileCheck size={20} color="#059669" />
              Transfer Slip Auto-Generated: {approveResult?.transfer_no || data.transfer_slip?.transfer_no}
            </div>
            <div style={{ fontSize: '0.875rem', color: '#047857', marginTop: '0.25rem' }}>
              Goods handed to <strong>INTERMEDIATE_STORE</strong> (Total Qty:{' '}
              {data.transfer_slip?.total_qty || 'All lines'}) &bull; Status:{' '}
              <Badge variant="success">{data.transfer_slip?.status || 'INITIATED'}</Badge>
            </div>
          </div>
          {onOpenTransfer && (data.transfer_slip?.id || approveResult?.transfer_id) && (
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenTransfer((data.transfer_slip?.id || approveResult?.transfer_id)!)}
            >
              <Printer size={16} style={{ marginRight: '6px' }} />
              Print Transfer Note
            </Button>
          )}
        </div>
      )}

      {/* Documents & Unboxing Media Row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1rem',
          marginBottom: '1rem',
        }}
      >
        {/* Documents */}
        <div className="card" style={{ padding: '1rem' }}>
          <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={18} color="var(--color-primary)" />
            Uploaded Documents ({data.documents.length})
          </h3>
          {data.documents.length === 0 ? (
            <p style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>No documents uploaded.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {data.documents.map((doc) => (
                <div
                  key={doc.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0.5rem 0.75rem',
                    backgroundColor: 'var(--color-bg-subtle, #f9fafb)',
                    borderRadius: '6px',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                      {doc.document_type} {doc.document_number ? `(${doc.document_number})` : ''}
                    </div>
                    {doc.file_name && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-muted)' }}>{doc.file_name}</div>
                    )}
                  </div>
                  {doc.file_url ? (
                    <a
                      href={doc.file_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: '0.85rem', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      View <ExternalLink size={14} />
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Carton Videos */}
        <div className="card" style={{ padding: '1rem' }}>
          <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Video size={18} color="var(--color-primary)" />
            Carton Opening Videos ({data.carton_videos.length})
          </h3>
          {data.carton_videos.length === 0 ? (
            <p style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>No carton videos uploaded.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {data.carton_videos.map((vid) => (
                <div
                  key={vid.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0.5rem 0.75rem',
                    backgroundColor: 'var(--color-bg-subtle, #f9fafb)',
                    borderRadius: '6px',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                      Carton #{vid.carton_no || '1'} Video
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-muted)' }}>{vid.file_name}</div>
                  </div>
                  {vid.file_url ? (
                    <a
                      href={vid.file_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: '0.85rem', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      Play <ExternalLink size={14} />
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Items & Categorisation Table */}
      <div className="card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h2 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Package size={20} color="var(--color-primary)" />
            Counted Items &amp; Categorisation Breakdown
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {data.all_conserved ? (
              <Badge variant="success">All lines G-19 conserved</Badge>
            ) : (
              <Badge variant="danger">G-19 Mismatch present: Must resolve before approval</Badge>
            )}
            {isReviewable && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setAddLineOpen(true)}
              >
                <Plus size={14} style={{ marginRight: '4px' }} />
                Add line
              </Button>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {data.items.map((it, idx) => (
            <div
              key={it.item_id}
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                padding: '1rem',
                backgroundColor: 'var(--color-bg-subtle, #fcfcfc)',
              }}
            >
              {/* Item Header */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.5rem',
                  borderBottom: '1px solid var(--color-border)',
                  paddingBottom: '0.5rem',
                  marginBottom: '0.75rem',
                }}
              >
                <div>
                  <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>
                    #{idx + 1}. {it.sku_name}
                  </span>{' '}
                  <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>({it.sku_code})</span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.85rem' }}>
                    Doc: <strong>{it.documented_qty}</strong>
                  </span>
                  <span style={{ fontSize: '0.85rem' }}>
                    Counted: <strong>{it.received_qty}</strong>
                  </span>
                  {it.short_qty > 0 && <Badge variant="warning">Short: {it.short_qty}</Badge>}
                  {it.excess_qty > 0 && <Badge variant="info">Excess: {it.excess_qty}</Badge>}
                  {it.is_conserved ? (
                    <Badge variant="success">Conserved ({it.total_bucket_qty}/{it.received_qty})</Badge>
                  ) : (
                    <Badge variant="danger">
                      Mismatch ({it.total_bucket_qty}/{it.received_qty})
                    </Badge>
                  )}
                  {isReviewable && (
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => openEditModal(it)}
                      >
                        <Edit size={14} style={{ marginRight: '4px' }} />
                        Edit Qty/Buckets
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setChangingItem(it)}
                      >
                        <RefreshCw size={14} style={{ marginRight: '4px' }} />
                        Change product
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setRemovingItem({ item: it, lineNo: idx + 1 })}
                      >
                        <Trash2 size={14} style={{ marginRight: '4px' }} />
                        Remove line
                      </Button>
                    </div>
                  )}
                </div>
              </div>

              {/* Bucket details chips */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                {it.buckets.map((b) => (
                  <div
                    key={b.field_code}
                    style={{
                      padding: '0.25rem 0.5rem',
                      borderRadius: '4px',
                      backgroundColor: b.qty > 0 ? 'var(--color-bg-card, #ffffff)' : 'transparent',
                      border: '1px solid var(--color-border)',
                      fontSize: '0.8rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <span style={{ color: 'var(--color-muted)' }}>{b.field_label || b.field_code}:</span>
                    <strong>{b.qty}</strong>
                  </div>
                ))}
              </div>

              {/* Counts details */}
              {it.counts.length > 0 && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: 'var(--color-muted)', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                  {it.counts.map((c) => (
                    <span key={c.count_type}>
                      {c.field_label || c.count_type}: <strong>{c.count_value}</strong>
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Revision History Section */}
      <div className="card" style={{ padding: '1rem', marginBottom: '1rem' }}>
        <button
          type="button"
          onClick={() => setShowRevisions(!showRevisions)}
          style={{
            width: '100%',
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            textAlign: 'left',
          }}
        >
          <div style={{ fontWeight: 600, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <History size={18} color="var(--color-primary)" />
            Revision Audit Trail ({data.revisions.length} revision{data.revisions.length === 1 ? '' : 's'})
          </div>
          <span style={{ color: 'var(--color-muted)', fontSize: '0.85rem' }}>
            {showRevisions ? 'Collapse ▲' : 'Expand ▼'}
          </span>
        </button>

        {showRevisions && (
          <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {data.revisions.map((rev) => (
              <div
                key={rev.id}
                style={{
                  borderLeft: '3px solid var(--color-primary)',
                  paddingLeft: '0.75rem',
                  paddingTop: '0.25rem',
                  paddingBottom: '0.25rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <strong>Revision #{rev.revision_no}</strong>
                  <Badge
                    variant={
                      rev.action === 'RM_APPROVED'
                        ? 'success'
                        : rev.action === 'RM_SENT_BACK'
                        ? 'warning'
                        : rev.action === 'RM_REMOVE_LINE'
                        ? 'danger'
                        : rev.action === 'RM_CHANGE_PRODUCT'
                        ? 'warning'
                        : rev.action === 'RM_ADD_LINE'
                        ? 'success'
                        : 'info'
                    }
                  >
                    {rev.action}
                  </Badge>
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>
                    by {rev.created_by_name || 'System'} at {formatDateTime(rev.created_at)}
                  </span>
                </div>
                {rev.remarks && (
                  <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem', fontStyle: 'italic', color: 'var(--color-text)' }}>
                    "{rev.remarks}"
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Edit Item Modal */}
      {editingItem && (
        <Modal
          isOpen={true}
          onClose={() => setEditingItem(null)}
          title={`Edit Item: ${editingItem.sku_name}`}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <div>
                <label className="form-label" htmlFor="edit-doc-qty">
                  Documented Qty
                </label>
                <input
                  id="edit-doc-qty"
                  type="number"
                  min="0"
                  value={editDocQty}
                  onChange={(e) => setEditDocQty(parseInt(e.target.value, 10) || 0)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--color-border)' }}
                />
              </div>
              <div>
                <label className="form-label" htmlFor="edit-recv-qty">
                  Received (Counted) Qty
                </label>
                <input
                  id="edit-recv-qty"
                  type="number"
                  min="0"
                  value={editRecvQty}
                  onChange={(e) => setEditRecvQty(parseInt(e.target.value, 10) || 0)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid var(--color-border)' }}
                />
              </div>
            </div>

            {/* Buckets input */}
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.5rem' }}>
                Condition Buckets (Sum must equal {editRecvQty}):
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.5rem' }}>
                {editingItem.allowed_buckets.map((b) => (
                  <div key={b.field_code} style={{ display: 'flex', flexDirection: 'column' }}>
                    <label style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--color-muted)' }}>
                      {b.field_label}
                    </label>
                    <input
                      type="number"
                      min="0"
                      value={editBuckets[b.field_code] ?? 0}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10) || 0;
                        setEditBuckets((prev) => ({ ...prev, [b.field_code]: val }));
                      }}
                      style={{ padding: '0.4rem', borderRadius: '4px', border: '1px solid var(--color-border)' }}
                    />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: '0.5rem' }}>
                {isEditConserved ? (
                  <Badge variant="success">
                    <CheckCircle2 size={12} style={{ marginRight: '4px' }} />
                    Conserved: Total {currentEditBucketTotal} = {editRecvQty}
                  </Badge>
                ) : (
                  <Badge variant="danger">
                    <AlertTriangle size={12} style={{ marginRight: '4px' }} />
                    Mismatch: Total {currentEditBucketTotal} != {editRecvQty} (Difference: {currentEditBucketTotal - editRecvQty})
                  </Badge>
                )}
              </div>
            </div>

            {/* Mandatory remarks for audit */}
            <div>
              <label className="form-label" htmlFor="edit-remarks">
                Reason for Adjustment (Recorded in Revision Audit)
              </label>
              <Textarea
                id="edit-remarks"
                rows={2}
                value={editRemarks}
                placeholder="e.g. Adjusted count from 8 to 6 after verifying package labels"
                onChange={(e) => setEditRemarks(e.target.value)}
              />
            </div>

            {editError && (
              <p role="alert" className="form-control__error">
                {editError.message}
              </p>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
              <Button type="button" variant="outline" onClick={() => setEditingItem(null)}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                isLoading={savingEdit}
                disabled={!isEditConserved}
                onClick={() => void handleSaveEdit()}
              >
                Save Adjustment (G-19)
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Send Back Modal */}
      {sendBackOpen && (
        <Modal
          isOpen={true}
          onClose={() => setSendBackOpen(false)}
          title="Send Back to Categorisation"
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--color-muted)' }}>
              This will transition the Goods Slip back to <strong>Categorisation</strong> so the inward verifier can
              re-verify quantities and condition buckets.
            </p>
            <div>
              <label className="form-label" htmlFor="sendback-remarks">
                Remarks for Inward Verifier (Mandatory)
              </label>
              <Textarea
                id="sendback-remarks"
                rows={3}
                value={sendBackRemarks}
                placeholder="e.g. Please verify packaging condition for remaining 2 pieces"
                onChange={(e) => setSendBackRemarks(e.target.value)}
              />
            </div>
            {sendBackError && (
              <p role="alert" className="form-control__error">
                {sendBackError.message}
              </p>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <Button type="button" variant="outline" onClick={() => setSendBackOpen(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                isLoading={sendingBack}
                disabled={sendBackRemarks.trim().length < 3}
                onClick={() => void handleSendBack()}
              >
                Confirm Send Back
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Approve Modal */}
      {approveOpen && (
        <Modal
          isOpen={true}
          onClose={() => setApproveOpen(false)}
          title="Approve &amp; Generate Custody Transfer Slip"
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ margin: 0, fontSize: '0.875rem' }}>
              Approving this goods slip will automatically generate a <strong>Transfer Slip (TRF/...)</strong> handing
              over all items to the <strong>Intermediate Store Manager</strong>.
            </p>
            <div>
              <label className="form-label" htmlFor="approve-remarks">
                Approval Remarks (Optional)
              </label>
              <Textarea
                id="approve-remarks"
                rows={2}
                value={approveRemarks}
                placeholder="e.g. All pieces verified and approved for Intermediate Store handover"
                onChange={(e) => setApproveRemarks(e.target.value)}
              />
            </div>
            {approveError && (
              <p role="alert" className="form-control__error">
                {approveError.message}
              </p>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <Button type="button" variant="outline" onClick={() => setApproveOpen(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                isLoading={approving}
                onClick={() => void handleApprove()}
              >
                Approve &amp; Generate Transfer
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* DEC-54 Modals */}
      <RmAddLineModal
        gsId={gsId}
        isOpen={addLineOpen}
        onClose={() => setAddLineOpen(false)}
        onSuccess={loadData}
      />

      {changingItem && (
        <RmChangeProductModal
          gsId={gsId}
          item={changingItem}
          isOpen={true}
          onClose={() => setChangingItem(null)}
          onSuccess={loadData}
        />
      )}

      {removingItem && (
        <RmRemoveLineModal
          gsId={gsId}
          item={removingItem.item}
          lineNo={removingItem.lineNo}
          totalLines={data.items.length}
          isOpen={true}
          onClose={() => setRemovingItem(null)}
          onSuccess={loadData}
        />
      )}
    </div>
  );
}
