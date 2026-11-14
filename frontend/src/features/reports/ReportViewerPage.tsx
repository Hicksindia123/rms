import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ArrowLeft, Columns3, FileDown, FileSpreadsheet, Printer, Trash2 } from 'lucide-react';

import { hashPath } from '@/app/router';
import { DataView, FilterBar, type DataViewColumn } from '@/components/erp';
import {
  Badge,
  Button,
  Checkbox,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  reportsApi,
  type ReportColumn,
  type ReportData,
  type ReportDefinition,
  type ReportParams,
  type ReportRow,
} from './api';
import { filterParams, formatCell, formatTotal, isNumeric } from './format';

interface Props {
  code: string;
  /** Query string of the hash route (filters, sort, dir, page). */
  query: URLSearchParams;
  navigate: (path: string) => void;
}

function paramsOf(query: URLSearchParams): ReportParams {
  const out: ReportParams = {};
  query.forEach((v, k) => {
    out[k] = v;
  });
  return out;
}

function errorLike(e: ApiError) {
  return { message: e.message, code: e.code, requestId: e.requestId };
}

/** Loads the definition, then renders the viewer for it. */
export function ReportViewerPage({ code, query, navigate }: Props) {
  const fetcher = useCallback(() => reportsApi.definition(code), [code]);
  const def = useApiQuery<ReportDefinition>(fetcher);

  if (def.error) {
    return (
      <div className="page">
        <BackLink
          onBack={() => {
            navigate('/reports');
          }}
        />
        <ErrorState
          title="This report could not be opened"
          error={errorLike(def.error)}
          onRetry={def.reload}
        />
      </div>
    );
  }
  if (!def.data) return <LoadingState label="Loading report…" />;
  return (
    <ReportViewer
      key={def.data.code}
      definition={def.data}
      query={query}
      navigate={navigate}
      onDefinitionChanged={def.reload}
    />
  );
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <Button type="button" variant="ghost" size="sm" onClick={onBack} className="report-back">
      <ArrowLeft size={16} aria-hidden="true" /> All reports
    </Button>
  );
}

function ReportViewer({
  definition,
  query,
  navigate,
  onDefinitionChanged,
}: {
  definition: ReportDefinition;
  query: URLSearchParams;
  navigate: (path: string) => void;
  onDefinitionChanged: () => void;
}) {
  const code = definition.code;
  const qs = query.toString();
  const filterKeys = useMemo(() => definition.filters.map((f) => f.key), [definition]);
  const params = useMemo(() => paramsOf(new URLSearchParams(qs)), [qs]);

  // Opening a report without filters applies the user's default saved filter, if any.
  const defaultSaved = definition.saved_filters.find((s) => s.is_default);
  const hasFilterParams = Object.keys(filterParams(params, filterKeys)).length > 0;
  const effectiveParams: ReportParams =
    !hasFilterParams && defaultSaved && !params.page && !params.sort
      ? { ...defaultSaved.params }
      : params;
  const effectiveQs = new URLSearchParams(effectiveParams).toString();

  const [visible, setVisible] = useState<string[]>(definition.visible_columns);
  const [columnSource, setColumnSource] = useState(definition.column_source);
  const [chooserOpen, setChooserOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  const dataFetcher = useCallback(
    () =>
      reportsApi.data(code, {
        ...Object.fromEntries(new URLSearchParams(effectiveQs)),
        page_size: String(definition.page_size),
      }),
    [code, effectiveQs, definition.page_size],
  );
  const data = useApiQuery<ReportData>(dataFetcher);

  const columnsByKey = useMemo(
    () => new Map(definition.columns.map((c) => [c.key, c] as const)),
    [definition],
  );
  const shown: ReportColumn[] = visible
    .map((k) => columnsByKey.get(k))
    .filter((c): c is ReportColumn => c !== undefined);

  const rowIndex = useMemo(
    () => new Map((data.data?.rows ?? []).map((r, i) => [r, i] as const)),
    [data.data],
  );
  const sort = data.data?.sort ?? definition.default_sort;
  const page = data.data?.page ?? 1;

  const go = (next: ReportParams) => {
    navigate(hashPath(`/reports/${code}`, next));
  };
  const applyFilters = (values: Record<string, string>) => {
    const next: ReportParams = filterParams(values, filterKeys);
    if (params.sort) next.sort = params.sort;
    if (params.dir) next.dir = params.dir;
    go(next);
  };
  const onSort = (key: string) => {
    const col = columnsByKey.get(key);
    const dir =
      sort.key === key
        ? sort.dir === 'asc'
          ? 'desc'
          : 'asc'
        : col && isNumeric(col.type)
          ? 'desc'
          : 'asc';
    go({ ...filterParams(effectiveParams, filterKeys), sort: key, dir });
  };
  const onPage = (p: number) => {
    go({ ...effectiveParams, page: String(p) });
  };

  const runAction = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(toApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const exportParams = (): ReportParams => {
    const out: ReportParams = {
      ...filterParams(effectiveParams, filterKeys),
      columns: visible.join(','),
    };
    out.sort = sort.key;
    out.dir = sort.dir;
    return out;
  };

  const tableColumns: DataViewColumn<ReportRow>[] = shown.map((c) => ({
    key: c.key,
    header: c.label,
    align: isNumeric(c.type) ? 'right' : 'left',
    sortable: c.sortable,
    render: (row) => <Cell column={c} row={row} />,
  }));

  const totals = data.data
    ? Object.fromEntries(
        shown
          .filter((c) => c.total !== null)
          .map((c) => [
            c.key,
            formatTotal(c, data.data?.totals[c.key] ?? null, data.data?.total ?? 0),
          ]),
      )
    : undefined;

  const titleCol = shown.find((c) => c.card === 1) ?? shown[0];
  const highlightCol = shown.find((c) => c.card === 2 && c !== titleCol);
  const renderCard = (row: ReportRow) => (
    <div className="report-card">
      <div className="report-card__head">
        {titleCol ? (
          <strong className="report-card__title">
            <Cell column={titleCol} row={row} />
          </strong>
        ) : null}
        {highlightCol ? (
          <span className="report-card__highlight">
            <Cell column={highlightCol} row={row} />
          </span>
        ) : null}
      </div>
      <dl className="report-card__body">
        {shown
          .filter((c) => c !== titleCol && c !== highlightCol)
          .map((c) => (
            <div key={c.key}>
              <dt>{c.label}</dt>
              <dd>
                <Cell column={c} row={row} />
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );

  const appliedCount = Object.keys(filterParams(effectiveParams, filterKeys)).length;
  const panelValues: Record<string, string> = {};
  for (const f of definition.filters) {
    const applied = data.data?.applied[f.key];
    const fromUrl = effectiveParams[f.key];
    panelValues[f.key] =
      fromUrl ??
      (applied === undefined ? '' : typeof applied === 'boolean' ? String(applied) : applied);
  }

  return (
    <div className="page page--wide report-viewer">
      <BackLink
        onBack={() => {
          navigate('/reports');
        }}
      />
      <header className="report-viewer__head">
        <div style={{ minWidth: 0 }}>
          <p className="report-viewer__group">
            {definition.group_title} · {definition.code}
          </p>
          <h2 className="page__title">{definition.title}</h2>
          {definition.description ? (
            <p className="page__subtitle">{definition.description}</p>
          ) : null}
          {definition.scope !== 'all' ? (
            <Badge variant="info">
              {definition.scope === 'own' ? 'Your own records only' : 'Your department only'}
            </Badge>
          ) : null}
        </div>
        <div className="report-viewer__actions">
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setChooserOpen(true);
            }}
          >
            <Columns3 size={16} aria-hidden="true" /> Columns
          </Button>
          {definition.can_export ? (
            <>
              <Button
                type="button"
                variant="secondary"
                isLoading={busy === 'csv'}
                disabled={busy !== null}
                onClick={() => {
                  void runAction('csv', () => reportsApi.exportFile(code, 'csv', exportParams()));
                }}
              >
                <FileDown size={16} aria-hidden="true" /> CSV
              </Button>
              <Button
                type="button"
                variant="secondary"
                isLoading={busy === 'xlsx'}
                disabled={busy !== null}
                onClick={() => {
                  void runAction('xlsx', () => reportsApi.exportFile(code, 'xlsx', exportParams()));
                }}
              >
                <FileSpreadsheet size={16} aria-hidden="true" /> Excel
              </Button>
            </>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              navigate(hashPath(`/reports/${code}/print`, exportParams()));
            }}
          >
            <Printer size={16} aria-hidden="true" /> Print
          </Button>
        </div>
      </header>

      <FilterPanel
        key={`${effectiveQs}|${data.data ? 'loaded' : 'pending'}`}
        definition={definition}
        initial={panelValues}
        activeCount={appliedCount}
        onApply={applyFilters}
        onReset={() => {
          go({});
        }}
        savedControls={
          <SavedFilters
            definition={definition}
            onApply={(p) => {
              go(p);
            }}
            onSaveRequested={() => {
              setSaveOpen(true);
            }}
            onChanged={onDefinitionChanged}
            onError={setActionError}
          />
        }
      />

      {actionError ? (
        <ErrorState
          title="That did not work"
          error={errorLike(actionError)}
          onRetry={() => {
            setActionError(null);
          }}
        />
      ) : null}

      <p className="report-viewer__meta" aria-live="polite">
        {data.data
          ? `${data.data.total.toLocaleString('en-IN')} row${data.data.total === 1 ? '' : 's'}`
          : ' '}
        {columnSource !== 'default' ? (
          <span> · columns: {columnSource === 'user' ? 'your choice' : 'role default'}</span>
        ) : null}
      </p>

      <DataView<ReportRow>
        rows={data.data?.rows ?? null}
        rowKey={(row) => `${String(page)}-${String(rowIndex.get(row) ?? 0)}`}
        columns={tableColumns}
        renderCard={renderCard}
        loading={data.loading}
        error={data.error ? errorLike(data.error) : null}
        onRetry={data.reload}
        emptyTitle="No rows match these filters"
        emptyHint="Widen the date range or reset the filters."
        page={page}
        pageSize={data.data?.page_size ?? definition.page_size}
        {...(data.data ? { total: data.data.total } : {})}
        onPageChange={onPage}
        sort={sort}
        onSort={onSort}
        {...(totals ? { totals } : {})}
      />

      <ColumnChooser
        isOpen={chooserOpen}
        definition={definition}
        visible={visible}
        onClose={() => {
          setChooserOpen(false);
        }}
        onApply={(cols) => {
          setVisible(cols);
          setChooserOpen(false);
        }}
        onSaved={(cols, source) => {
          setVisible(cols);
          setColumnSource(source);
          setChooserOpen(false);
        }}
      />

      <SaveFilterModal
        isOpen={saveOpen}
        code={code}
        params={filterParams(panelValues, filterKeys)}
        onClose={() => {
          setSaveOpen(false);
        }}
        onSaved={() => {
          setSaveOpen(false);
          onDefinitionChanged();
        }}
      />
    </div>
  );
}

function Cell({ column, row }: { column: ReportColumn; row: ReportRow }) {
  const value = row[column.key] ?? null;
  const text = formatCell(column.type, value);
  const link = row._links?.[column.key];
  if (link) {
    return (
      <a className="report-link" href={`#${link}`}>
        {text}
      </a>
    );
  }
  if (column.type === 'bool' && value === true) return <Badge variant="warning">{text}</Badge>;
  return <>{text}</>;
}

function FilterPanel({
  definition,
  initial,
  activeCount,
  onApply,
  onReset,
  savedControls,
}: {
  definition: ReportDefinition;
  initial: Record<string, string>;
  activeCount: number;
  onApply: (values: Record<string, string>) => void;
  onReset: () => void;
  savedControls: ReactNode;
}) {
  const [draft, setDraft] = useState(initial);
  if (definition.filters.length === 0) return null;
  return (
    <FilterBar
      idPrefix={`rf-${definition.code}`}
      fields={definition.filters}
      values={draft}
      onChange={setDraft}
      onApply={() => {
        onApply(draft);
      }}
      onReset={onReset}
      activeCount={activeCount}
      extra={savedControls}
    />
  );
}

function SavedFilters({
  definition,
  onApply,
  onSaveRequested,
  onChanged,
  onError,
}: {
  definition: ReportDefinition;
  onApply: (params: ReportParams) => void;
  onSaveRequested: () => void;
  onChanged: () => void;
  onError: (e: ApiError) => void;
}) {
  const [selected, setSelected] = useState('');
  const saved = definition.saved_filters;
  const current = saved.find((s) => s.id === selected);
  return (
    <div className="saved-filters">
      {saved.length > 0 ? (
        <div className="saved-filters__pick">
          <label className="form-label" htmlFor={`sf-${definition.code}`}>
            Saved filters
          </label>
          <Select
            id={`sf-${definition.code}`}
            value={selected}
            placeholder="Choose…"
            options={saved.map((s) => ({
              value: s.id,
              label: s.is_default ? `${s.name} (default)` : s.name,
            }))}
            onChange={(e) => {
              setSelected(e.target.value);
              const s = saved.find((x) => x.id === e.target.value);
              if (s) onApply(s.params);
            }}
          />
        </div>
      ) : null}
      <Button type="button" variant="ghost" onClick={onSaveRequested}>
        Save these filters…
      </Button>
      {current ? (
        <Button
          type="button"
          variant="ghost"
          aria-label={`Delete saved filter ${current.name}`}
          onClick={() => {
            reportsApi.deleteFilter(definition.code, current.id).then(
              () => {
                setSelected('');
                onChanged();
              },
              (err: unknown) => {
                onError(toApiError(err));
              },
            );
          }}
        >
          <Trash2 size={16} aria-hidden="true" /> Delete
        </Button>
      ) : null}
    </div>
  );
}

function ColumnChooser({
  isOpen,
  definition,
  visible,
  onClose,
  onApply,
  onSaved,
}: {
  isOpen: boolean;
  definition: ReportDefinition;
  visible: string[];
  onClose: () => void;
  onApply: (cols: string[]) => void;
  onSaved: (cols: string[], source: ReportDefinition['column_source']) => void;
}) {
  return isOpen ? (
    <ColumnChooserBody
      definition={definition}
      visible={visible}
      onClose={onClose}
      onApply={onApply}
      onSaved={onSaved}
    />
  ) : null;
}

function ColumnChooserBody({
  definition,
  visible,
  onClose,
  onApply,
  onSaved,
}: {
  definition: ReportDefinition;
  visible: string[];
  onClose: () => void;
  onApply: (cols: string[]) => void;
  onSaved: (cols: string[], source: ReportDefinition['column_source']) => void;
}) {
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(visible));
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const ordered = definition.columns.map((c) => c.key).filter((k) => chosen.has(k));

  const save = (
    fn: () => Promise<{
      visible_columns: string[];
      column_source: ReportDefinition['column_source'];
    }>,
  ) => {
    setSaving(true);
    setError(null);
    fn().then(
      (res) => {
        setSaving(false);
        onSaved(res.visible_columns, res.column_source);
      },
      (err: unknown) => {
        setSaving(false);
        setError(toApiError(err));
      },
    );
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title="Choose columns"
      footer={
        <div className="column-chooser__footer">
          <Button
            type="button"
            variant="ghost"
            disabled={saving}
            onClick={() => {
              save(() => reportsApi.resetColumns(definition.code));
            }}
          >
            Reset to default
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={saving || ordered.length === 0}
            onClick={() => {
              save(() => reportsApi.saveColumns(definition.code, ordered));
            }}
          >
            Save as my default
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={ordered.length === 0}
            onClick={() => {
              onApply(ordered);
            }}
          >
            Apply
          </Button>
        </div>
      }
    >
      {error ? <ErrorState error={errorLike(error)} /> : null}
      <fieldset className="column-chooser">
        <legend className="sr-only">Visible columns</legend>
        {definition.columns.map((c) => (
          <Checkbox
            key={c.key}
            id={`cc-${definition.code}-${c.key}`}
            label={c.label}
            checked={chosen.has(c.key)}
            onChange={(e) => {
              const next = new Set(chosen);
              if (e.target.checked) next.add(c.key);
              else next.delete(c.key);
              setChosen(next);
            }}
          />
        ))}
      </fieldset>
      {ordered.length === 0 ? (
        <p className="form-control__error" role="alert">
          Choose at least one column.
        </p>
      ) : null}
    </Modal>
  );
}

function SaveFilterModal({
  isOpen,
  code,
  params,
  onClose,
  onSaved,
}: {
  isOpen: boolean;
  code: string;
  params: ReportParams;
  onClose: () => void;
  onSaved: () => void;
}) {
  if (!isOpen) return null;
  return <SaveFilterBody code={code} params={params} onClose={onClose} onSaved={onSaved} />;
}

function SaveFilterBody({
  code,
  params,
  onClose,
  onSaved,
}: {
  code: string;
  params: ReportParams;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = () => {
    setSaving(true);
    setError(null);
    reportsApi.saveFilter(code, { name: name.trim(), params, is_default: isDefault }).then(
      () => {
        setSaving(false);
        onSaved();
      },
      (err: unknown) => {
        setSaving(false);
        setError(toApiError(err));
      },
    );
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title="Save filters"
      size="sm"
      footer={
        <Button
          type="button"
          variant="primary"
          isLoading={saving}
          disabled={name.trim() === ''}
          onClick={submit}
        >
          Save
        </Button>
      }
    >
      {error ? <ErrorState error={errorLike(error)} /> : null}
      <label className="form-label" htmlFor={`sfn-${code}`}>
        Name
      </label>
      <Input
        id={`sfn-${code}`}
        value={name}
        maxLength={80}
        onChange={(e) => {
          setName(e.target.value);
        }}
      />
      <Checkbox
        id={`sfd-${code}`}
        label="Open this report with these filters by default"
        checked={isDefault}
        onChange={(e) => {
          setIsDefault(e.target.checked);
        }}
      />
      <p className="form-control__helper">
        {Object.keys(params).length === 0
          ? 'No filters are set: the saved filter shows everything.'
          : `${String(Object.keys(params).length)} filter value(s) will be saved.`}
      </p>
    </Modal>
  );
}
