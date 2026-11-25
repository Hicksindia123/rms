import { useEffect, useState } from 'react';
import { Sliders, CheckCircle2, AlertCircle } from 'lucide-react';

import { apiRequest, toApiError } from '@/lib/api/client';

export interface SettingItem {
  id: string;
  key: string;
  value: unknown;
  category: string;
  description: string | null;
  source_ref: string | null;
}

export function SystemSettingsManager() {
  const [activeCategory, setActiveCategory] = useState<'provisional' | 'branding' | 'general'>(
    'provisional',
  );
  const [settings, setSettings] = useState<SettingItem[]>([]);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Branding state
  const [primaryColor, setPrimaryColor] = useState('#0f172a');
  const [logoUrl, setLogoUrl] = useState('/assets/logo.png');
  const [contrastRatio, setContrastRatio] = useState<number | null>(null);
  const [contrastAA, setContrastAA] = useState<boolean>(true);

  const loadSettings = () => {
    apiRequest<SettingItem[]>('/config/settings')
      .then((data) => {
        setSettings(data);
        const col = data.find((s) => s.key === 'branding_primary_color');
        if (col && typeof col.value === 'string') {
          setPrimaryColor(col.value);
        }
        const logo = data.find((s) => s.key === 'branding_logo_url');
        if (logo && typeof logo.value === 'string') {
          setLogoUrl(logo.value);
        }
      })
      .catch((err: unknown) => {
        const e = toApiError(err);
        setError(
          `Could not load the settings: ${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`,
        );
      });
  };

  useEffect(() => {
    loadSettings();
  }, []);

  // Check contrast whenever primary color changes
  useEffect(() => {
    if (!primaryColor.startsWith('#') || (primaryColor.length !== 4 && primaryColor.length !== 7)) {
      return;
    }
    let ignore = false;
    apiRequest<{ contrast_ratio: number; normal_text_aa: boolean }>(
      '/config/settings/branding/contrast-check',
      {
        method: 'POST',
        body: { foreground_color: '#ffffff', background_color: primaryColor },
      },
    )
      .then((data) => {
        if (!ignore) {
          setContrastRatio(data.contrast_ratio);
          setContrastAA(data.normal_text_aa);
        }
      })
      .catch((err: unknown) => {
        // The contrast hint is advisory; the colour itself is still saved by the user.
        if (!ignore) setContrastRatio(null);
        console.warn('contrast check failed', toApiError(err).message);
      });
    return () => {
      ignore = true;
    };
  }, [primaryColor]);

  async function updateSettingValue(key: string, newValue: unknown) {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/config/settings/${encodeURIComponent(key)}`, {
        method: 'PUT',
        body: { value: newValue, reason: `Admin updated setting ${key}` },
      });
      setSuccess(`Setting '${key}' updated successfully.`);
      loadSettings();
    } catch (err: unknown) {
      const e = toApiError(err);
      setError(`${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`);
    }
  }

  const provisionalSettings = settings.filter((s) => s.category === 'provisional');
  const generalSettings = settings.filter(
    (s) => s.category === 'general' || s.category === 'uploads',
  );

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
              backgroundColor: '#fef3c7',
              color: '#d97706',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Sliders size={22} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              System Settings & Provisional Business Rules
            </h2>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Provisional business rules and application shell branding settings.
            </p>
          </div>
        </div>

        {/* Tab buttons */}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            onClick={() => {
              setActiveCategory('provisional');
            }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: activeCategory === 'provisional' ? '2px solid #3f63fb' : '1px solid #cbd5e1',
              backgroundColor: activeCategory === 'provisional' ? '#eef3ff' : '#ffffff',
              color: activeCategory === 'provisional' ? '#2236d6' : '#334155',
              fontWeight: 600,
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            Business Rules (Provisional)
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveCategory('branding');
            }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: activeCategory === 'branding' ? '2px solid #3f63fb' : '1px solid #cbd5e1',
              backgroundColor: activeCategory === 'branding' ? '#eef3ff' : '#ffffff',
              color: activeCategory === 'branding' ? '#2236d6' : '#334155',
              fontWeight: 600,
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            Branding & Shell
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveCategory('general');
            }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: activeCategory === 'general' ? '2px solid #3f63fb' : '1px solid #cbd5e1',
              backgroundColor: activeCategory === 'general' ? '#eef3ff' : '#ffffff',
              color: activeCategory === 'general' ? '#2236d6' : '#334155',
              fontWeight: 600,
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            General Settings
          </button>
        </div>
      </div>

      {success && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: '6px',
            color: '#15803d',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <CheckCircle2 size={16} /> {success}
        </div>
      )}
      {error && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            color: '#b91c1c',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Provisional Decisions Tab */}
      {activeCategory === 'provisional' && (
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '1rem 1.5rem',
              backgroundColor: '#fffbeb',
              borderBottom: '1px solid #fde68a',
              color: '#92400e',
              fontSize: '0.875rem',
            }}
          >
            <strong>Master Plan §5 Policy:</strong> None of these decisions are silently decided in
            code. Each provisional approach is configurable below so the business owner can change
            it without code rewrites.
          </div>
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
                <th style={{ padding: '0.75rem 1rem', width: '100px' }}>DEC ID</th>
                <th style={{ padding: '0.75rem 1rem' }}>Key & Description</th>
                <th style={{ padding: '0.75rem 1rem', width: '220px' }}>Current Value / Toggle</th>
              </tr>
            </thead>
            <tbody>
              {provisionalSettings.map((s) => {
                const isBool = typeof s.value === 'boolean';
                return (
                  <tr key={s.key} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          fontFamily: 'monospace',
                          backgroundColor: '#fef3c7',
                          color: '#92400e',
                          padding: '0.2rem 0.5rem',
                          borderRadius: '4px',
                        }}
                      >
                        {s.source_ref || 'DEC'}
                      </span>
                    </td>
                    <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                      <div
                        style={{
                          fontWeight: 600,
                          color: '#0f172a',
                          fontFamily: 'monospace',
                          fontSize: '0.8125rem',
                        }}
                      >
                        {s.key}
                      </div>
                      <div
                        style={{ color: '#475569', fontSize: '0.8125rem', marginTop: '0.25rem' }}
                      >
                        {s.description}
                      </div>
                    </td>
                    <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                      {isBool ? (
                        <button
                          type="button"
                          onClick={() => {
                            void updateSettingValue(s.key, !s.value);
                          }}
                          style={{
                            padding: '0.35rem 0.75rem',
                            borderRadius: '9999px',
                            border: 'none',
                            fontSize: '0.8125rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                            backgroundColor: s.value ? '#dcfce7' : '#fee2e2',
                            color: s.value ? '#15803d' : '#b91c1c',
                          }}
                        >
                          {s.value ? 'Enabled (True)' : 'Disabled (False)'}
                        </button>
                      ) : (
                        <div
                          style={{
                            fontFamily: 'monospace',
                            fontSize: '0.8125rem',
                            color: '#0f172a',
                          }}
                        >
                          {JSON.stringify(s.value)}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Branding Tab */}
      {activeCategory === 'branding' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
          {/* Controls */}
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
            }}
          >
            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
              Shell Branding & Primary Color
            </h3>

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.35rem',
                }}
              >
                Primary Header Color (Hex)
              </label>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <input
                  type="color"
                  value={primaryColor}
                  onChange={(e) => {
                    setPrimaryColor(e.target.value);
                  }}
                  style={{
                    width: '42px',
                    height: '42px',
                    padding: 0,
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                  }}
                />
                <input
                  type="text"
                  value={primaryColor}
                  onChange={(e) => {
                    setPrimaryColor(e.target.value);
                  }}
                  style={{
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                    fontFamily: 'monospace',
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    void updateSettingValue('branding_primary_color', primaryColor);
                  }}
                  style={{
                    padding: '0.5rem 1rem',
                    borderRadius: '6px',
                    border: 'none',
                    backgroundColor: '#2a47f0',
                    color: '#ffffff',
                    fontWeight: 600,
                    fontSize: '0.875rem',
                    cursor: 'pointer',
                  }}
                >
                  Save Color
                </button>
              </div>
            </div>

            {/* Contrast Check Indicator */}
            {contrastRatio !== null && (
              <div
                style={{
                  padding: '0.75rem',
                  backgroundColor: contrastAA ? '#f0fdf4' : '#fef2f2',
                  border: `1px solid ${contrastAA ? '#bbf7d0' : '#fecaca'}`,
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontSize: '0.8125rem',
                  color: contrastAA ? '#15803d' : '#b91c1c',
                }}
              >
                {contrastAA ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                <span>
                  WCAG Contrast Ratio with white text: <strong>{contrastRatio}:1</strong> (
                  {contrastAA ? 'Passes AA' : 'Fails AA'})
                </span>
              </div>
            )}

            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: '#475569',
                  marginBottom: '0.35rem',
                }}
              >
                Logo URL / Path
              </label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  type="text"
                  value={logoUrl}
                  onChange={(e) => {
                    setLogoUrl(e.target.value);
                  }}
                  placeholder="/assets/logo.png"
                  style={{
                    flex: 1,
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    void updateSettingValue('branding_logo_url', logoUrl);
                  }}
                  style={{
                    padding: '0.5rem 1rem',
                    borderRadius: '6px',
                    border: 'none',
                    backgroundColor: '#2a47f0',
                    color: '#ffffff',
                    fontWeight: 600,
                    fontSize: '0.875rem',
                    cursor: 'pointer',
                  }}
                >
                  Save Logo
                </button>
              </div>
            </div>
          </div>

          {/* Live Shell Preview */}
          <div
            style={{
              backgroundColor: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
              Live Shell Header Preview
            </h3>
            <div
              style={{
                backgroundColor: primaryColor,
                color: '#ffffff',
                padding: '0.75rem 1.25rem',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                {logoUrl && (
                  <div
                    style={{
                      background: '#ffffff',
                      padding: '2px 6px',
                      borderRadius: '6px',
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    <img
                      src={logoUrl}
                      alt="Logo"
                      loading="lazy"
                      style={{ height: '26px', objectFit: 'contain' }}
                      onError={(e) => {
                        (e.target as HTMLElement).style.display = 'none';
                      }}
                    />
                  </div>
                )}
                <span style={{ fontWeight: 700, fontSize: '1rem' }}>
                  Replacement Management System
                </span>
              </div>
              <span style={{ fontSize: '0.75rem', opacity: 0.8 }}>Live Shell Preview</span>
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
              The header bar reflects the brand color immediately without requiring an application
              rebuild.
            </div>
          </div>
        </div>
      )}

      {/* General Settings Tab */}
      {activeCategory === 'general' && (
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
                <th style={{ padding: '0.75rem 1rem' }}>Key</th>
                <th style={{ padding: '0.75rem 1rem' }}>Description</th>
                <th style={{ padding: '0.75rem 1rem' }}>Value</th>
              </tr>
            </thead>
            <tbody>
              {generalSettings.map((s) => (
                <tr key={s.key} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', fontWeight: 600 }}>
                    {s.key}
                  </td>
                  <td style={{ padding: '0.75rem 1rem', color: '#475569' }}>
                    {s.description || '—'}
                  </td>
                  <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace' }}>
                    {JSON.stringify(s.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
