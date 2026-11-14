import { formatDateTime, humanize } from '@/features/goods-slips/format';

import type { CellValue, ColumnType, ReportColumn, ReportParams } from './api';

const INT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const ONE = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const TWO = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function asNumber(value: CellValue): number | null {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return null;
}

/** Display text for a report cell (system codes are humanised, never relabelled). */
export function formatCell(type: ColumnType, value: CellValue): string {
  if (value === null || value === '') return '—';
  if (type === 'bool') return value === true ? 'Yes' : value === false ? 'No' : String(value);
  if (type === 'date' && typeof value === 'string') {
    const [y, m, d] = value.slice(0, 10).split('-');
    return y && m && d ? `${d}-${m}-${y}` : value;
  }
  if (type === 'datetime' && typeof value === 'string') return formatDateTime(value);
  if (type === 'code' && typeof value === 'string') {
    return value
      .split(', ')
      .map((v) => humanize(v))
      .join(', ');
  }
  const n = asNumber(value);
  if (n !== null) {
    if (type === 'int') return INT.format(n);
    if (type === 'money') return `₹${TWO.format(n)}`;
    if (type === 'decimal') return TWO.format(n);
    if (type === 'hours' || type === 'days') return ONE.format(n);
    if (type === 'percent') return `${ONE.format(n)}%`;
  }
  return String(value);
}

/** Totals-row text: count_true shows "x of n", averages are marked. */
export function formatTotal(col: ReportColumn, value: CellValue, rows: number): string {
  if (col.total === null) return '';
  if (value === null) return '—';
  if (col.total === 'count_true') return `${formatCell('int', value)} of ${INT.format(rows)}`;
  const type: ColumnType = col.type === 'bool' ? 'int' : col.type;
  const text = formatCell(type, value);
  if (col.total === 'avg') return `avg ${text}`;
  if (col.total === 'max') return `max ${text}`;
  return text;
}

export function isNumeric(type: ColumnType): boolean {
  return ['int', 'decimal', 'money', 'hours', 'days', 'percent'].includes(type);
}

/** Only filter values (no paging / sorting / columns) — for saved filters and "filters used". */
export function filterParams(params: ReportParams, filterKeys: string[]): ReportParams {
  const out: ReportParams = {};
  for (const key of filterKeys) {
    const v = params[key];
    if (v !== undefined && v !== '') out[key] = v;
  }
  return out;
}
