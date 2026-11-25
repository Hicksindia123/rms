import { useCallback, useState } from 'react';
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Clock,
  FileCheck,
  FileText,
  History,
  Package,
  Shield,
  Truck,
  User,
} from 'lucide-react';
import { Badge, Button, EmptyState, LoadingState } from '@/components/ui';
import { auditApi, type GsActivityItem } from '@/features/audit/api';
import { formatDateTime } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';

interface GsActivityTabProps {
  gsId: string;
}

type CategoryFilter = 'ALL' | 'STATUS' | 'STOCK' | 'DOCUMENT' | 'COMMERCIAL' | 'AUDIT';

/** Field-diff values are JSON: primitives print as-is, objects / arrays as JSON. */
function formatDiffValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value);
  }
  return JSON.stringify(value);
}

export function GsActivityTab({ gsId }: GsActivityTabProps) {
  const [activeCategory, setActiveCategory] = useState<CategoryFilter>('ALL');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const fetchActivity = useCallback(
    () => auditApi.fetchGsActivity(gsId, activeCategory === 'ALL' ? undefined : activeCategory),
    [gsId, activeCategory],
  );
  const activity = useApiQuery(fetchActivity);
  const items: GsActivityItem[] = activity.data?.items ?? [];
  const loading = activity.loading;
  const error = activity.error ? 'Failed to load activity history.' : null;

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'STATUS':
        return <Truck size={16} color="#2563eb" />;
      case 'STOCK':
        return <Package size={16} color="#16a34a" />;
      case 'DOCUMENT':
        return <FileText size={16} color="#0891b2" />;
      case 'COMMERCIAL':
        return <FileCheck size={16} color="#d97706" />;
      case 'AUDIT':
        return <Shield size={16} color="#7c3aed" />;
      default:
        return <Activity size={16} color="#64748b" />;
    }
  };

  const categories: Array<{ id: CategoryFilter; label: string }> = [
    { id: 'ALL', label: 'All Activities' },
    { id: 'STATUS', label: 'Status' },
    { id: 'STOCK', label: 'Stock Movements' },
    { id: 'DOCUMENT', label: 'Documents' },
    { id: 'COMMERCIAL', label: 'Commercial / CN' },
    { id: 'AUDIT', label: 'Field Edits' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Category Pills & Controls */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => {
                setActiveCategory(c.id);
              }}
              style={{
                padding: '0.35rem 0.75rem',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: activeCategory === c.id ? '#2563eb' : '#cbd5e1',
                backgroundColor: activeCategory === c.id ? '#2563eb' : '#fff',
                color: activeCategory === c.id ? '#fff' : '#334155',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {c.label}
            </button>
          ))}
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            activity.reload();
          }}
          style={{ fontSize: '0.75rem' }}
        >
          <History size={14} style={{ marginRight: '0.25rem' }} /> Refresh
        </Button>
      </div>

      {/* Loading & Error */}
      {loading && <LoadingState label="Loading activity timeline..." />}
      {error && <div style={{ color: '#dc2626', fontSize: '0.875rem' }}>{error}</div>}

      {/* Timeline items */}
      {!loading && items.length === 0 && (
        <EmptyState
          title="No activity records found"
          hint="Activities such as status changes, field updates, stock transfers, and credit notes will appear here."
        />
      )}

      {!loading && items.length > 0 && (
        <div
          style={{
            position: 'relative',
            paddingLeft: '1.75rem',
            borderLeft: '2px solid #e2e8f0',
            marginLeft: '0.75rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}
        >
          {items.map((item) => {
            const isExpanded = expandedIds.has(item.id);
            const hasDiffs = item.diffs.length > 0;

            return (
              <div
                key={item.id}
                style={{
                  position: 'relative',
                  backgroundColor: '#fff',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  padding: '0.875rem 1rem',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                }}
              >
                {/* Timeline node circle */}
                <div
                  style={{
                    position: 'absolute',
                    left: '-2.35rem',
                    top: '1rem',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    backgroundColor: '#fff',
                    border: '2px solid #cbd5e1',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {getCategoryIcon(item.category)}
                </div>

                {/* Item Header */}
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    gap: '0.5rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontWeight: 600, color: '#0f172a', fontSize: '0.9375rem' }}>
                        {item.title}
                      </span>
                      <Badge variant="neutral">{item.category}</Badge>
                      {item.step_code && (
                        <span
                          style={{
                            fontSize: '0.75rem',
                            color: '#64748b',
                            backgroundColor: '#f1f5f9',
                            padding: '0.1rem 0.35rem',
                            borderRadius: '4px',
                          }}
                        >
                          {item.step_code}
                        </span>
                      )}
                    </div>

                    {item.description && (
                      <div
                        style={{
                          fontSize: '0.875rem',
                          color: '#475569',
                          marginTop: '0.25rem',
                        }}
                      >
                        {item.description}
                      </div>
                    )}
                  </div>

                  <div
                    style={{
                      fontSize: '0.75rem',
                      color: '#64748b',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'flex-end',
                      gap: '0.15rem',
                    }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                      <Clock size={12} /> {formatDateTime(item.at)}
                    </span>
                    {item.actor_name && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <User size={12} /> {item.actor_name}
                      </span>
                    )}
                  </div>
                </div>

                {/* Diff Viewer toggle if present */}
                {hasDiffs && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <button
                      type="button"
                      onClick={() => {
                        toggleExpand(item.id);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#2563eb',
                        fontSize: '0.8125rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        padding: 0,
                      }}
                    >
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      {isExpanded
                        ? 'Hide field changes'
                        : `View ${String(item.diffs.length)} changed field${item.diffs.length > 1 ? 's' : ''}`}
                    </button>

                    {isExpanded && (
                      <div
                        style={{
                          marginTop: '0.5rem',
                          backgroundColor: '#f8fafc',
                          borderRadius: '6px',
                          border: '1px solid #e2e8f0',
                          padding: '0.5rem',
                          overflowX: 'auto',
                        }}
                      >
                        <table
                          style={{
                            width: '100%',
                            fontSize: '0.8125rem',
                            borderCollapse: 'collapse',
                          }}
                        >
                          <thead>
                            <tr
                              style={{
                                textAlign: 'left',
                                color: '#64748b',
                                borderBottom: '1px solid #e2e8f0',
                              }}
                            >
                              <th style={{ padding: '0.35rem 0.5rem' }}>Field</th>
                              <th style={{ padding: '0.35rem 0.5rem' }}>Old Value</th>
                              <th style={{ padding: '0.35rem 0.5rem' }}>New Value</th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.diffs.map((diff, idx) => (
                              <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                <td
                                  style={{
                                    padding: '0.35rem 0.5rem',
                                    fontWeight: 500,
                                    color: '#334155',
                                  }}
                                >
                                  {diff.field_label || diff.field}
                                </td>
                                <td style={{ padding: '0.35rem 0.5rem', color: '#dc2626' }}>
                                  {formatDiffValue(diff.old_value)}
                                </td>
                                <td style={{ padding: '0.35rem 0.5rem', color: '#16a34a' }}>
                                  {formatDiffValue(diff.new_value)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
