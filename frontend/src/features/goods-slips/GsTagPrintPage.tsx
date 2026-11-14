import { useCallback, useState } from 'react';
import QRCode from 'qrcode';
import { ArrowLeft, Printer } from 'lucide-react';

import { Button, ErrorState, LoadingState, RadioGroup } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { gsApi, type GsTag } from './api';

type Layout = 'a4' | 'label';

interface Props {
  gsId: string;
  onBack: () => void;
}

/** BR-02: one GS_TAG label per carton ("Carton 1 of 3", AMD-03) with a QR (gs_no|id); A4 sheet or label size. */
export function GsTagPrintPage({ gsId, onBack }: Props) {
  const fetcher = useCallback(async () => {
    const t = await gsApi.tag(gsId);
    const qr = await QRCode.toDataURL(t.qr_payload, {
      margin: 1,
      width: 192,
      errorCorrectionLevel: 'M',
    });
    return { tag: t, qr };
  }, [gsId]);
  const query = useApiQuery<{ tag: GsTag; qr: string }>(fetcher);
  const loaded = query.data?.tag.gs_id === gsId ? query.data : null;
  const tag = loaded?.tag ?? null;
  const qr = loaded?.qr ?? null;
  const error = query.error;
  const load = query.reload;
  const [layout, setLayout] = useState<Layout>('a4');

  const toolbar = (
    <div
      className="no-print"
      style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1rem' }}
    >
      <Button type="button" variant="ghost" onClick={onBack} style={{ alignSelf: 'flex-start' }}>
        <ArrowLeft size={16} aria-hidden="true" /> Back to goods slip
      </Button>
      <h1 className="page__title">Print GS tag</h1>
    </div>
  );

  if (error) {
    return (
      <div className="page">
        {toolbar}
        <ErrorState error={error} onRetry={load} title="Could not load the tag" />
      </div>
    );
  }
  if (!tag || !qr) {
    return (
      <div className="page">
        {toolbar}
        <LoadingState label="Preparing tag…" />
      </div>
    );
  }

  const fields = tag.sections
    .flatMap((s) => s.fields)
    .filter((f) => f.key !== 'gs_no' && f.key !== 'qr_code');

  return (
    <div className="page">
      {toolbar}
      <div
        className="no-print"
        style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1rem' }}
      >
        <RadioGroup
          id="tag-layout"
          name="tag-layout"
          value={layout}
          onChange={(v) => {
            setLayout(v === 'label' ? 'label' : 'a4');
          }}
          options={[
            { value: 'a4', label: 'A4 sheet (2 per row)' },
            { value: 'label', label: 'Label printer (100 × 50 mm, one per label)' },
          ]}
        />
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={() => {
            window.print();
          }}
        >
          <Printer size={18} aria-hidden="true" /> Print {String(tag.labels.length)} label
          {tag.labels.length === 1 ? '' : 's'}
        </Button>
        <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--color-muted)' }}>
          Template {tag.template_code} v{String(tag.template_version)}
        </p>
      </div>

      <div className={`tag-sheet tag-sheet--${layout}`} data-testid="tag-sheet">
        {tag.labels.map((l) => (
          <article key={l.box_no} className="tag-label" aria-label={`${tag.gs_no} ${l.caption}`}>
            <img className="tag-label__qr" src={qr} alt={`QR code for ${tag.gs_no}`} />
            <div style={{ minWidth: 0 }}>
              {tag.layout.header_title ? (
                <p className="tag-label__title">{tag.layout.header_title}</p>
              ) : null}
              <p className="tag-label__gs">{tag.gs_no}</p>
              {fields.map((f) =>
                f.value ? (
                  <p key={f.key} className="tag-label__field">
                    <strong>{f.label}:</strong> {f.value}
                  </p>
                ) : null,
              )}
              <p className="tag-label__box">{l.caption}</p>
            </div>
            {tag.layout.footer_text ? (
              <p className="tag-label__footer">{tag.layout.footer_text}</p>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
