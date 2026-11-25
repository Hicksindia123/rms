import { useCallback, useMemo, useState } from 'react';
import {
  FileText,
  PlusCircle,
  RefreshCw,
  Search,
  ExternalLink,
  Split,
  AlertCircle,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { creditNotesApi } from './api';
import type {
  CreditNoteWorkQueue,
  CreditNoteWorkQueueItem,
  CnTypeCode,
  GstPortalCode,
} from './types';

/** Decimal fields arrive as JSON strings (Pydantic v2 Decimal), so coerce at runtime. */
const toNum = (v: number | string): number => Number(v);

interface AccountsCreditNoteQueuePageProps {
  onOpenCn: (id: string) => void;
  onOpenGs?: (id: string) => void;
  onOpenCnDecision?: (id: string) => void;
}

export function AccountsCreditNoteQueuePage({
  onOpenCn,
  onOpenGs,
  onOpenCnDecision,
}: AccountsCreditNoteQueuePageProps) {
  const [activeTab, setActiveTab] = useState<'pending' | 'register'>('pending');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [typeFilter, setTypeFilter] = useState<string>('ALL');

  // Work queue query
  const queueFetcher = useCallback(() => creditNotesApi.getWorkQueue(), []);
  const {
    data: workQueue,
    loading: loadingQueue,
    error: queueError,
    reload: reloadQueue,
  } = useApiQuery<CreditNoteWorkQueue>(queueFetcher);

  // Draft Creation Modal state
  const [draftingGs, setDraftingGs] = useState<CreditNoteWorkQueueItem | null>(null);
  const [draftCnType, setDraftCnType] = useState<CnTypeCode>('GENERAL_CN');
  const [draftGstCode, setDraftGstCode] = useState<GstPortalCode | ''>('');
  const [draftQty, setDraftQty] = useState<number>(1);
  const [draftSubmitting, setDraftSubmitting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const handleOpenDraftModal = (gs: CreditNoteWorkQueueItem) => {
    setDraftingGs(gs);
    setDraftQty(Math.max(1, gs.pending_to_credit_qty));
    setDraftCnType('GENERAL_CN');
    setDraftGstCode('');
    setDraftError(null);
  };

  const handleCreateDraft = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draftingGs) return;
    setDraftSubmitting(true);
    setDraftError(null);
    try {
      // Fetch GS CN decision prefill to get gs_item_ids
      const prefill = await creditNotesApi.getCnDecisionPrefill(draftingGs.gs_id);
      const allowedLines = prefill.prefill_lines.filter(
        (l) => l.default_decision_code === 'ALLOW_CN' && l.allowed_qty > 0,
      );

      if (allowedLines.length === 0) {
        throw new Error('No items in this Goods Slip have been allowed for Credit Note by RM.');
      }

      // Distribute draftQty across allowed lines
      let remaining = draftQty;
      const linesPayload = [];
      for (const line of allowedLines) {
        if (remaining <= 0) break;
        const take = Math.min(remaining, line.allowed_qty);
        linesPayload.push({
          gs_item_id: line.gs_item_id,
          qty: take,
        });
        remaining -= take;
      }

      const created = await creditNotesApi.create({
        gs_id: draftingGs.gs_id,
        cn_type_code: draftCnType,
        gst_portal_code: draftGstCode ? draftGstCode : undefined,
        lines: linesPayload,
      });

      setDraftingGs(null);
      reloadQueue();
      onOpenCn(created.id);
    } catch (err: unknown) {
      setDraftError(err instanceof Error ? err.message : 'Failed to draft credit note');
    } finally {
      setDraftSubmitting(false);
    }
  };

  // Filtered register items
  const filteredRegister = useMemo(() => {
    if (!workQueue?.active_notes) return [];
    return workQueue.active_notes.filter((item) => {
      if (statusFilter !== 'ALL' && item.status !== statusFilter) return false;
      if (typeFilter !== 'ALL' && item.cn_type_code !== typeFilter) return false;
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        item.gs_no.toLowerCase().includes(q) ||
        item.party_name.toLowerCase().includes(q) ||
        (item.cn_no && item.cn_no.toLowerCase().includes(q)) ||
        (item.jv_no && item.jv_no.toLowerCase().includes(q))
      );
    });
  }, [workQueue, statusFilter, typeFilter, searchQuery]);

  // Filtered pending items
  const filteredPending = useMemo(() => {
    if (!workQueue?.pending_gs) return [];
    return workQueue.pending_gs.filter((item) => {
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return item.gs_no.toLowerCase().includes(q) || item.party_name.toLowerCase().includes(q);
    });
  }, [workQueue, searchQuery]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'DRAFT':
        return <Badge variant="neutral">Draft</Badge>;
      case 'VERIFIED':
        return <Badge variant="info">Verified</Badge>;
      case 'ISSUED':
        return <Badge variant="success">Issued</Badge>;
      case 'CANCELLED':
        return <Badge variant="danger">Cancelled</Badge>;
      default:
        return <Badge variant="default">{status}</Badge>;
    }
  };

  const getTypeBadge = (type: CnTypeCode) => {
    switch (type) {
      case 'GST_CN':
        return (
          <span
            style={{
              backgroundColor: '#e0f2fe',
              color: '#0369a1',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            GST CN
          </span>
        );
      case 'GENERAL_CN':
        return (
          <span
            style={{
              backgroundColor: '#fef3c7',
              color: '#b45309',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            General CN
          </span>
        );
      case 'JV_ONLY':
        return (
          <span
            style={{
              backgroundColor: '#f3e8ff',
              color: '#7e22ce',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            JV Only
          </span>
        );
      default:
        return <Badge>{type}</Badge>;
    }
  };

  if (loadingQueue && !workQueue) {
    return <LoadingState label="Loading Accounts Credit Note Queue..." />;
  }

  if (queueError && !workQueue) {
    return (
      <ErrorState
        error={{ message: queueError.message }}
        onRetry={() => {
          reloadQueue();
        }}
      />
    );
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.5rem',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
            Credit Notes & Accounts Work Queue
          </h1>
          <p style={{ margin: '0.25rem 0 0 0', color: '#64748b', fontSize: '0.875rem' }}>
            Accounts verification (Deepak Ji), GST portal checks, commercial rate verification &
            voucher issuance (Step-7)
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              reloadQueue();
            }}
            disabled={loadingQueue}
          >
            <RefreshCw
              size={14}
              className={loadingQueue ? 'animate-spin' : ''}
              style={{ marginRight: '0.5rem' }}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid #e2e8f0',
          marginBottom: '1.5rem',
          gap: '1rem',
        }}
      >
        <button
          type="button"
          onClick={() => {
            setActiveTab('pending');
          }}
          style={{
            padding: '0.75rem 1rem',
            borderBottom: activeTab === 'pending' ? '2px solid #2a47f0' : '2px solid transparent',
            color: activeTab === 'pending' ? '#2a47f0' : '#64748b',
            fontWeight: activeTab === 'pending' ? 600 : 500,
            background: 'none',
            borderTop: 'none',
            borderLeft: 'none',
            borderRight: 'none',
            cursor: 'pointer',
            fontSize: '0.9375rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <FileText size={16} />
          Pending Goods Slips
          {workQueue?.pending_gs && (
            <span
              style={{
                backgroundColor: activeTab === 'pending' ? '#dce6ff' : '#f1f5f9',
                color: activeTab === 'pending' ? '#2236d6' : '#475569',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '0.75rem',
                fontWeight: 600,
              }}
            >
              {workQueue.pending_gs.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('register');
          }}
          style={{
            padding: '0.75rem 1rem',
            borderBottom: activeTab === 'register' ? '2px solid #2a47f0' : '2px solid transparent',
            color: activeTab === 'register' ? '#2a47f0' : '#64748b',
            fontWeight: activeTab === 'register' ? 600 : 500,
            background: 'none',
            borderTop: 'none',
            borderLeft: 'none',
            borderRight: 'none',
            cursor: 'pointer',
            fontSize: '0.9375rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <Split size={16} />
          Credit Notes Register
          {workQueue?.active_notes && (
            <span
              style={{
                backgroundColor: activeTab === 'register' ? '#dce6ff' : '#f1f5f9',
                color: activeTab === 'register' ? '#2236d6' : '#475569',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '0.75rem',
                fontWeight: 600,
              }}
            >
              {workQueue.active_notes.length}
            </span>
          )}
        </button>
      </div>

      {/* Search & Filter Toolbar */}
      <div
        style={{
          display: 'flex',
          gap: '1rem',
          marginBottom: '1.25rem',
          flexWrap: 'wrap',
          backgroundColor: '#ffffff',
          padding: '1rem',
          borderRadius: '8px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          alignItems: 'center',
        }}
      >
        <div style={{ flex: 1, minWidth: '240px', position: 'relative' }}>
          <Search
            size={16}
            style={{
              position: 'absolute',
              left: '0.75rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: '#94a3b8',
            }}
          />
          <input
            type="text"
            aria-label="Search credit notes by GS No, party or voucher No"
            placeholder="Search GS No, Party Name, Voucher No..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
            }}
            style={{
              width: '100%',
              padding: '0.5rem 0.75rem 0.5rem 2.25rem',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              fontSize: '0.875rem',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {activeTab === 'register' && (
          <>
            <div>
              <select
                aria-label="Filter by Credit Note Status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                }}
                style={{
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.875rem',
                  backgroundColor: '#ffffff',
                }}
              >
                <option value="ALL">All Statuses</option>
                <option value="DRAFT">Draft</option>
                <option value="VERIFIED">Verified</option>
                <option value="ISSUED">Issued</option>
                <option value="CANCELLED">Cancelled</option>
              </select>
            </div>

            <div>
              <select
                aria-label="Filter by Credit Note Type"
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value);
                }}
                style={{
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.875rem',
                  backgroundColor: '#ffffff',
                }}
              >
                <option value="ALL">All Types</option>
                <option value="GST_CN">GST Credit Note</option>
                <option value="GENERAL_CN">General Credit Note</option>
                <option value="JV_ONLY">Journal Voucher (JV Only)</option>
              </select>
            </div>
          </>
        )}
      </div>

      {/* Tab 1: Pending Goods Slips */}
      {activeTab === 'pending' && (
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '8px',
            overflow: 'hidden',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              textAlign: 'left',
              fontSize: '0.875rem',
            }}
          >
            <thead>
              <tr
                style={{
                  backgroundColor: '#f8fafc',
                  borderBottom: '1px solid #e2e8f0',
                  color: '#475569',
                  fontWeight: 600,
                }}
              >
                <th style={{ padding: '0.75rem 1rem' }}>Goods Slip</th>
                <th style={{ padding: '0.75rem 1rem' }}>Party Name</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>RM Allowed Qty</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>Already Drafted</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>Issued Qty</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>Pending to Credit</th>
                <th style={{ padding: '0.75rem 1rem' }}>RM Decision Date</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredPending.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}
                  >
                    No pending goods slips awaiting credit note drafting.
                  </td>
                </tr>
              ) : (
                filteredPending.map((item) => (
                  <tr key={item.gs_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: '#0f172a' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span>{item.gs_no}</span>
                        {onOpenGs && (
                          <button
                            type="button"
                            onClick={() => {
                              onOpenGs(item.gs_id);
                            }}
                            title="Open GS details"
                            style={{
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                              color: '#64748b',
                            }}
                          >
                            <ExternalLink size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '0.75rem 1rem', color: '#334155' }}>{item.party_name}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'center', fontWeight: 600 }}>
                      {item.allowed_cn_qty}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'center', color: '#64748b' }}>
                      {item.draft_cn_qty}
                    </td>
                    <td
                      style={{
                        padding: '0.75rem 1rem',
                        textAlign: 'center',
                        color: '#16a34a',
                        fontWeight: 600,
                      }}
                    >
                      {item.issued_cn_qty}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>
                      <span
                        style={{
                          backgroundColor: item.pending_to_credit_qty > 0 ? '#fef3c7' : '#f1f5f9',
                          color: item.pending_to_credit_qty > 0 ? '#b45309' : '#64748b',
                          padding: '2px 8px',
                          borderRadius: '12px',
                          fontWeight: 600,
                        }}
                      >
                        {item.pending_to_credit_qty}
                      </span>
                    </td>
                    <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                      {new Date(item.rm_decision_date).toLocaleDateString()}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                        {onOpenCnDecision && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              onOpenCnDecision(item.gs_id);
                            }}
                          >
                            View Decision
                          </Button>
                        )}
                        <Button
                          variant="primary"
                          size="sm"
                          disabled={item.pending_to_credit_qty <= 0}
                          onClick={() => {
                            handleOpenDraftModal(item);
                          }}
                        >
                          <PlusCircle size={14} style={{ marginRight: '0.25rem' }} />
                          Draft CN
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 2: Credit Notes Register */}
      {activeTab === 'register' && (
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '8px',
            overflow: 'hidden',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              textAlign: 'left',
              fontSize: '0.875rem',
            }}
          >
            <thead>
              <tr
                style={{
                  backgroundColor: '#f8fafc',
                  borderBottom: '1px solid #e2e8f0',
                  color: '#475569',
                  fontWeight: 600,
                }}
              >
                <th style={{ padding: '0.75rem 1rem' }}>Voucher / CN No</th>
                <th style={{ padding: '0.75rem 1rem' }}>Goods Slip</th>
                <th style={{ padding: '0.75rem 1rem' }}>Party Name</th>
                <th style={{ padding: '0.75rem 1rem' }}>Type</th>
                <th style={{ padding: '0.75rem 1rem' }}>Status</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>Total Qty</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Taxable Value</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Total Value</th>
                <th style={{ padding: '0.75rem 1rem' }}>Date</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredRegister.length === 0 ? (
                <tr>
                  <td
                    colSpan={10}
                    style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}
                  >
                    No credit notes found matching filters.
                  </td>
                </tr>
              ) : (
                filteredRegister.map((cn) => (
                  <tr key={cn.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: '#0f172a' }}>
                      {cn.cn_no || cn.jv_no || (
                        <span style={{ color: '#94a3b8' }}>DRAFT (Unassigned)</span>
                      )}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', color: '#334155' }}>{cn.gs_no}</td>
                    <td style={{ padding: '0.75rem 1rem', color: '#334155' }}>{cn.party_name}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{getTypeBadge(cn.cn_type_code)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{getStatusBadge(cn.status)}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'center', fontWeight: 600 }}>
                      {cn.total_qty}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                      ₹
                      {toNum(cn.taxable_value).toLocaleString('en-IN', {
                        minimumFractionDigits: 2,
                      })}
                    </td>
                    <td
                      style={{
                        padding: '0.75rem 1rem',
                        textAlign: 'right',
                        fontWeight: 700,
                        color: '#0f172a',
                      }}
                    >
                      ₹{toNum(cn.total_value).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                      {cn.issued_at
                        ? new Date(cn.issued_at).toLocaleDateString()
                        : new Date(cn.created_at).toLocaleDateString()}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          onOpenCn(cn.id);
                        }}
                      >
                        Open Workspace
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: Draft Credit Note */}
      {draftingGs && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(15, 23, 42, 0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '12px',
              maxWidth: '520px',
              width: '100%',
              padding: '1.5rem',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
            }}
          >
            <h2
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                margin: '0 0 0.5rem 0',
                color: '#0f172a',
              }}
            >
              Draft New Credit Note
            </h2>
            <p style={{ margin: '0 0 1.25rem 0', color: '#64748b', fontSize: '0.875rem' }}>
              Goods Slip: <strong>{draftingGs.gs_no}</strong> ({draftingGs.party_name})
            </p>

            {draftError && (
              <div
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                  padding: '0.75rem',
                  borderRadius: '6px',
                  marginBottom: '1rem',
                  fontSize: '0.875rem',
                  display: 'flex',
                  gap: '0.5rem',
                  alignItems: 'center',
                }}
              >
                <AlertCircle size={16} />
                <span>{draftError}</span>
              </div>
            )}

            <form onSubmit={(e) => void handleCreateDraft(e)}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div>
                  <label
                    htmlFor="draft-cn-type-select"
                    style={{
                      display: 'block',
                      fontSize: '0.8125rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Initial Credit Note Type
                  </label>
                  <select
                    id="draft-cn-type-select"
                    value={draftCnType}
                    onChange={(e) => {
                      setDraftCnType(e.target.value as CnTypeCode);
                    }}
                    style={{
                      width: '100%',
                      padding: '0.5rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.875rem',
                    }}
                  >
                    <option value="GST_CN">
                      GST Credit Note (Tax Invoice credit for Good units)
                    </option>
                    <option value="GENERAL_CN">General / Commercial CN (For Repaired units)</option>
                    <option value="JV_ONLY">Journal Voucher (JV Only - GST Not Reflected)</option>
                  </select>
                </div>

                {draftCnType === 'GST_CN' && (
                  <div>
                    <label
                      htmlFor="draft-gst-portal-select"
                      style={{
                        display: 'block',
                        fontSize: '0.8125rem',
                        fontWeight: 600,
                        color: '#334155',
                        marginBottom: '0.25rem',
                      }}
                    >
                      GST Portal Reflection Status
                    </label>
                    <select
                      id="draft-gst-portal-select"
                      value={draftGstCode}
                      onChange={(e) => {
                        setDraftGstCode(e.target.value as GstPortalCode);
                      }}
                      style={{
                        width: '100%',
                        padding: '0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #cbd5e1',
                        fontSize: '0.875rem',
                      }}
                    >
                      <option value="">Select GST Portal Status...</option>
                      <option value="GST_REFLECTED">GST_REFLECTED (Reflected in GSTR-1/2B)</option>
                      <option value="GST_NOT_REFLECTED">GST_NOT_REFLECTED (Not Reflected)</option>
                    </select>
                  </div>
                )}

                <div>
                  <label
                    htmlFor="draft-qty-input"
                    style={{
                      display: 'block',
                      fontSize: '0.8125rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Quantity to Credit (Max Allowed: {draftingGs.pending_to_credit_qty})
                  </label>
                  <input
                    id="draft-qty-input"
                    type="number"
                    min={1}
                    max={draftingGs.pending_to_credit_qty}
                    value={draftQty}
                    onChange={(e) => {
                      setDraftQty(parseInt(e.target.value, 10) || 1);
                    }}
                    style={{
                      width: '100%',
                      padding: '0.5rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.875rem',
                    }}
                  />
                </div>
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '0.75rem',
                  marginTop: '1.5rem',
                }}
              >
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setDraftingGs(null);
                  }}
                  disabled={draftSubmitting}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={
                    draftSubmitting || draftQty <= 0 || draftQty > draftingGs.pending_to_credit_qty
                  }
                >
                  {draftSubmitting ? 'Creating Draft...' : 'Create Draft'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
