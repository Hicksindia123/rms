import { useCallback, useState } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  Printer,
  Ban,
  Split,
  Eye,
  Save,
  Send,
  ShieldAlert,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { creditNotesApi } from './api';
import type {
  CreditNoteDetail,
  PartyDocCode,
  GstPortalCode,
  GstReturnType,
  CnTypeCode,
  RateReferenceCode,
} from './types';

/** Decimal fields arrive as JSON strings (Pydantic v2 Decimal), so coerce at runtime. */
const toNum = (v: number | string): number => Number(v);

interface CreditNoteWorkspacePageProps {
  cnId: string;
  onBack: () => void;
  onOpenPrint: () => void;
}

export function CreditNoteWorkspacePage({
  cnId,
  onBack,
  onOpenPrint,
}: CreditNoteWorkspacePageProps) {
  const fetcher = useCallback(() => creditNotesApi.get(cnId), [cnId]);
  const { data: cn, loading, error, reload } = useApiQuery<CreditNoteDetail>(fetcher);

  // Card 1: Party Document form
  const [partyDocCode, setPartyDocCode] = useState<PartyDocCode>('PARTY_INVOICE');
  const [partyDocNo, setPartyDocNo] = useState('');
  const [partyDocDate, setPartyDocDate] = useState('');
  const [partyDocAmount, setPartyDocAmount] = useState<number | ''>('');
  const [partyDocNotes, setPartyDocNotes] = useState('');
  const [savingPartyDoc, setSavingPartyDoc] = useState(false);
  const [partyDocSuccess, setPartyDocSuccess] = useState(false);

  // Card 2: GST Check form
  const [gstPortalCode, setGstPortalCode] = useState<GstPortalCode>('GST_REFLECTED');
  const [gstReturnType, setGstReturnType] = useState<GstReturnType>('GSTR-1');
  const [gstPeriod, setGstPeriod] = useState('102026');
  const [gstCheckedOn, setGstCheckedOn] = useState(new Date().toISOString().slice(0, 10));
  const [savingGst, setSavingGst] = useState(false);
  const [gstSuccess, setGstSuccess] = useState(false);

  // Card 3: Type Selection
  const [savingType, setSavingType] = useState(false);
  const [typeError, setTypeError] = useState<string | null>(null);

  // Card 4: Rate Verification Modal
  const [rateModalLineId, setRateModalLineId] = useState<string | null>(null);
  const [rateRefCode, setRateRefCode] = useState<RateReferenceCode>('RATE_SALES');
  const [rateDocNo, setRateDocNo] = useState('');
  const [rateDocDate, setRateDocDate] = useState(new Date().toISOString().slice(0, 10));
  const [rateVal, setRateVal] = useState<number | ''>('');
  const [rateNotes, setRateNotes] = useState('');
  const [savingRate, setSavingRate] = useState(false);
  const [rateWarning, setRateWarning] = useState<string | null>(null);
  const [rateModalError, setRateModalError] = useState<string | null>(null);

  // Card 5: Issue Form
  const [voucherNo, setVoucherNo] = useState('');
  const [voucherDate, setVoucherDate] = useState(new Date().toISOString().slice(0, 10));
  const [issuing, setIssuing] = useState(false);
  const [issueError, setIssueError] = useState<string | null>(null);

  // Cancel Modal
  const [isCancelModalOpen, setIsCancelModalOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  // Split CN state
  const [splitting, setSplitting] = useState(false);
  const [splitMsg, setSplitMsg] = useState<string | null>(null);

  // Sync state once data loaded
  const [initialLoaded, setInitialLoaded] = useState(false);
  if (cn && !initialLoaded) {
    if (cn.party_doc_code) setPartyDocCode(cn.party_doc_code);
    if (cn.party_doc_no) setPartyDocNo(cn.party_doc_no);
    if (cn.party_doc_date) setPartyDocDate(cn.party_doc_date);
    if (cn.party_doc_amount !== null) setPartyDocAmount(cn.party_doc_amount);
    if (cn.party_doc_notes) setPartyDocNotes(cn.party_doc_notes);

    if (cn.gst_portal_code) setGstPortalCode(cn.gst_portal_code);
    if (cn.gst_return_type) setGstReturnType(cn.gst_return_type);
    if (cn.gst_return_period) setGstPeriod(cn.gst_return_period);
    if (cn.gst_checked_on) setGstCheckedOn(cn.gst_checked_on);

    if (cn.cn_no) setVoucherNo(cn.cn_no);
    else if (cn.jv_no) setVoucherNo(cn.jv_no);
    if (cn.cn_date) setVoucherDate(cn.cn_date);
    else if (cn.jv_date) setVoucherDate(cn.jv_date);

    setInitialLoaded(true);
  }

  const handleSavePartyDoc = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingPartyDoc(true);
    setPartyDocSuccess(false);
    try {
      await creditNotesApi.verifyPartyDoc(cnId, {
        party_doc_code: partyDocCode,
        doc_no: partyDocNo.trim() || undefined,
        doc_date: partyDocDate || undefined,
        amount: typeof partyDocAmount === 'number' ? partyDocAmount : undefined,
        notes: partyDocNotes.trim() || undefined,
      });
      setPartyDocSuccess(true);
      reload();
      setTimeout(() => {
        setPartyDocSuccess(false);
      }, 3000);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to save party document verification');
    } finally {
      setSavingPartyDoc(false);
    }
  };

  const handleSaveGstCheck = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingGst(true);
    setGstSuccess(false);
    try {
      await creditNotesApi.verifyGstCheck(cnId, {
        gst_portal_code: gstPortalCode,
        return_type: gstReturnType,
        return_period: gstPeriod.trim() || undefined,
        checked_on: gstCheckedOn,
      });
      setGstSuccess(true);
      reload();
      setTimeout(() => {
        setGstSuccess(false);
      }, 3000);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to save GST portal check');
    } finally {
      setSavingGst(false);
    }
  };

  const handleUpdateType = async (type: CnTypeCode) => {
    setSavingType(true);
    setTypeError(null);
    try {
      await creditNotesApi.updateType(cnId, type);
      reload();
    } catch (err: unknown) {
      setTypeError(err instanceof Error ? err.message : 'Failed to update CN type');
    } finally {
      setSavingType(false);
    }
  };

  const handleSplitCn = async () => {
    if (
      !window.confirm(
        'Split good pieces (GST CN) and repaired pieces (General CN) into separate credit notes?',
      )
    ) {
      return;
    }
    setSplitting(true);
    setSplitMsg(null);
    try {
      const res = await creditNotesApi.split(cnId);
      setSplitMsg(res.message);
      reload();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to split credit note');
    } finally {
      setSplitting(false);
    }
  };

  const handleOpenRateModal = (lineId: string) => {
    setRateModalLineId(lineId);
    setRateRefCode('RATE_SALES');
    setRateDocNo('');
    setRateVal('');
    setRateNotes('');
    setRateWarning(null);
    setRateModalError(null);
  };

  const handleSaveRate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rateModalLineId || typeof rateVal !== 'number' || rateVal <= 0) return;
    setSavingRate(true);
    setRateModalError(null);
    setRateWarning(null);
    try {
      const res = await creditNotesApi.verifyRate(rateModalLineId, {
        reference_code: rateRefCode,
        ref_doc_no: rateDocNo.trim(),
        ref_doc_date: rateDocDate,
        rate: rateVal,
        notes: rateNotes.trim() || undefined,
      });

      if (res.has_variance_warning && res.variance_warning_message) {
        setRateWarning(res.variance_warning_message);
      } else {
        setRateModalLineId(null);
      }
      reload();
    } catch (err: unknown) {
      setRateModalError(err instanceof Error ? err.message : 'Failed to record rate verification');
    } finally {
      setSavingRate(false);
    }
  };

  const handleIssueVoucher = async (e: React.FormEvent) => {
    e.preventDefault();
    setIssuing(true);
    setIssueError(null);
    try {
      const isJv = cn?.cn_type_code === 'JV_ONLY';
      await creditNotesApi.issue(cnId, {
        cn_no: isJv ? undefined : voucherNo.trim(),
        cn_date: isJv ? undefined : voucherDate,
        jv_no: isJv ? voucherNo.trim() : undefined,
        jv_date: isJv ? voucherDate : undefined,
      });
      reload();
    } catch (err: unknown) {
      setIssueError(err instanceof Error ? err.message : 'Failed to issue voucher');
    } finally {
      setIssuing(false);
    }
  };

  const handleCancelCn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cancelReason.trim()) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await creditNotesApi.cancel(cnId, cancelReason.trim());
      setIsCancelModalOpen(false);
      reload();
    } catch (err: unknown) {
      setCancelError(err instanceof Error ? err.message : 'Failed to cancel credit note');
    } finally {
      setCancelling(false);
    }
  };

  if (loading && !cn) {
    return <LoadingState label="Loading Credit Note Workspace..." />;
  }

  if (error && !cn) {
    return <ErrorState error={{ message: error.message }} onRetry={reload} />;
  }

  if (!cn) return null;

  const isIssued = cn.status === 'ISSUED';
  const isCancelled = cn.status === 'CANCELLED';
  const isReadOnly = isIssued || isCancelled;
  const isJv = cn.cn_type_code === 'JV_ONLY';

  return (
    <div style={{ padding: '1.5rem', maxWidth: '1600px', margin: '0 auto' }}>
      {/* Top Bar */}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Button variant="outline" size="sm" onClick={onBack}>
            <ArrowLeft size={16} style={{ marginRight: '0.25rem' }} />
            Back to Queue
          </Button>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h1 style={{ fontSize: '1.375rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
                Credit Note Workspace: {cn.cn_no || cn.jv_no || 'DRAFT'}
              </h1>
              <Badge variant={isIssued ? 'success' : isCancelled ? 'danger' : 'neutral'}>
                {cn.status}
              </Badge>
              <span
                style={{
                  backgroundColor: isJv
                    ? '#f3e8ff'
                    : cn.cn_type_code === 'GST_CN'
                      ? '#e0f2fe'
                      : '#fef3c7',
                  color: isJv ? '#7e22ce' : cn.cn_type_code === 'GST_CN' ? '#0369a1' : '#b45309',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                }}
              >
                {cn.cn_type_label}
              </span>
            </div>
            <p style={{ margin: '0.25rem 0 0 0', color: '#64748b', fontSize: '0.8125rem' }}>
              Goods Slip: <strong>{cn.gs_no}</strong> | Party: <strong>{cn.party_name}</strong> |
              Created by {cn.created_by_name} on {new Date(cn.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <Button variant="outline" size="sm" onClick={onOpenPrint}>
            <Printer size={16} style={{ marginRight: '0.25rem' }} />
            Print Note
          </Button>

          {!isReadOnly && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setIsCancelModalOpen(true);
              }}
              style={{ color: '#dc2626', borderColor: '#fecaca' }}
            >
              <Ban size={16} style={{ marginRight: '0.25rem' }} />
              Cancel CN
            </Button>
          )}
        </div>
      </div>

      {splitMsg && (
        <div
          style={{
            backgroundColor: '#eef3ff',
            border: '1px solid #bfd0ff',
            color: '#2236d6',
            padding: '0.75rem 1rem',
            borderRadius: '8px',
            marginBottom: '1.25rem',
            fontSize: '0.875rem',
          }}
        >
          {splitMsg}
        </div>
      )}

      {/* Split Screen Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1.5fr',
          gap: '1.5rem',
          alignItems: 'start',
        }}
      >
        {/* Left Column: Goods Slip Evidence & Documents */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Party & GS Summary Card */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
            }}
          >
            <h3
              style={{
                fontSize: '1rem',
                fontWeight: 600,
                margin: '0 0 0.75rem 0',
                color: '#0f172a',
              }}
            >
              Party & Commercial Profile
            </h3>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '0.75rem',
                fontSize: '0.8125rem',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>Party Name:</span>
                <div style={{ fontWeight: 600, color: '#1e293b' }}>{cn.party_name}</div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>GSTIN:</span>
                <div style={{ fontWeight: 600, color: '#1e293b' }}>
                  {cn.party_gstin || 'None / Unregistered'}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Party State:</span>
                <div style={{ fontWeight: 600, color: '#1e293b' }}>
                  {cn.party_state || 'Unknown'}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Tax Classification:</span>
                <div style={{ fontWeight: 600, color: cn.is_inter_state ? '#b45309' : '#0369a1' }}>
                  {cn.is_inter_state ? 'Inter-State (IGST 18%)' : 'Intra-State (CGST 9% + SGST 9%)'}
                </div>
              </div>
            </div>
          </div>

          {/* Step-2 Unboxing Documents & Scans Card */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '0.75rem',
              }}
            >
              <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                Step-2 GS Documents & Evidence ({cn.linked_step2_documents.length})
              </h3>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>For Side-by-Side Review</span>
            </div>

            {cn.linked_step2_documents.length === 0 ? (
              <div
                style={{
                  padding: '1.5rem',
                  textAlign: 'center',
                  color: '#94a3b8',
                  fontSize: '0.875rem',
                }}
              >
                No documents uploaded during Step-2 Unboxing.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {cn.linked_step2_documents.map((doc) => (
                  <div
                    key={doc.id}
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: '8px',
                      padding: '0.75rem 1rem',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      backgroundColor: '#f8fafc',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '0.875rem', color: '#0f172a' }}>
                        {doc.document_type_label} {doc.doc_no && `(${doc.doc_no})`}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.2rem' }}>
                        {doc.doc_date && `Date: ${doc.doc_date}`}
                        {doc.amount !== null &&
                          ` | Amount: ₹${toNum(doc.amount).toLocaleString('en-IN')}`}
                      </div>
                    </div>

                    {doc.storage_path && (
                      <a
                        href={`/api/v1/attachments/${doc.attachment_id}/preview`}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                          color: '#2a47f0',
                          fontSize: '0.8125rem',
                          fontWeight: 500,
                          textDecoration: 'none',
                        }}
                      >
                        <Eye size={14} />
                        View Scan
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick Actions / Split Tool */}
          {!isReadOnly && (
            <div
              style={{
                backgroundColor: '#ffffff',
                borderRadius: '10px',
                padding: '1.25rem',
                boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                border: '1px solid #e2e8f0',
              }}
            >
              <h3
                style={{
                  fontSize: '1rem',
                  fontWeight: 600,
                  margin: '0 0 0.5rem 0',
                  color: '#0f172a',
                }}
              >
                Split Credit Note Tool
              </h3>
              <p style={{ margin: '0 0 1rem 0', color: '#64748b', fontSize: '0.8125rem' }}>
                If this Credit Note contains a mix of Good (packed) and Repaired pieces,
                automatically segregate them into separate GST and General Credit Notes.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleSplitCn()}
                disabled={splitting}
              >
                <Split size={14} style={{ marginRight: '0.25rem' }} />
                {splitting ? 'Splitting...' : 'Split Good vs Repaired Lines'}
              </Button>
            </div>
          )}
        </div>

        {/* Right Column: Verification & Issuance Stepper */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Card 1: Party Document Verification */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    backgroundColor: '#2a47f0',
                    color: '#ffffff',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.75rem',
                    fontWeight: 700,
                  }}
                >
                  1
                </span>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                  Party Document Verification
                </h3>
              </div>
              {cn.party_doc_code && <Badge variant="success">Verified</Badge>}
            </div>

            <form onSubmit={(e) => void handleSavePartyDoc(e)}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '1rem',
                  marginBottom: '1rem',
                }}
              >
                <div>
                  <label
                    htmlFor="party-doc-type-select"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Document Type
                  </label>
                  <select
                    id="party-doc-type-select"
                    value={partyDocCode}
                    onChange={(e) => {
                      setPartyDocCode(e.target.value as PartyDocCode);
                    }}
                    disabled={isReadOnly}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <option value="PARTY_INVOICE">Dealer Sales / Tax Invoice</option>
                    <option value="PARTY_DEBIT_NOTE">Dealer Debit Note</option>
                    <option value="PARTY_NO_DOC">No Supporting Document</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="party-doc-no-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Party Document No
                  </label>
                  <input
                    id="party-doc-no-input"
                    type="text"
                    value={partyDocNo}
                    onChange={(e) => {
                      setPartyDocNo(e.target.value);
                    }}
                    disabled={isReadOnly}
                    placeholder="e.g. INV-2026-88"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="party-doc-date-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Document Date
                  </label>
                  <input
                    id="party-doc-date-input"
                    type="date"
                    value={partyDocDate}
                    onChange={(e) => {
                      setPartyDocDate(e.target.value);
                    }}
                    disabled={isReadOnly}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="party-doc-amount-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Document Amount (₹)
                  </label>
                  <input
                    id="party-doc-amount-input"
                    type="number"
                    step="0.01"
                    min="0"
                    value={partyDocAmount}
                    onChange={(e) => {
                      setPartyDocAmount(e.target.value ? parseFloat(e.target.value) : '');
                    }}
                    disabled={isReadOnly}
                    placeholder="e.g. 15000.00"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>
              </div>

              {!isReadOnly && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  {partyDocSuccess && (
                    <span
                      style={{
                        color: '#16a34a',
                        fontSize: '0.75rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                      }}
                    >
                      <CheckCircle2 size={14} /> Saved
                    </span>
                  )}
                  <Button type="submit" variant="outline" size="sm" disabled={savingPartyDoc}>
                    <Save size={14} style={{ marginRight: '0.25rem' }} />
                    {savingPartyDoc ? 'Saving...' : 'Save Party Document'}
                  </Button>
                </div>
              )}
            </form>
          </div>

          {/* Card 2: GST Portal Verification */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    backgroundColor: '#2a47f0',
                    color: '#ffffff',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.75rem',
                    fontWeight: 700,
                  }}
                >
                  2
                </span>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                  GST Portal Verification
                </h3>
              </div>
              {cn.gst_portal_code && (
                <Badge variant={cn.gst_portal_code === 'GST_REFLECTED' ? 'success' : 'danger'}>
                  {cn.gst_portal_label}
                </Badge>
              )}
            </div>

            <form onSubmit={(e) => void handleSaveGstCheck(e)}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '1rem',
                  marginBottom: '1rem',
                }}
              >
                <div>
                  <label
                    htmlFor="gst-portal-code-select"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    GST Portal Status
                  </label>
                  <select
                    id="gst-portal-code-select"
                    value={gstPortalCode}
                    onChange={(e) => {
                      setGstPortalCode(e.target.value as GstPortalCode);
                    }}
                    disabled={isReadOnly}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <option value="GST_REFLECTED">
                      GST_REFLECTED (Reflected in GSTR-1/GSTR-2B)
                    </option>
                    <option value="GST_NOT_REFLECTED">
                      GST_NOT_REFLECTED (Strict: JV_ONLY forced)
                    </option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="gst-return-type-select"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Return Type
                  </label>
                  <select
                    id="gst-return-type-select"
                    value={gstReturnType}
                    onChange={(e) => {
                      setGstReturnType(e.target.value as GstReturnType);
                    }}
                    disabled={isReadOnly}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <option value="GSTR-1">GSTR-1 (Outward Supplies)</option>
                    <option value="GSTR-2B">GSTR-2B (Auto-drafted ITC)</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="gst-period-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Return Period (MMYYYY)
                  </label>
                  <input
                    id="gst-period-input"
                    type="text"
                    value={gstPeriod}
                    onChange={(e) => {
                      setGstPeriod(e.target.value);
                    }}
                    disabled={isReadOnly}
                    placeholder="e.g. 102026"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="gst-checked-on-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#475569',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Verification Date
                  </label>
                  <input
                    id="gst-checked-on-input"
                    type="date"
                    value={gstCheckedOn}
                    onChange={(e) => {
                      setGstCheckedOn(e.target.value);
                    }}
                    disabled={isReadOnly}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>
              </div>

              {!isReadOnly && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  {gstSuccess && (
                    <span
                      style={{
                        color: '#16a34a',
                        fontSize: '0.75rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                      }}
                    >
                      <CheckCircle2 size={14} /> Saved
                    </span>
                  )}
                  <Button type="submit" variant="outline" size="sm" disabled={savingGst}>
                    <Save size={14} style={{ marginRight: '0.25rem' }} />
                    {savingGst ? 'Saving...' : 'Save GST Check'}
                  </Button>
                </div>
              )}
            </form>
          </div>

          {/* Card 3: CN Type Selection */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                marginBottom: '0.75rem',
              }}
            >
              <span
                style={{
                  backgroundColor: '#2a47f0',
                  color: '#ffffff',
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                }}
              >
                3
              </span>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                Credit Note Type & Compliance
              </h3>
            </div>

            {typeError && (
              <div
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  marginBottom: '0.75rem',
                  fontSize: '0.75rem',
                }}
              >
                {typeError}
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <button
                type="button"
                disabled={isReadOnly || savingType}
                onClick={() => void handleUpdateType('GST_CN')}
                style={{
                  padding: '0.6rem 1rem',
                  borderRadius: '6px',
                  border: cn.cn_type_code === 'GST_CN' ? '2px solid #0369a1' : '1px solid #cbd5e1',
                  backgroundColor: cn.cn_type_code === 'GST_CN' ? '#e0f2fe' : '#ffffff',
                  color: cn.cn_type_code === 'GST_CN' ? '#0369a1' : '#334155',
                  fontWeight: 600,
                  fontSize: '0.8125rem',
                  cursor: isReadOnly ? 'default' : 'pointer',
                  textAlign: 'left',
                }}
              >
                <div>GST Credit Note</div>
                <div
                  style={{
                    fontSize: '0.6875rem',
                    fontWeight: 400,
                    marginTop: '2px',
                    color: '#64748b',
                  }}
                >
                  Requires GST_REFLECTED + Good stock
                </div>
              </button>

              <button
                type="button"
                disabled={isReadOnly || savingType}
                onClick={() => void handleUpdateType('GENERAL_CN')}
                style={{
                  padding: '0.6rem 1rem',
                  borderRadius: '6px',
                  border:
                    cn.cn_type_code === 'GENERAL_CN' ? '2px solid #b45309' : '1px solid #cbd5e1',
                  backgroundColor: cn.cn_type_code === 'GENERAL_CN' ? '#fef3c7' : '#ffffff',
                  color: cn.cn_type_code === 'GENERAL_CN' ? '#b45309' : '#334155',
                  fontWeight: 600,
                  fontSize: '0.8125rem',
                  cursor: isReadOnly ? 'default' : 'pointer',
                  textAlign: 'left',
                }}
              >
                <div>General / Commercial CN</div>
                <div
                  style={{
                    fontSize: '0.6875rem',
                    fontWeight: 400,
                    marginTop: '2px',
                    color: '#64748b',
                  }}
                >
                  For Repaired units (No GST refund)
                </div>
              </button>

              <button
                type="button"
                disabled={isReadOnly || savingType}
                onClick={() => void handleUpdateType('JV_ONLY')}
                style={{
                  padding: '0.6rem 1rem',
                  borderRadius: '6px',
                  border: cn.cn_type_code === 'JV_ONLY' ? '2px solid #7e22ce' : '1px solid #cbd5e1',
                  backgroundColor: cn.cn_type_code === 'JV_ONLY' ? '#f3e8ff' : '#ffffff',
                  color: cn.cn_type_code === 'JV_ONLY' ? '#7e22ce' : '#334155',
                  fontWeight: 600,
                  fontSize: '0.8125rem',
                  cursor: isReadOnly ? 'default' : 'pointer',
                  textAlign: 'left',
                }}
              >
                <div>Journal Voucher (JV Only)</div>
                <div
                  style={{
                    fontSize: '0.6875rem',
                    fontWeight: 400,
                    marginTop: '2px',
                    color: '#64748b',
                  }}
                >
                  For returns NOT reflected on portal
                </div>
              </button>
            </div>
          </div>

          {/* Card 4: Rate Verification per Line (G-14, DEC-24) */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '0.75rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    backgroundColor: '#2a47f0',
                    color: '#ffffff',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.75rem',
                    fontWeight: 700,
                  }}
                >
                  4
                </span>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                  Commercial Rate Verification & Valuation
                </h3>
              </div>
            </div>

            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '0.8125rem',
                marginBottom: '1rem',
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
                  <th style={{ padding: '0.5rem 0.75rem' }}>#</th>
                  <th style={{ padding: '0.5rem 0.75rem' }}>Product</th>
                  <th style={{ padding: '0.5rem 0.75rem', textAlign: 'center' }}>Qty</th>
                  <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>Verified Rate</th>
                  <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>Taxable Amt</th>
                  <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>Total Amt</th>
                  <th style={{ padding: '0.5rem 0.75rem', textAlign: 'center' }}>Rate Status</th>
                  {!isReadOnly && (
                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>Action</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {cn.lines.map((line) => (
                  <tr key={line.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.5rem 0.75rem' }}>{line.line_no}</td>
                    <td style={{ padding: '0.5rem 0.75rem' }}>
                      <div style={{ fontWeight: 600, color: '#0f172a' }}>{line.product_name}</div>
                      <div style={{ fontSize: '0.6875rem', color: '#64748b' }}>
                        {line.product_code} {line.condition_class && `• ${line.condition_class}`}
                      </div>
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', textAlign: 'center', fontWeight: 600 }}>
                      {line.qty}
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>
                      ₹{toNum(line.rate).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>
                      ₹
                      {toNum(line.taxable_amount).toLocaleString('en-IN', {
                        minimumFractionDigits: 2,
                      })}
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right', fontWeight: 600 }}>
                      ₹
                      {toNum(line.total_amount).toLocaleString('en-IN', {
                        minimumFractionDigits: 2,
                      })}
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', textAlign: 'center' }}>
                      {line.is_rate_verified ? (
                        <span style={{ color: '#16a34a', fontWeight: 600, fontSize: '0.75rem' }}>
                          ✓ Verified
                        </span>
                      ) : (
                        <span style={{ color: '#dc2626', fontWeight: 600, fontSize: '0.75rem' }}>
                          ⚠ Pending
                        </span>
                      )}
                    </td>
                    {!isReadOnly && (
                      <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            handleOpenRateModal(line.id);
                          }}
                        >
                          Verify Rate
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Valuation Summary Box */}
            <div
              style={{
                backgroundColor: '#f8fafc',
                padding: '1rem',
                borderRadius: '8px',
                border: '1px solid #e2e8f0',
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.75rem',
                fontSize: '0.8125rem',
              }}
            >
              <div>
                <span style={{ color: '#64748b' }}>Taxable Value:</span>
                <div style={{ fontWeight: 700, fontSize: '1rem', color: '#0f172a' }}>
                  ₹{toNum(cn.taxable_value).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>CGST / SGST:</span>
                <div style={{ fontWeight: 600, color: '#334155' }}>
                  ₹
                  {(toNum(cn.cgst_amount) + toNum(cn.sgst_amount)).toLocaleString('en-IN', {
                    minimumFractionDigits: 2,
                  })}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>IGST:</span>
                <div style={{ fontWeight: 600, color: '#334155' }}>
                  ₹{toNum(cn.igst_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Total Credit Note Value:</span>
                <div style={{ fontWeight: 700, fontSize: '1.125rem', color: '#16a34a' }}>
                  ₹{toNum(cn.total_value).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>
          </div>

          {/* Card 5: Issue Credit Note (DEC-22, G-14) */}
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '1.25rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              border: '1px solid #e2e8f0',
            }}
          >
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}
            >
              <span
                style={{
                  backgroundColor: '#2a47f0',
                  color: '#ffffff',
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                }}
              >
                5
              </span>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
                {isJv ? 'Journal Voucher Issue' : 'Credit Note Voucher Issue'}
              </h3>
            </div>

            {isIssued ? (
              <div
                style={{
                  backgroundColor: '#f0fdf4',
                  border: '1px solid #bbf7d0',
                  color: '#166534',
                  padding: '1rem',
                  borderRadius: '8px',
                  fontSize: '0.875rem',
                }}
              >
                <div style={{ fontWeight: 600 }}>Voucher Officially Issued</div>
                <div style={{ marginTop: '0.25rem' }}>
                  Number: <strong>{cn.cn_no || cn.jv_no}</strong> | Date:{' '}
                  <strong>{cn.cn_date || cn.jv_date}</strong>
                </div>
                <div style={{ fontSize: '0.75rem', color: '#15803d', marginTop: '0.25rem' }}>
                  Issued by {cn.issued_by_name} on{' '}
                  {cn.issued_at && new Date(cn.issued_at).toLocaleString()}
                </div>
              </div>
            ) : isCancelled ? (
              <div
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                  padding: '1rem',
                  borderRadius: '8px',
                  fontSize: '0.875rem',
                }}
              >
                <div style={{ fontWeight: 600 }}>Credit Note Cancelled</div>
                <div style={{ marginTop: '0.25rem' }}>Reason: {cn.cancel_reason}</div>
              </div>
            ) : (
              <form onSubmit={(e) => void handleIssueVoucher(e)}>
                {issueError && (
                  <div
                    style={{
                      backgroundColor: '#fef2f2',
                      border: '1px solid #fecaca',
                      color: '#991b1b',
                      padding: '0.5rem 0.75rem',
                      borderRadius: '6px',
                      marginBottom: '0.75rem',
                      fontSize: '0.75rem',
                    }}
                  >
                    {issueError}
                  </div>
                )}

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '1rem',
                    marginBottom: '1.25rem',
                  }}
                >
                  <div>
                    <label
                      htmlFor="issue-voucher-no-input"
                      style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: '#475569',
                        marginBottom: '0.25rem',
                      }}
                    >
                      {isJv ? 'Accounting JV Number' : 'Accounting CN Number'}
                    </label>
                    <input
                      id="issue-voucher-no-input"
                      type="text"
                      required
                      value={voucherNo}
                      onChange={(e) => {
                        setVoucherNo(e.target.value);
                      }}
                      placeholder={isJv ? 'e.g. JV-2026-001' : 'e.g. CN-2026-001'}
                      style={{
                        width: '100%',
                        padding: '0.5rem',
                        borderRadius: '6px',
                        border: '1px solid #cbd5e1',
                        fontSize: '0.875rem',
                      }}
                    />
                    <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>
                      Entered directly from external accounting software (e.g. Tally).
                    </span>
                  </div>

                  <div>
                    <label
                      htmlFor="issue-voucher-date-input"
                      style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: '#475569',
                        marginBottom: '0.25rem',
                      }}
                    >
                      Voucher Date
                    </label>
                    <input
                      id="issue-voucher-date-input"
                      type="date"
                      required
                      value={voucherDate}
                      onChange={(e) => {
                        setVoucherDate(e.target.value);
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

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={
                      issuing || !voucherNo.trim() || cn.lines.some((l) => !l.is_rate_verified)
                    }
                  >
                    <Send size={14} style={{ marginRight: '0.25rem' }} />
                    {issuing ? 'Issuing...' : isJv ? 'Issue Journal Voucher' : 'Issue Credit Note'}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>

      {/* Modal: Rate Verification */}
      {rateModalLineId && (
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
              maxWidth: '480px',
              width: '100%',
              padding: '1.5rem',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
            }}
          >
            <h3
              style={{
                fontSize: '1.125rem',
                fontWeight: 700,
                margin: '0 0 0.5rem 0',
                color: '#0f172a',
              }}
            >
              Record Rate Verification
            </h3>
            <p style={{ margin: '0 0 1rem 0', color: '#64748b', fontSize: '0.8125rem' }}>
              Sales rate determines the Credit Note line valuation. Purchase rate provides baseline
              for variance check.
            </p>

            {rateModalError && (
              <div
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  marginBottom: '0.75rem',
                  fontSize: '0.75rem',
                }}
              >
                {rateModalError}
              </div>
            )}

            {rateWarning && (
              <div
                style={{
                  backgroundColor: '#fffbeb',
                  border: '1px solid #fde68a',
                  color: '#b45309',
                  padding: '0.75rem',
                  borderRadius: '6px',
                  marginBottom: '1rem',
                  fontSize: '0.8125rem',
                  display: 'flex',
                  gap: '0.5rem',
                  alignItems: 'flex-start',
                }}
              >
                <ShieldAlert size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <div style={{ fontWeight: 600 }}>Variance Warning</div>
                  <div>{rateWarning}</div>
                </div>
              </div>
            )}

            <form onSubmit={(e) => void handleSaveRate(e)}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <div>
                  <label
                    htmlFor="rate-ref-code-select"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Rate Reference Code
                  </label>
                  <select
                    id="rate-ref-code-select"
                    value={rateRefCode}
                    onChange={(e) => {
                      setRateRefCode(e.target.value as RateReferenceCode);
                    }}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <option value="RATE_SALES">Verified Sales Invoice Rate</option>
                    <option value="RATE_PURCHASE">Purchase Invoice Rate (Variance Baseline)</option>
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="rate-doc-no-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Reference Document No
                  </label>
                  <input
                    id="rate-doc-no-input"
                    type="text"
                    required
                    value={rateDocNo}
                    onChange={(e) => {
                      setRateDocNo(e.target.value);
                    }}
                    placeholder="e.g. INV-2025-992 or PO-441"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="rate-doc-date-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Reference Document Date
                  </label>
                  <input
                    id="rate-doc-date-input"
                    type="date"
                    required
                    value={rateDocDate}
                    onChange={(e) => {
                      setRateDocDate(e.target.value);
                    }}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="rate-val-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Rate per Unit (₹)
                  </label>
                  <input
                    id="rate-val-input"
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={rateVal}
                    onChange={(e) => {
                      setRateVal(e.target.value ? parseFloat(e.target.value) : '');
                    }}
                    placeholder="e.g. 1250.00"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>

                <div>
                  <label
                    htmlFor="rate-notes-input"
                    style={{
                      display: 'block',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#334155',
                      marginBottom: '0.25rem',
                    }}
                  >
                    Notes / Remarks
                  </label>
                  <input
                    id="rate-notes-input"
                    type="text"
                    value={rateNotes}
                    onChange={(e) => {
                      setRateNotes(e.target.value);
                    }}
                    placeholder="e.g. Verified against dealer tax invoice"
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      borderRadius: '6px',
                      border: '1px solid #cbd5e1',
                      fontSize: '0.8125rem',
                    }}
                  />
                </div>
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '0.75rem',
                  marginTop: '1.25rem',
                }}
              >
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setRateModalLineId(null);
                  }}
                  disabled={savingRate}
                >
                  Close
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={savingRate || typeof rateVal !== 'number' || rateVal <= 0}
                >
                  {savingRate ? 'Saving...' : 'Record Rate'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Cancel Credit Note */}
      {isCancelModalOpen && (
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
              maxWidth: '440px',
              width: '100%',
              padding: '1.5rem',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
            }}
          >
            <h3
              style={{
                fontSize: '1.125rem',
                fontWeight: 700,
                margin: '0 0 0.5rem 0',
                color: '#991b1b',
              }}
            >
              Cancel Credit Note
            </h3>
            <p style={{ margin: '0 0 1rem 0', color: '#64748b', fontSize: '0.8125rem' }}>
              Cancelling will release the credited quantities back to the Goods Slip allowed
              balance. Reason is mandatory.
            </p>

            {cancelError && (
              <div
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  color: '#991b1b',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  marginBottom: '0.75rem',
                  fontSize: '0.75rem',
                }}
              >
                {cancelError}
              </div>
            )}

            <form onSubmit={(e) => void handleCancelCn(e)}>
              <div>
                <label
                  htmlFor="cancel-reason-input"
                  style={{
                    display: 'block',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: '#334155',
                    marginBottom: '0.25rem',
                  }}
                >
                  Reason for Cancellation
                </label>
                <textarea
                  id="cancel-reason-input"
                  required
                  rows={3}
                  value={cancelReason}
                  onChange={(e) => {
                    setCancelReason(e.target.value);
                  }}
                  placeholder="Explain why this credit note is being cancelled..."
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.8125rem',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '0.75rem',
                  marginTop: '1.25rem',
                }}
              >
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setIsCancelModalOpen(false);
                  }}
                  disabled={cancelling}
                >
                  Close
                </Button>
                <Button
                  type="submit"
                  variant="danger"
                  disabled={cancelling || !cancelReason.trim()}
                >
                  {cancelling ? 'Cancelling...' : 'Confirm Cancellation'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
