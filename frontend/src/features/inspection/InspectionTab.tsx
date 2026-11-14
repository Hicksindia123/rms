import React from 'react';
import { Eye, CheckCircle2, AlertTriangle, AlertOctagon } from 'lucide-react';
import { Button } from '@/components/ui';
import type { InspectionGsOut } from './types';

interface InspectionTabProps {
  data: InspectionGsOut | null;
  loading: boolean;
  onOpenInspectionPage: () => void;
}

export const InspectionTab: React.FC<InspectionTabProps> = ({
  data,
  loading,
  onOpenInspectionPage,
}) => {
  if (loading && !data) {
    return <div style={{ padding: '1rem', color: '#64748b' }}>Loading inspection records...</div>;
  }

  if (!data || data.lines.length === 0) {
    return (
      <div style={{ padding: '1.5rem', textAlign: 'center', color: '#64748b' }}>
        No inspection lines recorded for this Goods Slip yet.
      </div>
    );
  }

  const { totals, lines, has_hazard } = data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
            Inspection Summary: {totals.lines_finalised} / {totals.lines_count} lines finalised
          </span>
          {has_hazard && (
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
              <AlertOctagon size={14} aria-hidden="true" /> Hazard Quarantined
            </span>
          )}
        </div>

        <Button type="button" variant="primary" onClick={onOpenInspectionPage}>
          <Eye size={16} aria-hidden="true" /> Open Inspection Workspace
        </Button>
      </div>

      <div className="table-responsive">
        <table className="table" style={{ width: '100%', fontSize: '0.85rem' }}>
          <thead>
            <tr>
              <th>Line</th>
              <th>Product</th>
              <th>Category</th>
              <th>Received</th>
              <th>Graded Allocations</th>
              <th>Extraction</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const isFinal = line.inspection_status === 'FINAL';
              const activeAllocs = line.allocations.filter((a) => a.qty > 0);
              return (
                <tr key={line.gs_item_id}>
                  <td>
                    <strong>{line.line_no}</strong>
                  </td>
                  <td>
                    <div>
                      <strong>{line.product_code}</strong>
                    </div>
                    <div style={{ color: '#64748b', fontSize: '0.75rem' }}>{line.product_name}</div>
                  </td>
                  <td>
                    <span
                      style={{
                        padding: '1px 6px',
                        borderRadius: '4px',
                        backgroundColor: '#e0f2fe',
                        color: '#0369a1',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                      }}
                    >
                      {line.category_code}
                    </span>
                  </td>
                  <td>{line.received_qty}</td>
                  <td>
                    {activeAllocs.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                        {activeAllocs.map((a) => (
                          <span key={a.condition_code} style={{ fontSize: '0.75rem' }}>
                            &bull; {a.qty} &times; {a.label || a.condition_code}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>Pending</span>
                    )}
                  </td>
                  <td>
                    {line.extraction ? (
                      <span style={{ fontSize: '0.75rem' }}>
                        Pkg: {line.extraction.packaging_qty} / Cnt: {line.extraction.container_qty}
                      </span>
                    ) : (
                      <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>Pending</span>
                    )}
                  </td>
                  <td>
                    {isFinal ? (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                          color: '#15803d',
                          fontWeight: 600,
                        }}
                      >
                        <CheckCircle2 size={14} aria-hidden="true" /> Finalised
                      </span>
                    ) : (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                          color: '#d97706',
                          fontWeight: 600,
                        }}
                      >
                        <AlertTriangle size={14} aria-hidden="true" />{' '}
                        {line.inspection_status || 'Draft'}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
