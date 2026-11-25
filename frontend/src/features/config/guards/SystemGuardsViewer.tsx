import { useEffect, useState } from 'react';
import { Lock, ShieldCheck, AlertCircle } from 'lucide-react';
import { apiRequest, toApiError } from '@/lib/api/client';

export interface SystemGuardItem {
  code: string;
  name: string;
  statement: string;
  enforcement_layer: string;
  is_locked: boolean;
}

export function SystemGuardsViewer() {
  const [guards, setGuards] = useState<SystemGuardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadGuards() {
      try {
        setLoading(true);
        const data = await apiRequest<SystemGuardItem[]>('/config/system-guards');
        setGuards(data);
      } catch (err: unknown) {
        const e = toApiError(err);
        setError(
          `Failed to load system guards: ${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`,
        );
      } finally {
        setLoading(false);
      }
    }
    void loadGuards();
  }, []);

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
      {/* Header Banner */}
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
              backgroundColor: '#fee2e2',
              color: '#dc2626',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Lock size={22} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              System Guards Catalogue (G-01 … G-18)
            </h2>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Master Plan §4.2 Non-bypassable integrity constraints. These guards are enforced in
              PostgreSQL and FastAPI services, and cannot be disabled by configuration.
            </p>
          </div>
        </div>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            backgroundColor: '#fee2e2',
            color: '#b91c1c',
            padding: '0.35rem 0.75rem',
            borderRadius: '9999px',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
          }}
        >
          <Lock size={12} /> Read-Only System Security
        </span>
      </div>

      {loading && (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
          Loading system guards...
        </div>
      )}
      {error && (
        <div
          style={{
            padding: '1rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            color: '#b91c1c',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={18} /> {error}
        </div>
      )}

      {/* Grid of Guards */}
      {!loading && !error && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
            gap: '1rem',
          }}
        >
          {guards.map((g) => (
            <div
              key={g.code}
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '1.25rem',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              }}
            >
              <div>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '0.75rem',
                  }}
                >
                  <span
                    style={{
                      fontFamily: 'monospace',
                      fontWeight: 700,
                      fontSize: '0.875rem',
                      backgroundColor: '#f1f5f9',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      color: '#0f172a',
                    }}
                  >
                    {g.code}
                  </span>
                  <span
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#15803d',
                      backgroundColor: '#dcfce7',
                      padding: '0.15rem 0.5rem',
                      borderRadius: '9999px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                    }}
                  >
                    <ShieldCheck size={12} /> Locked Guard
                  </span>
                </div>
                <h3
                  style={{
                    fontSize: '1rem',
                    fontWeight: 600,
                    margin: '0 0 0.5rem 0',
                    color: '#1e293b',
                  }}
                >
                  {g.name}
                </h3>
                <p
                  style={{ fontSize: '0.875rem', color: '#334155', lineHeight: '1.45', margin: 0 }}
                >
                  {g.statement}
                </p>
              </div>

              <div
                style={{
                  marginTop: '1rem',
                  paddingTop: '0.75rem',
                  borderTop: '1px solid #f1f5f9',
                  fontSize: '0.75rem',
                  color: '#64748b',
                }}
              >
                <span style={{ fontWeight: 600 }}>Enforcement: </span>
                {g.enforcement_layer}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
