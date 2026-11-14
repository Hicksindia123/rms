import { useCallback } from 'react';
import { ChevronRight, FileBarChart } from 'lucide-react';

import { EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';

import { reportsApi, type ReportGroup } from './api';

interface Props {
  onOpen: (code: string) => void;
}

/** P4-02 report catalogue: grouped, only the reports the API says you may run. */
export function ReportsCataloguePage({ onOpen }: Props) {
  const fetcher = useCallback(() => reportsApi.catalogue(), []);
  const { data, error, loading, reload } = useApiQuery<ReportGroup[]>(fetcher);

  return (
    <div className="page report-catalogue">
      <h2 className="page__title">Reports &amp; MIS</h2>
      <p className="page__subtitle">
        Operational reports with filters, totals, CSV / Excel export and printing.
      </p>
      {error ? (
        <ErrorState
          title="Reports could not be loaded"
          error={{ message: error.message, code: error.code, requestId: error.requestId }}
          onRetry={reload}
        />
      ) : loading && !data ? (
        <LoadingState label="Loading reports…" />
      ) : !data || data.length === 0 ? (
        <EmptyState
          title="No reports available"
          hint="Your roles do not include any report. Ask an administrator for report access."
        />
      ) : (
        data.map((group) => (
          <section key={group.code} className="report-group" aria-labelledby={`rg-${group.code}`}>
            <h3 id={`rg-${group.code}`} className="report-group__title">
              {group.title}
            </h3>
            <ul className="report-group__list">
              {group.reports.map((r) => (
                <li key={r.code}>
                  <button
                    type="button"
                    className="report-tile"
                    onClick={() => {
                      onOpen(r.code);
                    }}
                  >
                    <FileBarChart size={20} aria-hidden="true" className="report-tile__icon" />
                    <span className="report-tile__text">
                      <span className="report-tile__title">
                        <span className="report-tile__code">{r.code}</span> {r.title}
                      </span>
                      {r.description ? (
                        <span className="report-tile__desc">{r.description}</span>
                      ) : null}
                    </span>
                    <ChevronRight size={18} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
