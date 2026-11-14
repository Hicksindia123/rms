import { useCallback } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

import { Button, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { rmActionsApi } from './api';
import type { ReplacementSlipLine, ReplacementSlipResponse, SignatureBlock } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
}

export function ReplacementSlipPrintPage({ gsId, onBack }: Props) {
  const fetcher = useCallback(() => rmActionsApi.getReplacementSlip(gsId), [gsId]);
  const query = useApiQuery<ReplacementSlipResponse>(fetcher);
  const slip = query.data?.gs_id === gsId ? query.data : null;
  const error = query.error;
  const load = query.reload;

  const toolbar = (
    <div
      className="no-print"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '0.75rem',
        marginBottom: '1.25rem',
        flexWrap: 'wrap',
      }}
    >
      <Button type="button" variant="ghost" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" /> Back to Goods Slip
      </Button>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {slip?.is_reprint ? (
          <span
            style={{
              fontSize: '0.8125rem',
              fontWeight: 600,
              color: '#b45309',
              backgroundColor: '#fef3c7',
              padding: '0.25rem 0.5rem',
              borderRadius: '4px',
            }}
          >
            Reprint #{slip.print_count}
          </span>
        ) : null}
        <Button
          type="button"
          variant="primary"
          onClick={() => {
            window.print();
          }}
        >
          <Printer size={16} aria-hidden="true" /> Print / Save as PDF
        </Button>
      </div>
    </div>
  );

  if (error) {
    return (
      <div className="page">
        {toolbar}
        <ErrorState error={error} onRetry={load} title="Could not load Replacement Slip" />
      </div>
    );
  }

  if (!slip) {
    return (
      <div className="page">
        {toolbar}
        <LoadingState label="Preparing Replacement Slip…" />
      </div>
    );
  }

  // Header text comes from the published REPLACEMENT_SLIP print template (rule e, P1-08).
  const headerTitle = typeof slip.layout.header_title === 'string' ? slip.layout.header_title : '';
  const headerSubtitle =
    typeof slip.layout.header_subtitle === 'string' ? slip.layout.header_subtitle : '';

  return (
    <div className="page">
      {toolbar}

      {/* Printable Sheet (A4 portrait) */}
      <div
        className="replacement-slip-sheet"
        style={{
          position: 'relative',
          backgroundColor: '#ffffff',
          color: '#0f172a',
          padding: '24mm 20mm',
          margin: '0 auto',
          maxWidth: '210mm',
          minHeight: '297mm',
          boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
          border: '1px solid #e2e8f0',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          fontSize: '11pt',
          lineHeight: 1.4,
          boxSizing: 'border-box',
        }}
      >
        {/* Reprint / Revision Watermark */}
        {slip.watermark ? (
          <div
            style={{
              position: 'absolute',
              top: '40%',
              left: '50%',
              transform: 'translate(-50%, -50%) rotate(-30deg)',
              fontSize: '52pt',
              fontWeight: 800,
              color: 'rgba(203, 213, 225, 0.35)',
              pointerEvents: 'none',
              userSelect: 'none',
              letterSpacing: '0.15em',
              whiteSpace: 'nowrap',
              zIndex: 0,
            }}
          >
            {slip.watermark}
          </div>
        ) : null}

        <div style={{ position: 'relative', zIndex: 1 }}>
          {/* Header */}
          <header
            style={{
              textAlign: 'center',
              borderBottom: '2px solid #0f172a',
              paddingBottom: '0.75rem',
              marginBottom: '1.25rem',
            }}
          >
            <h1
              style={{
                margin: 0,
                fontSize: '18pt',
                fontWeight: 800,
                letterSpacing: '0.02em',
                textTransform: 'uppercase',
              }}
            >
              {headerTitle}
            </h1>
            <p
              style={{
                margin: '0.25rem 0 0 0',
                fontSize: '13pt',
                fontWeight: 700,
                color: '#334155',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {headerSubtitle}
            </p>
          </header>

          {/* Metadata Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '0.5rem 1.5rem',
              border: '1px solid #cbd5e1',
              borderRadius: '4px',
              padding: '0.75rem 1rem',
              marginBottom: '1.25rem',
              backgroundColor: '#f8fafc',
              fontSize: '10pt',
            }}
          >
            <div>
              <strong>Goods Slip No:</strong>{' '}
              <span style={{ fontFamily: 'monospace', fontWeight: 700 }}>{slip.gs_no}</span>
            </div>
            <div>
              <strong>Date:</strong> {slip.date}
            </div>
            <div>
              <strong>Party:</strong> {slip.party_name}{' '}
              {slip.party_code ? `(${slip.party_code})` : ''}
            </div>
            <div>
              <strong>Revision No:</strong> #{slip.revision_no}
            </div>
            <div>
              <strong>Station / State:</strong>{' '}
              {[slip.station_name, slip.state_name].filter(Boolean).join(', ') || '—'}
            </div>
            <div>
              <strong>RM Officer:</strong> {slip.rm_name}
            </div>
            <div>
              <strong>Prepared By:</strong> {slip.prepared_by}
            </div>
            <div>
              <strong>Print Status:</strong>{' '}
              {slip.print_count > 1 ? `Reprint (Count: ${String(slip.print_count)})` : 'Original'}
            </div>
          </div>

          {/* Items Table */}
          <div style={{ overflowX: 'auto', marginBottom: '1.5rem' }}>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '9.5pt',
                textAlign: 'left',
              }}
            >
              <thead>
                <tr style={{ backgroundColor: '#0f172a', color: '#ffffff' }}>
                  <th style={{ padding: '6px 8px', border: '1px solid #0f172a', width: '32px' }}>
                    #
                  </th>
                  <th style={{ padding: '6px 8px', border: '1px solid #0f172a' }}>
                    Item Description
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '45px',
                    }}
                  >
                    Recv
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '50px',
                    }}
                  >
                    Send New
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '50px',
                    }}
                  >
                    Send Rep
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '50px',
                    }}
                  >
                    CN
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '50px',
                    }}
                  >
                    Not Allw
                  </th>
                  <th
                    style={{
                      padding: '6px 8px',
                      border: '1px solid #0f172a',
                      textAlign: 'right',
                      width: '50px',
                    }}
                  >
                    Pending
                  </th>
                  <th style={{ padding: '6px 8px', border: '1px solid #0f172a', width: '90px' }}>
                    Rejections
                  </th>
                </tr>
              </thead>
              <tbody>
                {slip.lines.map((line: ReplacementSlipLine) => (
                  <tr key={line.line_no} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'center',
                      }}
                    >
                      {line.line_no}
                    </td>
                    <td style={{ padding: '6px 8px', border: '1px solid #cbd5e1' }}>
                      <div style={{ fontWeight: 600 }}>{line.product_name}</div>
                      <div style={{ fontSize: '8pt', color: '#64748b', fontFamily: 'monospace' }}>
                        {line.product_code}
                      </div>
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        fontWeight: 600,
                      }}
                    >
                      {line.received_qty}
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        color: line.send_new_qty ? '#15803d' : '#94a3b8',
                      }}
                    >
                      {line.send_new_qty || '-'}
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        color: line.send_repaired_qty ? '#0369a1' : '#94a3b8',
                      }}
                    >
                      {line.send_repaired_qty || '-'}
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        color: line.issue_cn_qty ? '#d97706' : '#94a3b8',
                      }}
                    >
                      {line.issue_cn_qty || '-'}
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        color: line.not_allowed_qty ? '#b91c1c' : '#94a3b8',
                        fontWeight: line.not_allowed_qty ? 600 : 400,
                      }}
                    >
                      {line.not_allowed_qty || '-'}
                    </td>
                    <td
                      style={{
                        padding: '6px 8px',
                        border: '1px solid #cbd5e1',
                        textAlign: 'right',
                        color: line.pending_bp_qty ? '#7c3aed' : '#94a3b8',
                      }}
                    >
                      {line.pending_bp_qty || '-'}
                    </td>
                    <td
                      style={{ padding: '6px 8px', border: '1px solid #cbd5e1', fontSize: '8pt' }}
                    >
                      {line.rejected_qty > 0 ? (
                        <span style={{ color: '#b91c1c' }}>
                          Qty: {line.rejected_qty}
                          {line.rejection_reasons.length > 0
                            ? ` (${line.rejection_reasons.join(', ')})`
                            : ''}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr
                  style={{
                    backgroundColor: '#f1f5f9',
                    fontWeight: 700,
                    borderTop: '2px solid #0f172a',
                  }}
                >
                  <td
                    colSpan={2}
                    style={{ padding: '8px', border: '1px solid #cbd5e1', textAlign: 'right' }}
                  >
                    Total:
                  </td>
                  <td style={{ padding: '8px', border: '1px solid #cbd5e1', textAlign: 'right' }}>
                    {slip.totals.received_qty ?? 0}
                  </td>
                  <td
                    style={{
                      padding: '8px',
                      border: '1px solid #cbd5e1',
                      textAlign: 'right',
                      color: '#15803d',
                    }}
                  >
                    {slip.totals.send_new_qty ?? 0}
                  </td>
                  <td
                    style={{
                      padding: '8px',
                      border: '1px solid #cbd5e1',
                      textAlign: 'right',
                      color: '#0369a1',
                    }}
                  >
                    {slip.totals.send_repaired_qty ?? 0}
                  </td>
                  <td
                    style={{
                      padding: '8px',
                      border: '1px solid #cbd5e1',
                      textAlign: 'right',
                      color: '#d97706',
                    }}
                  >
                    {slip.totals.issue_cn_qty ?? 0}
                  </td>
                  <td
                    style={{
                      padding: '8px',
                      border: '1px solid #cbd5e1',
                      textAlign: 'right',
                      color: '#b91c1c',
                    }}
                  >
                    {slip.totals.not_allowed_qty ?? 0}
                  </td>
                  <td
                    style={{
                      padding: '8px',
                      border: '1px solid #cbd5e1',
                      textAlign: 'right',
                      color: '#7c3aed',
                    }}
                  >
                    {slip.totals.pending_bp_qty ?? 0}
                  </td>
                  <td style={{ padding: '8px', border: '1px solid #cbd5e1' }} />
                </tr>
              </tfoot>
            </table>
          </div>

          {/* Signatures */}
          <div
            style={{
              marginTop: '3.5rem',
              display: 'grid',
              gridTemplateColumns: `repeat(${String(slip.signature_blocks.length || 3)}, 1fr)`,
              gap: '1.5rem',
              textAlign: 'center',
            }}
          >
            {slip.signature_blocks.map((block: SignatureBlock) => (
              <div
                key={block.role}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                }}
              >
                <div
                  style={{
                    borderTop: '1px dashed #64748b',
                    width: '80%',
                    paddingTop: '0.5rem',
                    minHeight: '40px',
                  }}
                />
                <div style={{ fontWeight: 700, fontSize: '10pt', color: '#0f172a' }}>
                  {block.name || '________________'}
                </div>
                <div
                  style={{
                    fontSize: '8.5pt',
                    color: '#64748b',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  {block.role}
                </div>
              </div>
            ))}
          </div>

          {/* Footer note */}
          <footer
            style={{
              marginTop: '2.5rem',
              paddingTop: '0.75rem',
              borderTop: '1px solid #e2e8f0',
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: '8pt',
              color: '#94a3b8',
            }}
          >
            <span>Computer-generated Replacement Slip (RMS)</span>
            <span>Page 1 of 1</span>
          </footer>
        </div>
      </div>

      <style>{`
        @media print {
          body {
            background-color: #ffffff !important;
            margin: 0 !important;
            padding: 0 !important;
          }
          .no-print, header.no-print, nav {
            display: none !important;
          }
          .app-shell, main, .page {
            padding: 0 !important;
            margin: 0 !important;
            background: none !important;
          }
          .replacement-slip-sheet {
            box-shadow: none !important;
            border: none !important;
            padding: 10mm 15mm !important;
            margin: 0 auto !important;
            width: 100% !important;
            max-width: none !important;
            min-height: auto !important;
          }
        }
      `}</style>
    </div>
  );
}
