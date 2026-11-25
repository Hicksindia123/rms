import { useEffect, useState } from 'react';
import { Hash, AlertCircle, CheckCircle2 } from 'lucide-react';
import { apiRequest, toApiError } from '@/lib/api/client';

export interface NumberSeriesItem {
  id: string;
  code: string;
  name: string;
  prefix: string | null;
  pattern: string;
  reset_policy: string;
  fy_start_month: number;
  fy_format: string;
  start_value: number;
  is_active: boolean;
  is_provisional_gs: boolean;
  max_used_counter: number;
}

export interface NumberPreviewData {
  code: string;
  pattern: string;
  on_date: string;
  fy_string: string;
  period_key: string;
  next_numbers: string[];
}

export function NumberSeriesManager() {
  const [seriesList, setSeriesList] = useState<NumberSeriesItem[]>([]);
  const [selectedCode, setSelectedCode] = useState<string>('GS');
  const [previewDate, setPreviewDate] = useState<string>(
    new Date().toISOString().split('T')[0] ?? '',
  );
  const [previewData, setPreviewData] = useState<NumberPreviewData | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Edit form state
  const [name, setName] = useState('');
  const [prefix, setPrefix] = useState('');
  const [pattern, setPattern] = useState('');
  const [resetPolicy, setResetPolicy] = useState('YEARLY_FY');
  const [fyStartMonth, setFyStartMonth] = useState(4);
  const [fyFormat, setFyFormat] = useState('LONG');
  const [startValue, setStartValue] = useState(1);

  function selectSeries(code: string) {
    setSelectedCode(code);
    const found = seriesList.find((s) => s.code === code);
    if (found) {
      setName(found.name);
      setPrefix(found.prefix ?? '');
      setPattern(found.pattern);
      setResetPolicy(found.reset_policy);
      setFyStartMonth(found.fy_start_month);
      setFyFormat(found.fy_format);
      setStartValue(found.start_value);
      setError(null);
      setSuccess(null);
    }
  }

  useEffect(() => {
    let ignore = false;
    apiRequest<NumberSeriesItem[]>('/config/numbering')
      .then((data) => {
        if (!ignore) {
          setSeriesList(data);
          const initial = data[0];
          if (initial) {
            setSelectedCode(initial.code);
            setName(initial.name);
            setPrefix(initial.prefix ?? '');
            setPattern(initial.pattern);
            setResetPolicy(initial.reset_policy);
            setFyStartMonth(initial.fy_start_month);
            setFyFormat(initial.fy_format);
            setStartValue(initial.start_value);
          }
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          const e = toApiError(err);
          setError(
            `Could not load the number series: ${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`,
          );
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  // Load preview
  useEffect(() => {
    if (!selectedCode) return;
    let ignore = false;
    apiRequest<NumberPreviewData>(`/config/numbering/${selectedCode}/preview`, {
      query: { count: 3, on_date: previewDate },
    })
      .then((data) => {
        if (!ignore) {
          setPreviewData(data);
        }
      })
      .catch((err: unknown) => {
        // Advisory live preview only: the editor and save path keep working without it.
        console.warn('number series preview failed', selectedCode, toApiError(err).message);
      });
    return () => {
      ignore = true;
    };
  }, [selectedCode, previewDate, pattern, prefix, resetPolicy, fyStartMonth, fyFormat, startValue]);

  async function handleSave() {
    setError(null);
    setSuccess(null);
    setSaving(true);

    try {
      await apiRequest(`/config/numbering/${selectedCode}`, {
        method: 'PUT',
        body: {
          name,
          prefix: prefix || null,
          pattern,
          reset_policy: resetPolicy,
          fy_start_month: fyStartMonth,
          fy_format: fyFormat,
          start_value: startValue,
          is_active: true,
          reason: `Admin updated pattern for ${selectedCode}`,
        },
      });

      setSuccess(`Number series ${selectedCode} updated successfully.`);
      const updatedData = await apiRequest<NumberSeriesItem[]>('/config/numbering');
      setSeriesList(updatedData);
    } catch (err: unknown) {
      const e = toApiError(err);
      setError(`${e.message}${e.requestId ? ` (Request ID: ${e.requestId})` : ''}`);
    } finally {
      setSaving(false);
    }
  }

  const selectedSeries = seriesList.find((s) => s.code === selectedCode);

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
              backgroundColor: '#e0e7ff',
              color: '#2236d6',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Hash size={22} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Number Series Configuration & Next Number Preview
            </h2>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Manage prefix, financial-year tokens, sequence padding, and rollover periods for all
              operational documents.
            </p>
          </div>
        </div>
      </div>

      {/* Series selection tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {seriesList.map((s) => (
          <button
            key={s.code}
            type="button"
            onClick={() => {
              selectSeries(s.code);
            }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: selectedCode === s.code ? '2px solid #3f63fb' : '1px solid #e2e8f0',
              backgroundColor: selectedCode === s.code ? '#eef3ff' : '#ffffff',
              color: selectedCode === s.code ? '#2236d6' : '#334155',
              fontWeight: 600,
              fontSize: '0.875rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            {s.name} ({s.code})
            {s.is_provisional_gs && (
              <span
                style={{
                  fontSize: '0.7rem',
                  backgroundColor: '#fef3c7',
                  color: '#92400e',
                  padding: '0.1rem 0.35rem',
                  borderRadius: '4px',
                }}
              >
                Provisional
              </span>
            )}
          </button>
        ))}
      </div>

      {/* DEC-01 Banner for Goods Slip */}
      {selectedSeries?.is_provisional_gs && (
        <div
          style={{
            backgroundColor: '#fffbeb',
            border: '1px solid #fde68a',
            borderRadius: '8px',
            padding: '1rem 1.25rem',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '0.75rem',
            color: '#92400e',
          }}
        >
          <AlertCircle size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div style={{ fontSize: '0.875rem', lineHeight: '1.4' }}>
            <strong>Provisional Goods Slip Format:</strong> The workbook specifies that Goods Slips
            are auto-generated with "existing formatting". The placeholder format below is fully
            configurable without code changes. Set your desired prefix, FY token, sequence length,
            and starting value.
          </div>
        </div>
      )}

      {/* Main Grid: Editor & Live Preview */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Editor Form */}
        <div
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            padding: '1.5rem',
          }}
        >
          <h3
            style={{ fontSize: '1rem', fontWeight: 600, margin: '0 0 1.25rem 0', color: '#0f172a' }}
          >
            Edit Series: {selectedCode}
          </h3>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleSave();
            }}
            style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}
          >
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
                Series Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                }}
                required
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.875rem',
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0.75rem' }}>
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
                  Prefix
                </label>
                <input
                  type="text"
                  value={prefix}
                  onChange={(e) => {
                    setPrefix(e.target.value);
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
                  Pattern Template
                </label>
                <input
                  type="text"
                  value={pattern}
                  onChange={(e) => {
                    setPattern(e.target.value);
                  }}
                  required
                  placeholder="{PREFIX}/{FY}/{SEQ:5}"
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                    fontFamily: 'monospace',
                  }}
                />
              </div>
            </div>

            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
              Available tokens: <code>{'{PREFIX}'}</code>, <code>{'{FY}'}</code>,{' '}
              <code>{'{YYYY}'}</code>, <code>{'{YY}'}</code>, <code>{'{MM}'}</code>,{' '}
              <code>{'{SEQ}'}</code>, <code>{'{SEQ:5}'}</code>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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
                  Reset Policy
                </label>
                <select
                  value={resetPolicy}
                  onChange={(e) => {
                    setResetPolicy(e.target.value);
                  }}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                    backgroundColor: '#ffffff',
                  }}
                >
                  <option value="YEARLY_FY">Yearly by Financial Year (YEARLY_FY)</option>
                  <option value="MONTHLY">Monthly (MONTHLY)</option>
                  <option value="NEVER">Never (Continuous NEVER)</option>
                </select>
              </div>

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
                  FY Start Month
                </label>
                <select
                  value={fyStartMonth}
                  onChange={(e) => {
                    setFyStartMonth(Number(e.target.value));
                  }}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                    backgroundColor: '#ffffff',
                  }}
                >
                  <option value={4}>April (India standard)</option>
                  <option value={1}>January (Calendar year)</option>
                  <option value={7}>July</option>
                  <option value={10}>October</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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
                  FY Token Format
                </label>
                <select
                  value={fyFormat}
                  onChange={(e) => {
                    setFyFormat(e.target.value);
                  }}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.875rem',
                    backgroundColor: '#ffffff',
                  }}
                >
                  <option value="LONG">Long (2026-27)</option>
                  <option value="COMPACT">Compact (2627)</option>
                  <option value="SHORT">Short (26-27)</option>
                </select>
              </div>

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
                  Starting Value (≥ Max Used)
                </label>
                <input
                  type="number"
                  min={selectedSeries?.max_used_counter || 1}
                  value={startValue}
                  onChange={(e) => {
                    setStartValue(Number(e.target.value));
                  }}
                  required
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

            {error && (
              <div
                style={{
                  padding: '0.75rem',
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '6px',
                  color: '#b91c1c',
                  fontSize: '0.8125rem',
                }}
              >
                {error}
              </div>
            )}
            {success && (
              <div
                style={{
                  padding: '0.75rem',
                  backgroundColor: '#f0fdf4',
                  border: '1px solid #bbf7d0',
                  borderRadius: '6px',
                  color: '#15803d',
                  fontSize: '0.8125rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                }}
              >
                <CheckCircle2 size={16} /> {success}
              </div>
            )}

            <button
              type="submit"
              disabled={saving}
              style={{
                marginTop: '0.5rem',
                padding: '0.6rem 1.25rem',
                backgroundColor: '#2a47f0',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                fontSize: '0.875rem',
                cursor: 'pointer',
              }}
            >
              {saving ? 'Saving...' : 'Save Configuration Changes'}
            </button>
          </form>
        </div>

        {/* Live Preview Panel */}
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
              Next 3 Numbers Live Preview
            </h3>
            <span
              style={{
                fontSize: '0.75rem',
                backgroundColor: '#e2e8f0',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
                color: '#475569',
              }}
            >
              SAMPLE PREVIEW
            </span>
          </div>

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
              Preview Date (Test FY Rollover e.g. 31-Mar vs 01-Apr)
            </label>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <input
                type="date"
                value={previewDate}
                onChange={(e) => {
                  setPreviewDate(e.target.value);
                }}
                style={{
                  padding: '0.5rem',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.875rem',
                }}
              />
              <button
                type="button"
                onClick={() => {
                  setPreviewDate('2026-03-31');
                }}
                style={{
                  padding: '0.4rem 0.6rem',
                  fontSize: '0.75rem',
                  borderRadius: '4px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#f8fafc',
                  cursor: 'pointer',
                }}
              >
                Set 31-Mar
              </button>
              <button
                type="button"
                onClick={() => {
                  setPreviewDate('2026-04-01');
                }}
                style={{
                  padding: '0.4rem 0.6rem',
                  fontSize: '0.75rem',
                  borderRadius: '4px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#f8fafc',
                  cursor: 'pointer',
                }}
              >
                Set 01-Apr
              </button>
            </div>
          </div>

          {previewData && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div
                style={{
                  padding: '0.75rem',
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '6px',
                  fontSize: '0.8125rem',
                  color: '#334155',
                }}
              >
                <div>
                  <strong>Period Key:</strong> {previewData.period_key}
                </div>
                <div>
                  <strong>FY Rendering:</strong> {previewData.fy_string}
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {previewData.next_numbers.map((num, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '0.85rem 1rem',
                      backgroundColor: '#f0fdf4',
                      border: '1px solid #bbf7d0',
                      borderRadius: '6px',
                      fontFamily: 'monospace',
                      fontWeight: 700,
                      fontSize: '1rem',
                      color: '#15803d',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span>{num}</span>
                    <span style={{ fontSize: '0.75rem', fontWeight: 500, color: '#16a34a' }}>
                      #{String(idx + 1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
