import { useCallback, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, Printer, RefreshCw } from 'lucide-react';

import { DynamicForm } from '@/components/erp';
import type { FieldRenderApi } from '@/components/erp';
import { Button, Checkbox, ErrorState, Input, LoadingState, Select } from '@/components/ui';
import type { FormFieldSnapshot } from '@/features/config/forms/types';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import {
  gsApi,
  type CreateGsPayload,
  type GateDocument,
  type GateForm,
  type GateInwardResult,
  type LookupItem,
} from './api';
import { DistributorPicker } from './DistributorPicker';
import { GateDocumentsEditor } from './GateDocumentsEditor';
import { newDocDraft, toDocumentInputs, type DocDraft } from './gateDocs';
import { uploadDocumentFiles as uploadFiles, type PendingFile } from './gateUploads';
import { TransporterInput } from './GatePickers';
import type { PartySelection } from './useStations';
import { defaultValues, toDynamicFormSnapshot } from './snapshot';
import './gateForm.css';

// Which return type shows the gate entry fields is configured on the form version (visible_when on
// the RETURN_TYPE code, AMD-02 / DEC-39); nothing here keys off labels (CLAUDE.md rule e).
const MASTER_FIELDS: ReadonlySet<string> = new Set(['party_name', 'state', 'station']);

interface Props {
  onOpenTag: (gsId: string) => void;
  onOpenGs: (gsId: string) => void;
}

interface Created {
  result: GateInwardResult;
  failed: PendingFile[];
}

/** Step-1 gate inward (P2-02; form v2 per change plan 2026-11-12 Phase 2): mobile-first GS
 * creation at the gate. Labels, options, required rules and document types all come from the
 * published S1_GATE_INWARD form version and the GATE_DOCUMENT configuration. */
export function NewGoodsSlipPage({ onOpenTag, onOpenGs }: Props) {
  const fetcher = useCallback(async () => {
    const [form, states] = await Promise.all([gsApi.gateForm(), gsApi.states()]);
    return { form, states };
  }, []);
  const query = useApiQuery<{ form: GateForm; states: LookupItem[] }>(fetcher);
  const [created, setCreated] = useState<Created | null>(null);
  const [formKey, setFormKey] = useState(0);

  if (query.error) {
    return (
      <div className="page page--narrow">
        <h1 className="page__title">New Goods Slip</h1>
        <ErrorState
          error={query.error}
          onRetry={query.reload}
          title="Could not load the gate form"
        />
      </div>
    );
  }
  if (!query.data) {
    return (
      <div className="page page--narrow">
        <h1 className="page__title">New Goods Slip</h1>
        <LoadingState label="Loading gate form…" />
      </div>
    );
  }
  if (created) {
    return (
      <Confirmation
        created={created}
        onRetried={setCreated}
        onOpenTag={onOpenTag}
        onOpenGs={onOpenGs}
        onNew={() => {
          setCreated(null);
          setFormKey((k) => k + 1);
        }}
      />
    );
  }
  return (
    <div className="page page--narrow">
      <h1 className="page__title">New Goods Slip</h1>
      <p className="page__subtitle">Gate Inward &amp; GS Creation</p>
      <GateFormBody
        key={formKey}
        form={query.data.form}
        states={query.data.states}
        onCreated={setCreated}
      />
    </div>
  );
}

/** Stations of a state from the station master (API), cached per state. */
function useStationLookup() {
  const [byState, setByState] = useState<Record<string, LookupItem[] | 'error'>>({});
  const load = useCallback((stateId: string) => {
    if (!stateId) return;
    gsApi
      .stations(stateId)
      .then((rows) => {
        setByState((m) => ({ ...m, [stateId]: rows }));
      })
      .catch((err: unknown) => {
        console.error('Station lookup failed', err);
        setByState((m) => ({ ...m, [stateId]: 'error' }));
      });
  }, []);
  return { byState, load };
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function GateFormBody({
  form,
  states,
  onCreated,
}: {
  form: GateForm;
  states: LookupItem[];
  onCreated: (c: Created) => void;
}) {
  const stations = useStationLookup();
  const [party, setParty] = useState<PartySelection | null>(null);
  const [transporterId, setTransporterId] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocDraft[]>(() => [newDocDraft()]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [serverErrors, setServerErrors] = useState<Record<string, string[]> | undefined>();
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  // One key per GS attempt: a double tap or a retry after a lost response replays (G-16).
  const idempotencyKey = useRef(newIdempotencyKey());

  const snapshot = useMemo(
    () =>
      toDynamicFormSnapshot(
        form.snapshot,
        form.contact_phone_pattern ? { rep_contact: { regex: form.contact_phone_pattern } } : {},
      ),
    [form],
  );
  const initialValues = useMemo(() => defaultValues(form.snapshot), [form]);
  const today = form.business_today ?? undefined;
  const minEntryDate =
    today && form.max_backdate_days !== null
      ? shiftDate(today, -form.max_backdate_days)
      : undefined;
  const noDocument = values.no_document === true;
  const noDocField = form.snapshot.fields.find((f) => f.field_key === 'no_document');

  const onValuesChange = useCallback((v: Record<string, unknown>) => {
    setValues(v);
  }, []);

  const fieldRenderers: Record<
    string,
    (f: FormFieldSnapshot, api: FieldRenderApi) => React.ReactNode
  > = {
    // AMD-01: the first question, as a two-way switch (labels from the RETURN_TYPE option set).
    return_type: (f, api) => (
      <div>
        <div
          className="gate-return-type"
          role="radiogroup"
          id="field-return_type"
          aria-label={f.label}
        >
          {(f.options ?? []).map((o) => (
            <button
              key={o.code}
              type="button"
              role="radio"
              aria-checked={api.value === o.code}
              data-testid={`return-type-${o.code}`}
              className="gate-return-type__option"
              disabled={submitting}
              onClick={() => {
                api.onChange(o.code);
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
        {api.error ? (
          <p className="form-control__error" role="alert">
            {api.error}
          </p>
        ) : null}
      </div>
    ),
    // AMD-02 / DEC-38: back-dating allowed, never later than today, optional lower limit.
    gate_entry_date: (f, api) => (
      <Input
        id="field-gate_entry_date"
        type="date"
        value={typeof api.value === 'string' ? api.value : ''}
        max={today}
        min={minEntryDate}
        error={api.error}
        helperText={f.help_text ?? undefined}
        disabled={submitting}
        onChange={(e) => {
          api.onChange(e.target.value);
        }}
      />
    ),
    gate_entry_no: (_f, api) => (
      <Input
        id="field-gate_entry_no"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        value={
          typeof api.value === 'number' || typeof api.value === 'string' ? String(api.value) : ''
        }
        error={api.error}
        disabled={submitting}
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, '');
          api.onChange(digits === '' ? '' : Number(digits));
        }}
      />
    ),
    state: (_f, api) => (
      <Select
        id="field-state"
        placeholder="-- Select State / UT --"
        options={states.map((s) => ({ value: s.id, label: s.name }))}
        value={typeof api.value === 'string' ? api.value : ''}
        error={api.error}
        disabled={submitting}
        onChange={(e) => {
          api.onChange(e.target.value);
          stations.load(e.target.value);
          api.setFieldValue('station', '');
          api.setFieldValue('party_name', '');
          setParty(null);
        }}
      />
    ),
    station: (_f, api) => {
      const stateId = typeof api.values.state === 'string' ? api.values.state : '';
      const list = stations.byState[stateId];
      return (
        <Select
          id="field-station"
          placeholder={stateId ? '-- Select Station --' : '-- Select State First --'}
          options={Array.isArray(list) ? list.map((s) => ({ value: s.id, label: s.name })) : []}
          value={typeof api.value === 'string' ? api.value : ''}
          error={
            api.error ??
            (list === 'error' ? 'Could not load stations; reselect the state' : undefined)
          }
          disabled={submitting || !stateId}
          onChange={(e) => {
            api.onChange(e.target.value);
            api.setFieldValue('party_name', '');
            setParty(null);
          }}
        />
      );
    },
    // AMD-06: State → Station → Distributor.
    party_name: (_f, api) => (
      <DistributorPicker
        id="field-party_name"
        stateId={typeof api.values.state === 'string' ? api.values.state : ''}
        stationId={typeof api.values.station === 'string' ? api.values.station : ''}
        selection={party}
        error={api.error}
        disabled={submitting}
        onSelect={(sel) => {
          setParty(sel);
          api.onChange(sel ? sel.name : '');
        }}
      />
    ),
    transporter_name: (_f, api) => (
      <TransporterInput
        id="field-transporter_name"
        value={typeof api.value === 'string' ? api.value : ''}
        error={api.error}
        disabled={submitting}
        onChange={(name, id) => {
          api.onChange(name);
          setTransporterId(id);
        }}
      />
    ),
    // AMD-04: document rows, or the GS-level "no document" flag (DEC-03).
    no_document: (f, api) => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {api.value === true ? null : (
          <GateDocumentsEditor
            types={form.document_types}
            rows={docs}
            onChange={setDocs}
            errors={serverErrors}
            maxDate={today}
            disabled={submitting}
          />
        )}
        <Checkbox
          id="field-no_document"
          label={f.label}
          checked={api.value === true}
          disabled={submitting}
          onChange={(e) => {
            api.onChange(e.target.checked);
          }}
        />
        {f.help_text ? <p className="gate-hint">{f.help_text}</p> : null}
      </div>
    ),
    // DD r10: AUTO_STANDARD is the only creation format; shown read-only.
    gs_creation_format: (f, api) => (
      <Select
        id="field-gs_creation_format"
        options={(f.options ?? []).map((o) => ({ value: o.code, label: o.label }))}
        value={typeof api.value === 'string' ? api.value : ''}
        disabled
        helperText="GS number is generated automatically in the configured format"
        onChange={() => undefined}
      />
    ),
  };

  const submit = async (submitted: Record<string, unknown>) => {
    if (submitting) return;
    if (!party) {
      setServerErrors({ party_name: ['Select a distributor or create a provisional party'] });
      return;
    }
    const { state, station } = submitted;
    const rest = Object.fromEntries(
      Object.entries(submitted).filter(([k]) => !MASTER_FIELDS.has(k)),
    );
    const withDocs = submitted.no_document !== true;
    const payload: CreateGsPayload = {
      values: rest,
      documents: withDocs ? toDocumentInputs(docs) : [],
      ...(typeof state === 'string' && state ? { state_id: state } : {}),
      ...(typeof station === 'string' && station ? { station_id: station } : {}),
      ...(party.kind === 'existing'
        ? { party_id: party.id }
        : {
            provisional_party: {
              name: party.name,
              state_id: party.stateId,
              station_id: party.stationId,
            },
          }),
      ...('transporter_name' in rest && transporterId ? { transporter_id: transporterId } : {}),
    };
    setSubmitting(true);
    setSubmitError(null);
    setServerErrors(undefined);
    try {
      setPhase('Creating goods slip…');
      const result = await gsApi.create(payload, idempotencyKey.current);
      const gs = result.goods_slip;
      const items = withDocs
        ? gs.documents.flatMap((d: GateDocument, i) =>
            (docs[i]?.files ?? []).map((file) => ({ documentId: d.id, file })),
          )
        : [];
      if (items.length > 0) setPhase(`Uploading ${String(items.length)} file(s)…`);
      const failed = await uploadFiles(gs.id, items);
      onCreated({ result, failed });
    } catch (err) {
      const apiErr = toApiError(err);
      setSubmitError(apiErr);
      const fieldErrors = apiErr.fieldErrors;
      if (Object.keys(fieldErrors).length > 0) setServerErrors(fieldErrors);
    } finally {
      setSubmitting(false);
      setPhase(null);
    }
  };

  return (
    <DynamicForm
      formSnapshot={snapshot}
      initialValues={initialValues}
      onSubmit={submit}
      onValuesChange={onValuesChange}
      isSubmitting={submitting}
      submitLabel={phase ?? 'Create Goods Slip'}
      fieldRenderers={fieldRenderers}
      serverErrors={serverErrors}
      stickySubmit
      beforeSubmit={
        noDocument || submitError ? (
          <>
            {noDocument ? (
              <div className="banner" role="alert" data-testid="no-document-warning">
                <AlertTriangle size={18} aria-hidden="true" style={{ flexShrink: 0 }} />
                <span>
                  <strong>{noDocField?.label}</strong>
                  {noDocField?.help_text ? ` · ${noDocField.help_text}` : null}
                </span>
              </div>
            ) : null}
            {submitError ? (
              <div style={{ marginTop: noDocument ? '0.75rem' : 0 }}>
                <ErrorState error={submitError} title="The goods slip was not created" />
              </div>
            ) : null}
          </>
        ) : undefined
      }
    />
  );
}

function Confirmation({
  created,
  onRetried,
  onOpenTag,
  onOpenGs,
  onNew,
}: {
  created: Created;
  onRetried: (c: Created) => void;
  onOpenTag: (id: string) => void;
  onOpenGs: (id: string) => void;
  onNew: () => void;
}) {
  const { result, failed } = created;
  const gs = result.goods_slip;
  const [retrying, setRetrying] = useState(false);
  const cartons = `${String(gs.carton_count)} carton${gs.carton_count === 1 ? '' : 's'}`;
  return (
    <div className="page page--narrow" style={{ textAlign: 'center' }}>
      <CheckCircle2 size={48} color="var(--color-success)" aria-hidden="true" />
      <h1 className="page__title">Goods slip created</h1>
      <p className="gs-no-big" data-testid="created-gs-no">
        {gs.gs_no}
      </p>
      <p style={{ margin: '0 0 1rem', color: 'var(--color-muted)' }}>
        {[gs.return_type_label, gs.party_name, cartons].filter(Boolean).join(' · ')}
        {gs.gate_entry_no ? ` · Gate entry ${String(gs.gate_entry_no)}` : ''}
      </p>
      {result.warnings.map((w) => (
        <div
          key={w.code}
          className="banner"
          role="alert"
          style={{ textAlign: 'left', marginBottom: '1rem' }}
        >
          <AlertTriangle size={18} aria-hidden="true" style={{ flexShrink: 0 }} />
          <span>{w.message}</span>
        </div>
      ))}
      {failed.length > 0 ? (
        <div
          className="banner"
          role="alert"
          data-testid="gate-upload-failed"
          style={{ textAlign: 'left', marginBottom: '1rem', flexDirection: 'column' }}
        >
          <strong>
            {String(failed.length)} document file(s) were not uploaded. The goods slip is saved.
          </strong>
          <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
            {failed.map((f, i) => (
              <li key={`${f.file.name}-${String(i)}`}>
                {f.file.name}: {f.error}
              </li>
            ))}
          </ul>
          <Button
            type="button"
            variant="secondary"
            isLoading={retrying}
            onClick={() => {
              setRetrying(true);
              void uploadFiles(gs.id, failed)
                .then((still) => {
                  onRetried({ result, failed: still });
                })
                .finally(() => {
                  setRetrying(false);
                });
            }}
          >
            <RefreshCw size={16} aria-hidden="true" /> Retry uploads
          </Button>
        </div>
      ) : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={() => {
            onOpenTag(gs.id);
          }}
        >
          <Printer size={18} aria-hidden="true" /> Print tag ({cartons})
        </Button>
        <Button type="button" variant="secondary" size="lg" onClick={onNew}>
          <Plus size={18} aria-hidden="true" /> New GS
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            onOpenGs(gs.id);
          }}
        >
          View goods slip
        </Button>
      </div>
    </div>
  );
}
