/**
 * DEC-76: E-Commerce Action Sheets. One sheet per unboxing batch of ONE platform: every order id
 * with Qty Received and Qty Issue CN. E-Commerce Accounts issues one credit note per sheet when
 * its Qty Issue CN > 0; a sheet of free replacements only completes by itself.
 */
import React, { useCallback, useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { formatDateTime } from '@/features/goods-slips/format';
import '@/features/goods-slips/gateForm.css';

import { settlementApi } from './api';
import type { ActionSheetList, SheetStatus } from './types';

interface Props {
  onOpen: (sheetId: string) => void;
}

export const EcomActionSheetsPage: React.FC<Props> = ({ onOpen }) => {
  const [status, setStatus] = useState<SheetStatus | ''>('PENDING_ACCOUNTS');
  const fetcher = useCallback(() => settlementApi.sheets(status), [status]);
  const query = useApiQuery<ActionSheetList>(fetcher);
  const tabs: Array<{ code: SheetStatus | ''; label: string }> = [
    ...(query.data?.status_options ?? []).map((o) => ({
      code: o.code as SheetStatus,
      label: o.label,
    })),
    { code: '', label: 'All' },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-action-sheets">
      <PageHeader
        title="E-Commerce Action Sheets"
        subtitle="Order ids, Qty Received and Qty Issue CN per platform. Accounts issues the credit note."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      {query.data ? (
        <div className="gate-return-type" role="tablist" aria-label="Status">
          {tabs.map((t) => (
            <button
              key={t.code || 'ALL'}
              type="button"
              role="tab"
              aria-selected={status === t.code}
              aria-checked={status === t.code}
              className="gate-return-type__option"
              onClick={() => {
                setStatus(t.code);
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      ) : null}

      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the sheets" />
      ) : !query.data ? (
        <LoadingState label="Loading action sheets…" />
      ) : query.data.rows.length === 0 ? (
        <EmptyState
          title="No action sheet"
          hint="The unboxing user creates an action sheet for each platform batch."
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Action sheets">
          {query.data.rows.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                className="flex min-h-[44px] w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm dark:border-slate-800 dark:bg-slate-900"
                data-testid={`sheet-${r.sheet_no}`}
                onClick={() => {
                  onOpen(r.id);
                }}
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{r.sheet_no}</span>
                    <Badge variant="info">{r.platform_label}</Badge>
                    <Badge variant={r.status === 'COMPLETED' ? 'success' : 'warning'}>
                      {r.status_label}
                    </Badge>
                  </div>
                  <div className="text-sm text-slate-600 dark:text-slate-300">
                    {r.orders} order(s) · Qty Received {r.total_received} · Qty Issue CN{' '}
                    {r.total_cn_qty}
                    {r.cn_no ? ` · CN ${r.cn_no}` : ''}
                  </div>
                  <div className="text-xs text-slate-500">{formatDateTime(r.created_at)}</div>
                </div>
                <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
