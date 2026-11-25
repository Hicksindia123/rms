import { Fragment, useEffect, useState } from 'react';
import { History, Filter, ChevronRight, ChevronDown } from 'lucide-react';

export interface ConfigChangeLogItem {
  id: number;
  entity_type: string;
  entity_id: string | null;
  action: string;
  before: unknown;
  after: unknown;
  reason: string | null;
  actor_email: string | null;
  actor_name: string | null;
  changed_at: string;
}

export function ConfigHistoryViewer() {
  const [items, setItems] = useState<ConfigChangeLogItem[]>([]);
  const [entityFilter, setEntityFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    async function loadHistory() {
      try {
        setLoading(true);
        let url = '/api/v1/config/history?page=1&page_size=50';
        if (entityFilter) {
          url += `&entity_type=${encodeURIComponent(entityFilter)}`;
        }
        const res = await fetch(url);
        if (res.ok) {
          const data = (await res.json()) as { items: ConfigChangeLogItem[]; total: number };
          setItems(data.items);
        }
      } finally {
        setLoading(false);
      }
    }
    void loadHistory();
  }, [entityFilter]);

  return (
    <div
      style={{
        maxWidth: '1200px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem',
      }}
    >
      {/* Top Banner */}
      <div
        style={{
          backgroundColor: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: '8px',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '8px',
              backgroundColor: '#e0f2fe',
              color: '#0284c7',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <History size={22} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Configuration Change History & Audit Trail
            </h2>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Insert-only audit trail. Every change to workflows, forms, option sets, number series,
              settings, and templates is tracked with attribution and before/after diffs.
            </p>
          </div>
        </div>

        {/* Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Filter size={16} color="#64748b" />
          <select
            value={entityFilter}
            onChange={(e) => {
              setEntityFilter(e.target.value);
            }}
            style={{
              padding: '0.4rem 0.75rem',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              fontSize: '0.875rem',
              backgroundColor: '#ffffff',
            }}
          >
            <option value="">All Entity Types</option>
            <option value="workflow_version">Workflow Versions</option>
            <option value="form_version">Form Versions</option>
            <option value="option_item">Option Items</option>
            <option value="number_series">Number Series</option>
            <option value="system_setting">System Settings</option>
            <option value="print_template">Print Templates</option>
          </select>
        </div>
      </div>

      {loading && (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
          Loading change log...
        </div>
      )}

      {!loading && items.length === 0 && (
        <div
          style={{
            padding: '3rem',
            textAlign: 'center',
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            color: '#64748b',
          }}
        >
          No configuration change logs found for this filter.
        </div>
      )}

      {!loading && items.length > 0 && (
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            overflow: 'hidden',
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
            <thead
              style={{
                backgroundColor: '#f8fafc',
                borderBottom: '1px solid #e2e8f0',
                color: '#475569',
              }}
            >
              <tr>
                <th style={{ padding: '0.75rem 1rem', width: '40px' }} />
                <th style={{ padding: '0.75rem 1rem' }}>Timestamp</th>
                <th style={{ padding: '0.75rem 1rem' }}>Entity</th>
                <th style={{ padding: '0.75rem 1rem' }}>Action</th>
                <th style={{ padding: '0.75rem 1rem' }}>Reason / Version Notes</th>
                <th style={{ padding: '0.75rem 1rem' }}>Changed By</th>
              </tr>
            </thead>
            <tbody>
              {items.map((log) => {
                const isExpanded = expandedId === log.id;
                return (
                  <Fragment key={log.id}>
                    <tr
                      style={{
                        borderBottom: '1px solid #f1f5f9',
                        cursor: 'pointer',
                        backgroundColor: isExpanded ? '#f8fafc' : 'transparent',
                      }}
                      onClick={() => {
                        setExpandedId(isExpanded ? null : log.id);
                      }}
                    >
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>
                        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </td>
                      <td
                        style={{ padding: '0.75rem 1rem', whiteSpace: 'nowrap', color: '#64748b' }}
                      >
                        {new Date(log.changed_at).toLocaleString()}
                      </td>
                      <td style={{ padding: '0.75rem 1rem' }}>
                        <span
                          style={{
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            fontFamily: 'monospace',
                            backgroundColor: '#e2e8f0',
                            padding: '0.15rem 0.45rem',
                            borderRadius: '4px',
                          }}
                        >
                          {log.entity_type}
                        </span>
                        {log.entity_id && (
                          <span
                            style={{
                              marginLeft: '0.5rem',
                              color: '#64748b',
                              fontSize: '0.8125rem',
                            }}
                          >
                            {log.entity_id}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: '#0f172a' }}>
                        {log.action}
                      </td>
                      <td style={{ padding: '0.75rem 1rem', color: '#334155' }}>
                        {log.reason || '—'}
                      </td>
                      <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                        {log.actor_name || log.actor_email || 'System'}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr style={{ backgroundColor: '#f8fafc' }}>
                        <td
                          colSpan={6}
                          style={{ padding: '1rem 1.5rem', borderBottom: '1px solid #e2e8f0' }}
                        >
                          <div
                            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}
                          >
                            <div>
                              <div
                                style={{
                                  fontSize: '0.75rem',
                                  fontWeight: 700,
                                  color: '#64748b',
                                  marginBottom: '0.25rem',
                                }}
                              >
                                BEFORE
                              </div>
                              <pre
                                style={{
                                  backgroundColor: '#ffffff',
                                  border: '1px solid #e2e8f0',
                                  borderRadius: '6px',
                                  padding: '0.75rem',
                                  fontSize: '0.75rem',
                                  maxHeight: '200px',
                                  overflow: 'auto',
                                  margin: 0,
                                }}
                              >
                                {log.before ? JSON.stringify(log.before, null, 2) : 'null'}
                              </pre>
                            </div>
                            <div>
                              <div
                                style={{
                                  fontSize: '0.75rem',
                                  fontWeight: 700,
                                  color: '#64748b',
                                  marginBottom: '0.25rem',
                                }}
                              >
                                AFTER
                              </div>
                              <pre
                                style={{
                                  backgroundColor: '#ffffff',
                                  border: '1px solid #e2e8f0',
                                  borderRadius: '6px',
                                  padding: '0.75rem',
                                  fontSize: '0.75rem',
                                  maxHeight: '200px',
                                  overflow: 'auto',
                                  margin: 0,
                                }}
                              >
                                {log.after ? JSON.stringify(log.after, null, 2) : 'null'}
                              </pre>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
