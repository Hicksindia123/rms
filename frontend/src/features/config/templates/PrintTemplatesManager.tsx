import { useEffect, useState } from 'react';
import { Printer, Eye } from 'lucide-react';

export interface PrintTemplateItem {
  id: string;
  code: string;
  name: string;
  version_no: number;
  status: string;
  layout: {
    paper_size?: string;
    orientation?: string;
    show_logo?: boolean;
    header_title?: string;
    header_subtitle?: string;
    footer_text?: string;
    sections?: Array<{ id: string; title: string; fields: string[] }>;
    signature_blocks?: Array<{ label: string; role: string }>;
  };
}

export interface SampleDataResponse {
  code: string;
  sample_data: Record<string, unknown>;
  data_dictionary: Array<{ field: string; description: string }>;
}

export function PrintTemplatesManager() {
  const [templates, setTemplates] = useState<PrintTemplateItem[]>([]);
  const [selectedCode, setSelectedCode] = useState<string>('REPLACEMENT_SLIP');
  const [sampleData, setSampleData] = useState<SampleDataResponse | null>(null);

  useEffect(() => {
    let ignore = false;
    fetch('/api/v1/config/templates')
      .then((res) => res.json())
      .then((data: PrintTemplateItem[]) => {
        if (!ignore) {
          setTemplates(data);
        }
      })
      .catch(() => {});
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedCode) return;
    let ignore = false;
    fetch(`/api/v1/config/templates/${selectedCode}/sample-data`)
      .then((res) => res.json())
      .then((data: SampleDataResponse) => {
        if (!ignore) {
          setSampleData(data);
        }
      })
      .catch(() => {});
    return () => {
      ignore = true;
    };
  }, [selectedCode]);

  const selectedTemplate = templates.find((t) => t.code === selectedCode);

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
              backgroundColor: '#ecfdf5',
              color: '#059669',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Printer size={22} />
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              Print Templates & Document Layout Designer
            </h2>
            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#64748b' }}>
              Master Plan §8.3 printable layouts with versioning, data dictionaries, signature
              blocks, and live sample preview.
            </p>
          </div>
        </div>
      </div>

      {/* Template Selection Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {templates.map((t) => (
          <button
            key={t.code}
            type="button"
            onClick={() => {
              setSelectedCode(t.code);
            }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: selectedCode === t.code ? '2px solid #3b82f6' : '1px solid #e2e8f0',
              backgroundColor: selectedCode === t.code ? '#eff6ff' : '#ffffff',
              color: selectedCode === t.code ? '#1d4ed8' : '#334155',
              fontWeight: 600,
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            {t.name} (v{t.version_no})
          </button>
        ))}
      </div>

      {/* Main Grid: Layout Config & Live Print Preview */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '1.5rem' }}>
        {/* Layout Inspector */}
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
            Template Structure: {selectedTemplate?.name}
          </h3>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '0.75rem',
              fontSize: '0.8125rem',
            }}
          >
            <div style={{ padding: '0.5rem', backgroundColor: '#f8fafc', borderRadius: '4px' }}>
              <strong>Paper Size:</strong> {selectedTemplate?.layout.paper_size || 'A4'}
            </div>
            <div style={{ padding: '0.5rem', backgroundColor: '#f8fafc', borderRadius: '4px' }}>
              <strong>Orientation:</strong> {selectedTemplate?.layout.orientation || 'portrait'}
            </div>
            <div style={{ padding: '0.5rem', backgroundColor: '#f8fafc', borderRadius: '4px' }}>
              <strong>Show Logo:</strong> {selectedTemplate?.layout.show_logo ? 'Yes' : 'No'}
            </div>
            <div style={{ padding: '0.5rem', backgroundColor: '#f8fafc', borderRadius: '4px' }}>
              <strong>Status:</strong> {selectedTemplate?.status}
            </div>
          </div>

          <div>
            <h4
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#334155',
                margin: '0 0 0.5rem 0',
              }}
            >
              Whitelisted Data Dictionary Fields
            </h4>
            <div
              style={{
                maxHeight: '180px',
                overflow: 'auto',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
              }}
            >
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                <thead style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                  <tr>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left' }}>Field</th>
                    <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left' }}>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {sampleData?.data_dictionary.map((d) => (
                    <tr key={d.field} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td
                        style={{
                          padding: '0.4rem 0.6rem',
                          fontFamily: 'monospace',
                          fontWeight: 600,
                        }}
                      >
                        {d.field}
                      </td>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#64748b' }}>
                        {d.description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h4
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#334155',
                margin: '0 0 0.5rem 0',
              }}
            >
              Layout JSON
            </h4>
            <pre
              style={{
                backgroundColor: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                padding: '0.75rem',
                fontSize: '0.75rem',
                maxHeight: '180px',
                overflow: 'auto',
                margin: 0,
              }}
            >
              {JSON.stringify(selectedTemplate?.layout, null, 2)}
            </pre>
          </div>
        </div>

        {/* Live Print Preview Sheet */}
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0, color: '#0f172a' }}>
              Live Print Preview
            </h3>
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                backgroundColor: '#fef3c7',
                color: '#92400e',
                padding: '0.2rem 0.6rem',
                borderRadius: '9999px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <Eye size={12} /> SAMPLE PREVIEW (NO DATA PERSISTED)
            </span>
          </div>

          {/* Printable Document Box */}
          <div
            style={{
              border: '2px dashed #cbd5e1',
              borderRadius: '6px',
              padding: '1.5rem',
              backgroundColor: '#ffffff',
              boxShadow: '0 4px 6px -1px rgba(0,0,0,0.05)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
            }}
          >
            {/* Header */}
            <div
              style={{
                borderBottom: '2px solid #0f172a',
                paddingBottom: '0.75rem',
                textAlign: 'center',
              }}
            >
              <h2
                style={{
                  fontSize: '1.125rem',
                  fontWeight: 800,
                  margin: 0,
                  color: '#0f172a',
                  letterSpacing: '0.025em',
                }}
              >
                {selectedTemplate?.layout.header_title}
              </h2>
              {selectedTemplate && selectedTemplate.layout.header_subtitle && (
                <div
                  style={{
                    fontSize: '0.8125rem',
                    color: '#475569',
                    marginTop: '0.25rem',
                    fontWeight: 500,
                  }}
                >
                  {selectedTemplate.layout.header_subtitle}
                </div>
              )}
            </div>

            {/* Document Body from Sample Data */}
            {sampleData && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1rem',
                  fontSize: '0.8125rem',
                }}
              >
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                    gap: '0.5rem',
                    backgroundColor: '#f8fafc',
                    padding: '0.75rem',
                    borderRadius: '4px',
                  }}
                >
                  {Object.entries(sampleData.sample_data)
                    .filter(
                      ([k]) =>
                        typeof sampleData.sample_data[k] !== 'object' && k !== 'is_sample_preview',
                    )
                    .map(([k, v]) => (
                      <div key={k}>
                        <span
                          style={{
                            color: '#64748b',
                            fontSize: '0.75rem',
                            textTransform: 'capitalize',
                          }}
                        >
                          {k.replace(/_/g, ' ')}:
                        </span>{' '}
                        <strong>{String(v)}</strong>
                      </div>
                    ))}
                </div>

                {/* Items list if available */}
                {Array.isArray(sampleData.sample_data.items) && (
                  <div>
                    <h4
                      style={{
                        fontSize: '0.8125rem',
                        fontWeight: 700,
                        margin: '0 0 0.35rem 0',
                        color: '#1e293b',
                      }}
                    >
                      Item-Wise Actions Summary
                    </h4>
                    <table
                      style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}
                    >
                      <thead style={{ backgroundColor: '#e2e8f0' }}>
                        <tr>
                          <th style={{ padding: '0.35rem 0.5rem', textAlign: 'left' }}>#</th>
                          <th style={{ padding: '0.35rem 0.5rem', textAlign: 'left' }}>Product</th>
                          <th style={{ padding: '0.35rem 0.5rem', textAlign: 'right' }}>Qty</th>
                          <th style={{ padding: '0.35rem 0.5rem', textAlign: 'left' }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(sampleData.sample_data.items as Array<Record<string, unknown>>).map(
                          (item, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                              <td style={{ padding: '0.35rem 0.5rem' }}>
                                {typeof item.line_no === 'number' ||
                                typeof item.line_no === 'string'
                                  ? String(item.line_no)
                                  : String(i + 1)}
                              </td>
                              <td style={{ padding: '0.35rem 0.5rem' }}>
                                {typeof item.product_name === 'string' ? item.product_name : ''}
                              </td>
                              <td style={{ padding: '0.35rem 0.5rem', textAlign: 'right' }}>
                                {typeof item.received_qty === 'number' ? item.received_qty : 0}
                              </td>
                              <td style={{ padding: '0.35rem 0.5rem', fontWeight: 600 }}>
                                {typeof item.action_code === 'string' ? item.action_code : ''}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Signature Blocks */}
                {(selectedTemplate?.layout.signature_blocks?.length ?? 0) > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-around',
                      marginTop: '1.5rem',
                      paddingTop: '1rem',
                      borderTop: '1px solid #e2e8f0',
                    }}
                  >
                    {selectedTemplate?.layout.signature_blocks?.map((sig, idx) => (
                      <div key={idx} style={{ textAlign: 'center', width: '180px' }}>
                        <div
                          style={{
                            borderBottom: '1px solid #475569',
                            height: '30px',
                            marginBottom: '0.35rem',
                          }}
                        />
                        <div style={{ fontWeight: 600, fontSize: '0.75rem' }}>{sig.label}</div>
                        <div style={{ fontSize: '0.7rem', color: '#64748b' }}>({sig.role})</div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Footer text */}
                {selectedTemplate?.layout.footer_text && (
                  <div
                    style={{
                      fontSize: '0.7rem',
                      color: '#64748b',
                      textAlign: 'center',
                      marginTop: '0.5rem',
                      fontStyle: 'italic',
                    }}
                  >
                    {selectedTemplate.layout.footer_text}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
