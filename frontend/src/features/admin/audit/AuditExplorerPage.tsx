import { useState, useEffect, useCallback } from 'react';
import { Download, RefreshCw, Shield, Eye } from 'lucide-react';
import { Button, Input, Badge, EmptyState, LoadingState, Modal } from '@/components/ui';
import { auditApi, type AuditLogRow, type AuditFilterParams } from '@/features/audit/api';
import { formatDateTime } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';

/** Render a diff value: primitives as text, objects/arrays as JSON. */
function formatDiffValue(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  return JSON.stringify(value);
}

export function AuditExplorerPage() {
  const [tables, setTables] = useState<string[]>([]);

  // Filters
  const [selectedTable, setSelectedTable] = useState<string>('');
  const [selectedAction, setSelectedAction] = useState<string>('');
  const [actorId, setActorId] = useState<string>('');
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');
  const [requestId, setRequestId] = useState<string>('');
  const [page, setPage] = useState(0);
  const pageSize = 25;

  // Selected row for diff modal
  const [inspectRow, setInspectRow] = useState<AuditLogRow | null>(null);

  useEffect(() => {
    void auditApi
      .fetchAuditTables()
      .then(setTables)
      .catch(() => {});
  }, []);

  const fetchLog = useCallback(() => {
    const params: AuditFilterParams = {
      table_name: selectedTable || undefined,
      action: selectedAction || undefined,
      actor_id: actorId.trim() || undefined,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
      request_id: requestId.trim() || undefined,
      limit: pageSize,
      offset: page * pageSize,
    };
    return auditApi.fetchAuditLog(params);
  }, [selectedTable, selectedAction, actorId, fromDate, toDate, requestId, page]);

  const { data: logData, error: logError, loading, reload } = useApiQuery(fetchLog);
  const items = logData?.items ?? [];
  const total = logData?.total ?? 0;
  const error = logError
    ? 'Failed to fetch audit log records. Ensure you have audit permissions.'
    : null;

  const handleExportCsv = () => {
    const params: AuditFilterParams = {
      table_name: selectedTable || undefined,
      action: selectedAction || undefined,
      actor_id: actorId.trim() || undefined,
      from_date: fromDate || undefined,
      to_date: toDate || undefined,
      request_id: requestId.trim() || undefined,
    };
    const url = auditApi.getAuditExportUrl(params);
    window.open(url, '_blank');
  };

  const getActionBadge = (action: string) => {
    switch (action) {
      case 'INSERT':
        return <Badge variant="success">INSERT</Badge>;
      case 'UPDATE':
        return <Badge variant="default">UPDATE</Badge>;
      case 'DELETE':
        return <Badge variant="danger">DELETE</Badge>;
      default:
        return <Badge variant="neutral">{action}</Badge>;
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Page Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Shield size={22} color="#4338ca" />
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Audit Explorer
            </h1>
          </div>
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem', color: '#64748b' }}>
            System-wide tamper-evident immutable audit log (BR-40, G-17).
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Button variant="secondary" onClick={reload} disabled={loading}>
            <RefreshCw size={15} style={{ marginRight: '0.35rem' }} /> Refresh
          </Button>
          <Button variant="primary" onClick={handleExportCsv}>
            <Download size={15} style={{ marginRight: '0.35rem' }} /> Export CSV
          </Button>
        </div>
      </div>

      {/* Filter Controls Bar */}
      <div
        style={{
          backgroundColor: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '8px',
          padding: '1rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '0.75rem',
          alignItems: 'end',
        }}
      >
        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            Table Name
          </label>
          <select
            value={selectedTable}
            onChange={(e) => {
              setSelectedTable(e.target.value);
              setPage(0);
            }}
            style={{
              width: '100%',
              height: '36px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              padding: '0 0.5rem',
              fontSize: '0.8125rem',
            }}
          >
            <option value="">All Tables ({tables.length})</option>
            {tables.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            Action
          </label>
          <select
            value={selectedAction}
            onChange={(e) => {
              setSelectedAction(e.target.value);
              setPage(0);
            }}
            style={{
              width: '100%',
              height: '36px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              padding: '0 0.5rem',
              fontSize: '0.8125rem',
            }}
          >
            <option value="">All Actions</option>
            <option value="INSERT">INSERT</option>
            <option value="UPDATE">UPDATE</option>
            <option value="DELETE">DELETE</option>
          </select>
        </div>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            From Date
          </label>
          <Input
            type="date"
            value={fromDate}
            onChange={(e) => {
              setFromDate(e.target.value);
              setPage(0);
            }}
            style={{ height: '36px' }}
          />
        </div>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            To Date
          </label>
          <Input
            type="date"
            value={toDate}
            onChange={(e) => {
              setToDate(e.target.value);
              setPage(0);
            }}
            style={{ height: '36px' }}
          />
        </div>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            Actor ID / Email
          </label>
          <Input
            type="text"
            placeholder="Search actor..."
            value={actorId}
            onChange={(e) => {
              setActorId(e.target.value);
              setPage(0);
            }}
            style={{ height: '36px' }}
          />
        </div>

        <div>
          <label
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#475569',
              marginBottom: '0.25rem',
            }}
          >
            Request ID
          </label>
          <Input
            type="text"
            placeholder="Search req-id..."
            value={requestId}
            onChange={(e) => {
              setRequestId(e.target.value);
              setPage(0);
            }}
            style={{ height: '36px' }}
          />
        </div>
      </div>

      {/* Audit Log Table */}
      {loading && <LoadingState label="Fetching audit logs..." />}
      {error && <div style={{ color: '#dc2626', fontSize: '0.875rem' }}>{error}</div>}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No audit entries matched"
          hint="Adjust table, action, or date filters to widen your search."
        />
      )}

      {!loading && items.length > 0 && (
        <div
          style={{
            backgroundColor: '#fff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
              <thead>
                <tr
                  style={{
                    backgroundColor: '#f8fafc',
                    borderBottom: '1px solid #e2e8f0',
                    color: '#64748b',
                    textAlign: 'left',
                  }}
                >
                  <th style={{ padding: '0.75rem 1rem' }}>Timestamp</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Table</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Action</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Row ID</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Actor</th>
                  <th style={{ padding: '0.75rem 1rem' }}>Diffs</th>
                  <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr
                    key={row.id}
                    style={{
                      borderBottom: '1px solid #f1f5f9',
                      transition: 'background-color 0.1s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = '#f8fafc';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = '#fff';
                    }}
                  >
                    <td style={{ padding: '0.75rem 1rem', color: '#1e293b', whiteSpace: 'nowrap' }}>
                      {formatDateTime(row.at)}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: '#334155' }}>
                      {row.table_name}
                    </td>
                    <td style={{ padding: '0.75rem 1rem' }}>{getActionBadge(row.action)}</td>
                    <td
                      style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', color: '#64748b' }}
                    >
                      {row.row_id.length > 18 ? `${row.row_id.substring(0, 18)}...` : row.row_id}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', color: '#334155' }}>
                      {row.actor_name ||
                        (row.actor_id ? `${row.actor_id.substring(0, 8)}...` : 'System')}
                    </td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      {row.diffs.length > 0 ? (
                        <span style={{ color: '#2563eb', fontWeight: 500 }}>
                          {row.diffs.length} field{row.diffs.length > 1 ? 's' : ''}
                        </span>
                      ) : (
                        <span style={{ color: '#94a3b8' }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setInspectRow(row);
                        }}
                        title="Inspect diff and payload"
                      >
                        <Eye size={14} style={{ marginRight: '0.25rem' }} /> View
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div
            style={{
              padding: '0.75rem 1rem',
              backgroundColor: '#f8fafc',
              borderTop: '1px solid #e2e8f0',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: '0.8125rem',
              color: '#64748b',
            }}
          >
            <span>
              Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} of {total}{' '}
              entries
            </span>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <Button
                size="sm"
                variant="secondary"
                disabled={page === 0}
                onClick={() => {
                  setPage((p) => Math.max(0, p - 1));
                }}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={page + 1 >= totalPages}
                onClick={() => {
                  setPage((p) => p + 1);
                }}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Row Inspection Modal */}
      {inspectRow && (
        <Modal
          isOpen={true}
          onClose={() => {
            setInspectRow(null);
          }}
          title={`Audit Entry: ${inspectRow.table_name} (${inspectRow.action})`}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '0.5rem',
                backgroundColor: '#f8fafc',
                padding: '0.75rem',
                borderRadius: '6px',
                fontSize: '0.8125rem',
              }}
            >
              <div>
                <strong>Timestamp:</strong> {formatDateTime(inspectRow.at)}
              </div>
              <div>
                <strong>Action:</strong> {inspectRow.action}
              </div>
              <div>
                <strong>Table:</strong> {inspectRow.table_name}
              </div>
              <div>
                <strong>Row ID:</strong> {inspectRow.row_id}
              </div>
              <div>
                <strong>Actor:</strong> {inspectRow.actor_name || inspectRow.actor_id || 'System'}
              </div>
              <div>
                <strong>Request ID:</strong> {inspectRow.request_id || '—'}
              </div>
            </div>

            {inspectRow.diffs.length > 0 && (
              <div>
                <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.875rem', fontWeight: 600 }}>
                  Field Diffs
                </h4>
                <table style={{ width: '100%', fontSize: '0.8125rem', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr
                      style={{
                        textAlign: 'left',
                        borderBottom: '1px solid #e2e8f0',
                        color: '#64748b',
                      }}
                    >
                      <th style={{ padding: '0.35rem 0.5rem' }}>Field</th>
                      <th style={{ padding: '0.35rem 0.5rem' }}>Old Value</th>
                      <th style={{ padding: '0.35rem 0.5rem' }}>New Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspectRow.diffs.map((d, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td
                          style={{ padding: '0.35rem 0.5rem', fontWeight: 500, color: '#1e293b' }}
                        >
                          {d.field_label || d.field}
                        </td>
                        <td style={{ padding: '0.35rem 0.5rem', color: '#dc2626' }}>
                          {formatDiffValue(d.old_value)}
                        </td>
                        <td style={{ padding: '0.35rem 0.5rem', color: '#16a34a' }}>
                          {formatDiffValue(d.new_value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div>
              <h4 style={{ margin: '0 0 0.25rem', fontSize: '0.875rem', fontWeight: 600 }}>
                Raw Payload
              </h4>
              <div
                style={{
                  maxHeight: '200px',
                  overflowY: 'auto',
                  backgroundColor: '#0f172a',
                  color: '#f8fafc',
                  padding: '0.75rem',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '0.75rem',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {JSON.stringify(
                  {
                    old_values: inspectRow.old_values,
                    new_values: inspectRow.new_values,
                  },
                  null,
                  2,
                )}
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
              <Button
                variant="secondary"
                onClick={() => {
                  setInspectRow(null);
                }}
              >
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
