import { useState, useEffect } from 'react';
import { ArrowLeft, Clock, Globe, Laptop, RefreshCw } from 'lucide-react';
import { Badge, Button, EmptyState, LoadingState } from '@/components/ui';
import { auditApi, type UserActivityItem } from '@/features/audit/api';
import { formatDateTime } from '@/features/goods-slips/format';

interface UserActivityPageProps {
  userId: string;
  userName?: string;
  onBack?: () => void;
}

export function UserActivityPage({ userId, userName, onBack }: UserActivityPageProps) {
  const [items, setItems] = useState<UserActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await auditApi.fetchUserActivity(userId, 50);
      setItems(res.items);
    } catch {
      setError('Failed to load user activity log.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [userId]);

  return (
    <div
      style={{
        maxWidth: '900px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Header */}
      <div>
        {onBack && (
          <Button variant="ghost" size="sm" onClick={onBack} style={{ marginBottom: '0.5rem' }}>
            <ArrowLeft size={16} style={{ marginRight: '0.25rem' }} /> Back to Users
          </Button>
        )}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.75rem',
          }}
        >
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              User Activity Log
            </h1>
            <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Sessions and sign-in audit history for user {userName ? `"${userName}"` : userId}.
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void loadData()} disabled={loading}>
            <RefreshCw size={14} style={{ marginRight: '0.25rem' }} /> Refresh
          </Button>
        </div>
      </div>

      {loading && <LoadingState label="Fetching user sessions..." />}
      {error && <div style={{ color: '#dc2626', fontSize: '0.875rem' }}>{error}</div>}

      {!loading && items.length === 0 && (
        <EmptyState
          title="No activity recorded"
          hint="Login events and user sessions will be logged here."
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
          <div
            style={{
              padding: '0.75rem 1rem',
              backgroundColor: '#f8fafc',
              borderBottom: '1px solid #e2e8f0',
              fontWeight: 600,
              fontSize: '0.875rem',
              color: '#475569',
            }}
          >
            Recent Sessions ({items.length})
          </div>

          <div>
            {items.map((act) => (
              <div
                key={act.id}
                style={{
                  padding: '1rem',
                  borderBottom: '1px solid #f1f5f9',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '0.75rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div
                    style={{
                      width: '36px',
                      height: '36px',
                      borderRadius: '50%',
                      backgroundColor: '#eff6ff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#2563eb',
                    }}
                  >
                    <Laptop size={18} />
                  </div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontWeight: 600, color: '#1e293b' }}>{act.activity_type}</span>
                      <Badge variant="success">Active</Badge>
                    </div>
                    {act.description && (
                      <div style={{ fontSize: '0.8125rem', color: '#64748b' }}>
                        {act.description}
                      </div>
                    )}
                    <div
                      style={{
                        display: 'flex',
                        gap: '1rem',
                        fontSize: '0.75rem',
                        color: '#94a3b8',
                        marginTop: '0.25rem',
                      }}
                    >
                      {act.ip_address && (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                          <Globe size={12} /> IP: {act.ip_address}
                        </span>
                      )}
                      {act.user_agent && (
                        <span
                          style={{
                            maxWidth: '300px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          UA: {act.user_agent}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    fontSize: '0.8125rem',
                    color: '#64748b',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                  }}
                >
                  <Clock size={14} />
                  {formatDateTime(act.created_at)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
