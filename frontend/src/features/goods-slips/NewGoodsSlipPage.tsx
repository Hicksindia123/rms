import { useCallback, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Plus, Printer, RefreshCw, Trash2 } from 'lucide-react';

import { DynamicForm } from '@/components/erp';
import type { FieldRenderApi } from '@/components/erp';
import { Button, Checkbox, Drawer, ErrorState, Input, LoadingState, Select } from '@/components/ui';
import type { FormFieldSnapshot } from '@/features/config/forms/types';
import { useApiQuery } from '@/hooks/useApiQuery';
import { evaluateRule } from '@/lib/rules';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import {
  gsApi,
  type CreateGsPayload,
  type GateDocument,
  type GateDocumentInput,
  type GateForm,
  type GateInwardResult,
  type LookupItem,
} from './api';
import { DistributorPicker } from './DistributorPicker';
import { GateDocumentsEditor } from './GateDocumentsEditor';
import { GateDocsV4Editor } from './GateDocsV4Editor';
import {
  NO_DOCUMENT_CHOICE,
  checkDocRows,
  newDocDraft,
  toDocumentInputs,
  type DocDraft,
} from './gateDocs';
import {
  uploadDocumentFiles as uploadFiles,
  type PendingFile,
  type UploadItem,
} from './gateUploads';
import { TransporterInput } from './GatePickers';
import type { PartySelection } from './useStations';
import { defaultValues, optionOf, toDynamicFormSnapshot } from './snapshot';
import './gateForm.css';

// Which return type shows the gate entry fields is configured on the form version (visible_when on
// the RETURN_TYPE code, AMD-02 / DEC-39); nothing here keys off labels (CLAUDE.md rule e).
const MASTER_FIELDS: ReadonlySet<string> = new Set(['party_name', 'state', 'station']);
/** DEC-62: gate form v4 is recognised by this field (as the backend does). */
const V4_MARKER_FIELD = 'transport_document';
/** Fields the summary sheet shows in their own way (party/state/station, documents, format). */
const SUMMARY_SKIP: ReadonlySet<string> = new Set([
  'party_name',
  'state',
  'station',
  'no_document',
  V4_MARKER_FIELD,
  'gs_creation_format',
]);

interface Props {
  onOpenTag: (gsId: string) => void;
  onOpenGs: (gsId: string) => void;
  /**
   * DEC-73: Return Type = E-Commerce has its own gate form. A function opens it; `null` hides the
   * E-Commerce option (user without ecommerce_returns.create). Left out, the switch behaves as
   * before (legacy DEC-39 path; tests).
   */
  onEcommerce?: (() => void) | null;
}

/** DEC-73: stable RETURN_TYPE code (labels come from the option set). */
const ECOMMERCE_RETURN = 'ECOMMERCE_RETURN';

interface Created {
  result: GateInwardResult;
  failed: PendingFile[];
}

/** Step-1 gate inward (P2-02; form v2 per change plan 2026-11-12 Phase 2; v4 per DEC-62):
 * mobile-first GS creation at the gate. Labels, options, required rules and document types all
 * come from the published S1_GATE_INWARD form version and the document option sets.
 * "Submit & Create GS" opens a summary sheet; the GS is created only from that sheet. */
export function NewGoodsSlipPage({ onOpenTag, onOpenGs, onEcommerce }: Props) {
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
        onChanged={setCreated}
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
        onEcommerce={onEcommerce}
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

/** What the summary sheet shows and what Submit sends. */
interface Review {
  payload: CreateGsPayload;
  rows: Array<{ label: string; value: string }>;
  /** Files to upload once the GS exists, by position in `payload.documents`. */
  files: Array<{ docIndex: number; file: File }>;
}

type RowErrors = Record<string, { type?: string; files?: string }>;

function GateFormBody({
  form,
  states,
  onCreated,
  onEcommerce,
}: {
  form: GateForm;
  states: LookupItem[];
  onCreated: (c: Created) => void;
  onEcommerce?: (() => void) | null | undefined;
}) {
  const isV4 = form.snapshot.fields.some((f) => f.field_key === V4_MARKER_FIELD);
  const stations = useStationLookup();
  const [party, setParty] = useState<PartySelection | null>(null);
  const [transporterId, setTransporterId] = useState<string | null>(null);
  // v1–v3: one empty row to start with; v4: documents are optional (DEC-62).
  const [docs, setDocs] = useState<DocDraft[]>(() => (isV4 ? [] : [newDocDraft()]));
  const [transportDocs, setTransportDocs] = useState<DocDraft[]>([]);
  const [rowErrors, setRowErrors] = useState<RowErrors>({});
  const [serverErrors, setServerErrors] = useState<Record<string, string[]> | undefined>();
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [sheetError, setSheetError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploads, setUploads] = useState<Array<{ name: string; percent: number }> | null>(null);
  // One key per summary sheet: a double tap on Submit, or a retry after a lost response, replays
  // the same request (G-16). A new key is made each time the sheet opens.
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
  const fieldLabel = (key: string, fallback: string) =>
    form.snapshot.fields.find((f) => f.field_key === key)?.label ?? fallback;
  const transportTypes = form.transport_document_types ?? [];

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
          {(f.options ?? [])
            .filter((o) => !(o.code === ECOMMERCE_RETURN && onEcommerce === null))
            .map((o) => (
              <button
                key={o.code}
                type="button"
                role="radio"
                aria-checked={api.value === o.code}
                data-testid={`return-type-${o.code}`}
                className="gate-return-type__option"
                disabled={submitting}
                onClick={() => {
                  if (o.code === ECOMMERCE_RETURN && onEcommerce) {
                    onEcommerce();
                    return;
                  }
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
    // Whole cartons only (AMD-03 / DEC-62: integer ≥ 1).
    carton_count: (f, api) => (
      <Input
        id="field-carton_count"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        value={
          typeof api.value === 'number' || typeof api.value === 'string' ? String(api.value) : ''
        }
        error={api.error}
        helperText={f.help_text ?? undefined}
        disabled={submitting}
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, '');
          api.onChange(digits === '' ? null : Number(digits));
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
    no_document: isV4
      ? // DEC-62: "Documents From Party" rows, or the "No Documents From Party" choice (BR-03).
        (f, api) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {f.help_text ? <p className="gate-hint">{f.help_text}</p> : null}
            <GateDocsV4Editor
              idPrefix="party"
              rowNoun="Party document"
              types={form.document_types}
              rows={docs}
              onChange={setDocs}
              noDocument={{
                label: optionOf(form.snapshot, 'no_document', NO_DOCUMENT_CHOICE)?.label ?? f.label,
                checked: api.value === true,
                onChange: (checked) => {
                  api.onChange(checked);
                  if (checked) setDocs([]);
                },
              }}
              rowErrors={rowErrors}
              serverErrors={serverErrors}
              offset={0}
              disabled={submitting}
            />
            {serverErrors?.documents?.[0] ? (
              <p className="form-control__error" role="alert">
                {serverErrors.documents[0]}
              </p>
            ) : null}
          </div>
        )
      : // AMD-04 (v2/v3): document rows, or the GS-level "no document" flag (DEC-03).
        (f, api) => (
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
    // DEC-62: "Documents From Transport" rows (courier slip + photo).
    [V4_MARKER_FIELD]: (f) => (
      <div id={`field-${V4_MARKER_FIELD}`}>
        {f.help_text ? <p className="gate-hint">{f.help_text}</p> : null}
        <GateDocsV4Editor
          idPrefix="transport"
          rowNoun="Transport document"
          types={transportTypes}
          rows={transportDocs}
          onChange={setTransportDocs}
          rowErrors={rowErrors}
          serverErrors={serverErrors}
          offset={docs.length}
          disabled={submitting}
        />
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

  /** Values shown on the summary sheet, labelled from the form snapshot (rule e). */
  const summaryRows = (submitted: Record<string, unknown>, sel: PartySelection) => {
    const stateId = typeof submitted.state === 'string' ? submitted.state : '';
    const stationList = stations.byState[stateId];
    const stationName = Array.isArray(stationList)
      ? stationList.find((s) => s.id === submitted.station)?.name
      : undefined;
    const rows: Array<{ label: string; value: string }> = [
      {
        label: fieldLabel('party_name', 'Party'),
        value: sel.kind === 'existing' ? sel.name : `${sel.name} (new party)`,
      },
      {
        label: fieldLabel('state', 'State'),
        value: states.find((s) => s.id === stateId)?.name ?? '—',
      },
      { label: fieldLabel('station', 'Station'), value: stationName ?? '—' },
    ];
    for (const f of form.snapshot.fields) {
      if (SUMMARY_SKIP.has(f.field_key)) continue;
      const raw = submitted[f.field_key];
      if (raw === undefined || raw === null || raw === '') continue;
      if (!evaluateRule(f.visible_when ?? null, submitted)) continue;
      const opt = optionOf(form.snapshot, f.field_key, raw);
      rows.push({
        label: f.label,
        value: opt ? opt.label : typeof raw === 'string' ? raw : JSON.stringify(raw),
      });
    }
    return rows;
  };

  const openSummary = (submitted: Record<string, unknown>) => {
    if (submitting) return;
    if (!party) {
      setServerErrors({ party_name: ['Select a distributor or create a provisional party'] });
      return;
    }
    const noDocument = submitted.no_document === true;
    const partyRows = noDocument ? [] : docs;
    if (isV4) {
      const errs = { ...checkDocRows(partyRows), ...checkDocRows(transportDocs) };
      setRowErrors(errs);
      if (Object.keys(errs).length > 0) return;
    }
    const { state, station } = submitted;
    const rest = Object.fromEntries(
      Object.entries(submitted).filter(([k]) => !MASTER_FIELDS.has(k)),
    );
    const documents: GateDocumentInput[] = isV4
      ? [
          ...partyRows.map((r) => ({ doc_type_code: r.doc_type_code, source: 'PARTY' as const })),
          ...transportDocs.map((r) => ({
            doc_type_code: r.doc_type_code,
            source: 'TRANSPORT' as const,
          })),
        ]
      : toDocumentInputs(partyRows);
    const fileRows = isV4 ? [...partyRows, ...transportDocs] : partyRows;
    const payload: CreateGsPayload = {
      values: rest,
      documents,
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
    const typeLabel = (code: string) =>
      [...form.document_types, ...transportTypes].find((t) => t.code === code)?.label ?? code;
    const describe = (rows: DocDraft[]) =>
      rows.length === 0
        ? 'None'
        : `${String(rows.length)} (${rows.map((r) => typeLabel(r.doc_type_code)).join(', ')})`;
    const noDocLabel =
      optionOf(form.snapshot, 'no_document', NO_DOCUMENT_CHOICE)?.label ??
      fieldLabel('no_document', 'No documents');
    const docRows = isV4
      ? [
          {
            label:
              form.snapshot.fields.find((f) => f.field_key === 'no_document')?.section ??
              'Documents',
            value: noDocument ? noDocLabel : describe(partyRows),
          },
          {
            label: fieldLabel(V4_MARKER_FIELD, 'Transport documents'),
            value: describe(transportDocs),
          },
        ]
      : [{ label: 'Documents', value: noDocument ? noDocLabel : describe(partyRows) }];
    idempotencyKey.current = newIdempotencyKey();
    setSheetError(null);
    setSubmitError(null);
    setServerErrors(undefined);
    setReview({
      payload,
      rows: [...summaryRows(submitted, party), ...docRows],
      files: fileRows.flatMap((r, docIndex) => r.files.map((file) => ({ docIndex, file }))),
    });
  };

  const submit = async () => {
    if (!review || submitting) return;
    setSubmitting(true);
    setSheetError(null);
    try {
      const result = await gsApi.create(review.payload, idempotencyKey.current);
      const gs = result.goods_slip;
      const items: UploadItem[] = review.files.flatMap(({ docIndex, file }) => {
        const doc: GateDocument | undefined = gs.documents[docIndex];
        return doc ? [{ documentId: doc.id, file }] : [];
      });
      setUploads(items.map((i) => ({ name: i.file.name, percent: 0 })));
      const failed = await uploadFiles(gs.id, items, (index, percent) => {
        setUploads((u) => (u ? u.map((x, j) => (j === index ? { ...x, percent } : x)) : u));
      });
      onCreated({ result, failed });
    } catch (err) {
      const apiErr = toApiError(err);
      const fieldErrors = apiErr.fieldErrors;
      if (Object.keys(fieldErrors).length > 0) {
        // Back to the form, with every field error shown next to its field and the button.
        setServerErrors(fieldErrors);
        setSubmitError(apiErr);
        setReview(null);
      } else {
        // Network / server error: stay on the sheet; Submit again replays the same key (G-16).
        setSheetError(apiErr);
      }
    } finally {
      setSubmitting(false);
      setUploads(null);
    }
  };

  const closeSheet = () => {
    if (!submitting) setReview(null);
  };

  return (
    <>
      <DynamicForm
        formSnapshot={snapshot}
        initialValues={initialValues}
        onSubmit={openSummary}
        isSubmitting={submitting}
        submitLabel={isV4 ? 'Submit & Create GS' : 'Create Goods Slip'}
        fieldRenderers={fieldRenderers}
        serverErrors={serverErrors}
        stickySubmit
        beforeSubmit={
          submitError ? (
            <>
              <ErrorState error={submitError} title="The goods slip was not created" />
              <FieldErrorList
                errors={submitError.fieldErrors}
                form={form}
                partyCount={docs.length}
              />
            </>
          ) : Object.keys(rowErrors).length > 0 ? (
            <p className="form-control__error" role="alert" data-testid="gate-doc-row-errors">
              Complete or remove the highlighted document rows.
            </p>
          ) : undefined
        }
      />
      <Drawer
        isOpen={review !== null}
        onClose={closeSheet}
        title="Check before creating the GS"
        subtitle="The goods slip is created only when you tap Submit."
        footer={
          <div className="gate-summary__actions">
            <Button
              type="button"
              variant="secondary"
              size="lg"
              disabled={submitting}
              onClick={closeSheet}
            >
              Back to edit
            </Button>
            <Button
              type="button"
              variant="primary"
              size="lg"
              isLoading={submitting}
              onClick={() => {
                void submit();
              }}
            >
              Submit
            </Button>
          </div>
        }
      >
        {review ? (
          <div className="gate-summary" data-testid="gate-summary">
            <dl className="gate-summary__list">
              {review.rows.map((r) => (
                <div key={r.label} className="gate-summary__row">
                  <dt>{r.label}</dt>
                  <dd>{r.value}</dd>
                </div>
              ))}
            </dl>
            {review.files.length > 0 ? (
              <p className="gate-hint">
                {String(review.files.length)} file(s) will be uploaded after the GS is created.
              </p>
            ) : null}
            {uploads && uploads.length > 0 ? (
              <ul
                className="gate-uploads"
                aria-label="Upload progress"
                data-testid="gate-upload-progress"
              >
                {uploads.map((u, i) => (
                  <li key={`${u.name}-${String(i)}`}>
                    <span className="gate-uploads__name">{u.name}</span>
                    <progress max={100} value={u.percent} aria-label={`Uploading ${u.name}`} />
                    <span className="gate-uploads__pct">{String(u.percent)}%</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {sheetError ? (
              <ErrorState
                error={sheetError}
                title="The goods slip was not created"
                onRetry={() => {
                  void submit();
                }}
              />
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </>
  );
}

/** Every server field error next to the submit button, labelled from the form snapshot, so a
 * problem on a field scrolled out of view (or not rendered, e.g. `documents`) is never hidden. */
function FieldErrorList({
  errors,
  form,
  partyCount,
}: {
  errors: Record<string, string[]>;
  form: GateForm;
  partyCount: number;
}) {
  const entries = Object.entries(errors).filter(([, msgs]) => msgs.length > 0);
  if (entries.length === 0) return null;
  const isV4 = form.snapshot.fields.some((f) => f.field_key === V4_MARKER_FIELD);
  const labelOf = (key: string) => {
    const doc = /^documents\.(\d+)\./.exec(key);
    if (doc) {
      const i = Number(doc[1]);
      if (!isV4) return `Document ${String(i + 1)}`;
      return i < partyCount
        ? `Party document ${String(i + 1)}`
        : `Transport document ${String(i - partyCount + 1)}`;
    }
    if (key === 'documents') return 'Documents';
    return form.snapshot.fields.find((f) => f.field_key === key)?.label ?? key;
  };
  return (
    <ul className="gate-field-errors" data-testid="gate-field-errors">
      {entries.map(([key, msgs]) => (
        <li key={key}>
          <strong>{labelOf(key)}:</strong> {msgs.join('; ')}
        </li>
      ))}
    </ul>
  );
}

function Confirmation({
  created,
  onChanged,
  onOpenTag,
  onOpenGs,
  onNew,
}: {
  created: Created;
  onChanged: (c: Created) => void;
  onOpenTag: (id: string) => void;
  onOpenGs: (id: string) => void;
  onNew: () => void;
}) {
  const { result, failed } = created;
  const gs = result.goods_slip;
  const [retrying, setRetrying] = useState<number | 'all' | null>(null);
  const cartons = `${String(gs.carton_count)} carton${gs.carton_count === 1 ? '' : 's'}`;
  const retry = (which: number | 'all') => {
    const items = which === 'all' ? failed : failed.filter((_, i) => i === which);
    setRetrying(which);
    void uploadFiles(gs.id, items)
      .then((still) => {
        const rest = which === 'all' ? [] : failed.filter((_, i) => i !== which);
        onChanged({ result, failed: [...rest, ...still] });
      })
      .finally(() => {
        setRetrying(null);
      });
  };
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
          <ul className="gate-failed">
            {failed.map((f, i) => (
              <li key={`${f.file.name}-${String(i)}`}>
                <span className="gate-failed__name">
                  {f.file.name}: {f.error}
                </span>
                <span className="gate-failed__actions">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    isLoading={retrying === i}
                    disabled={retrying !== null}
                    aria-label={`Retry ${f.file.name}`}
                    onClick={() => {
                      retry(i);
                    }}
                  >
                    <RefreshCw size={16} aria-hidden="true" /> Retry
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={retrying !== null}
                    aria-label={`Remove ${f.file.name}`}
                    onClick={() => {
                      onChanged({ result, failed: failed.filter((_, j) => j !== i) });
                    }}
                  >
                    <Trash2 size={16} aria-hidden="true" /> Remove
                  </Button>
                </span>
              </li>
            ))}
          </ul>
          {failed.length > 1 ? (
            <Button
              type="button"
              variant="secondary"
              isLoading={retrying === 'all'}
              disabled={retrying !== null}
              onClick={() => {
                retry('all');
              }}
            >
              <RefreshCw size={16} aria-hidden="true" /> Retry all
            </Button>
          ) : null}
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
          <Printer size={18} aria-hidden="true" /> Print GS Tag ({cartons})
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
