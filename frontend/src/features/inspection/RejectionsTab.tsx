import React from 'react';
import { ShieldAlert, AlertTriangle } from 'lucide-react';
import type { InspectionGsOut } from './types';

interface RejectionsTabProps {
  data: InspectionGsOut | null;
  loading: boolean;
}

export const RejectionsTab: React.FC<RejectionsTabProps> = ({ data, loading }) => {
  if (loading && !data) {
    return <div style={{ padding: '1rem', color: '#64748b' }}>Loading rejections...</div>;
  }

  if (!data) {
    return null;
  }

  // Flatten all rejections across all lines with line metadata
  const allRejections = data.lines.flatMap((line) =>
    line.rejections.map((rej) => ({
      ...rej,
      line_no: line.line_no,
      product_code: line.product_code,
      product_name: line.product_name,
      category_code: line.category_code,
    })),
  );

  if (allRejections.length === 0) {
    return (
      <div
        style={{
          padding: '2rem',
          textAlign: 'center',
          backgroundColor: '#f8fafc',
          borderRadius: '6px',
          border: '1px dashed #cbd5e1',
          color: '#64748b',
        }}
      >
        <p style={{ margin: 0, fontWeight: 600 }}>No rejections recorded for this Goods Slip.</p>
        <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.85rem' }}>
          All inspected pieces were accepted under allowed conditions, or inspection is not yet
          finalised.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
          Total Segregated Rejections: <strong>{data.totals.total_rejected_qty} pieces</strong>{' '}
          across {allRejections.length} entries
        </span>
      </div>

      <div className="table-responsive">
        <table className="table" style={{ width: '100%', fontSize: '0.85rem' }}>
          <thead>
            <tr>
              <th>Line</th>
              <th>Product</th>
              <th>Condition Code</th>
              <th>Qty (pcs)</th>
              <th>Disposition & Routing</th>
              <th>Classification</th>
              <th>Ledger Movement ID</th>
            </tr>
          </thead>
          <tbody>
            {allRejections.map((rej) => (
              <tr key={rej.id}>
                <td>
                  <strong>{rej.line_no}</strong>
                </td>
                <td>
                  <div>
                    <strong>{rej.product_code}</strong>
                  </div>
                  <div style={{ color: '#64748b', fontSize: '0.75rem' }}>{rej.product_name}</div>
                </td>
                <td>
                  <span style={{ fontWeight: 600 }}>{rej.condition_code}</span>
                </td>
                <td>
                  <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{rej.qty}</span>
                </td>
                <td>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      backgroundColor: '#f1f5f9',
                      fontWeight: 600,
                      fontSize: '0.8rem',
                    }}
                  >
                    {rej.disposition}
                  </span>
                </td>
                <td>
                  {rej.hazard ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        backgroundColor: '#fef2f2',
                        color: '#dc2626',
                        border: '1px solid #fecaca',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                      }}
                    >
                      <ShieldAlert size={14} aria-hidden="true" /> HAZARD
                    </span>
                  ) : (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        backgroundColor: '#fffbeb',
                        color: '#d97706',
                        border: '1px solid #fde68a',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                      }}
                    >
                      <AlertTriangle size={14} aria-hidden="true" /> NOT_ALLOWED
                    </span>
                  )}
                </td>
                <td>
                  {rej.stock_movement_id ? (
                    <code style={{ fontSize: '0.75rem', color: '#475569' }}>
                      {rej.stock_movement_id.slice(0, 8)}...
                    </code>
                  ) : (
                    <span style={{ color: '#94a3b8' }}>&mdash;</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
