import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataView, FilterBar } from '@/components/erp';
import type { ReportColumn } from '@/features/reports/api';
import { filterParams, formatCell, formatTotal, isNumeric } from '@/features/reports/format';

const col = (over: Partial<ReportColumn>): ReportColumn => ({
  key: 'k',
  label: 'K',
  type: 'int',
  default: true,
  total: null,
  has_link: false,
  card: 0,
  sortable: true,
  ...over,
});

describe('report formatting (P4-02)', () => {
  it('formats each column type', () => {
    expect(formatCell('int', 123456)).toBe('1,23,456');
    expect(formatCell('money', 1180)).toBe('₹1,180.00');
    expect(formatCell('hours', '2.25')).toBe('2.3');
    expect(formatCell('percent', 11.76)).toBe('11.8%');
    expect(formatCell('date', '2026-11-06')).toBe('06-11-2026');
    expect(formatCell('bool', true)).toBe('Yes');
    expect(formatCell('code', 'GATE_CREATED, OPEN_PENDENCY')).toBe('Gate created, Open pendency');
    expect(formatCell('text', null)).toBe('—');
    expect(isNumeric('money') && !isNumeric('code')).toBe(true);
  });

  it('formats totals by kind', () => {
    expect(formatTotal(col({ total: 'sum' }), 10, 3)).toBe('10');
    expect(formatTotal(col({ total: 'avg', type: 'hours' }), 1.5, 3)).toBe('avg 1.5');
    expect(formatTotal(col({ total: 'count_true', type: 'bool' }), 2, 30)).toBe('2 of 30');
    expect(formatTotal(col({ total: 'ratio', type: 'percent' }), 11.8, 3)).toBe('11.8%');
    expect(formatTotal(col({ total: null }), 5, 3)).toBe('');
  });

  it('keeps only filter values for saved filters', () => {
    expect(
      filterParams({ status: 'CLOSED', page: '2', sort: 'gs_no', party: '' }, ['status', 'party']),
    ).toEqual({ status: 'CLOSED' });
  });
});

describe('DataView sorting and totals (P4-02)', () => {
  it('renders sortable headers with aria-sort and a totals row', () => {
    const onSort = vi.fn();
    render(
      <DataView<{ id: string; qty: number }>
        rows={[{ id: 'a', qty: 3 }]}
        rowKey={(r) => r.id}
        columns={[
          { key: 'id', header: 'Id', render: (r) => r.id, sortable: true },
          { key: 'qty', header: 'Qty', render: (r) => r.qty, sortable: true, align: 'right' },
        ]}
        renderCard={(r) => r.id}
        emptyTitle="none"
        sort={{ key: 'qty', dir: 'desc' }}
        onSort={onSort}
        totals={{ qty: '3' }}
      />,
    );
    expect(screen.getAllByRole('columnheader')[1]).toHaveAttribute('aria-sort', 'descending');
    fireEvent.click(screen.getByRole('button', { name: /^Id/ }));
    expect(onSort).toHaveBeenCalledWith('id');
    expect(screen.getByText('Totals')).toBeInTheDocument();
  });
});

describe('FilterBar (P4-02)', () => {
  it('edits values and applies them', () => {
    // jsdom has no matchMedia: report a desktop viewport (inline filter bar).
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const onChange = vi.fn();
    const onApply = vi.fn();
    render(
      <FilterBar
        idPrefix="t"
        fields={[
          {
            key: 'status',
            label: 'Status',
            type: 'enum',
            choices: [{ value: 'CLOSED', label: 'CLOSED' }],
          },
          { key: 'hazard', label: 'Hazard only', type: 'bool' },
        ]}
        values={{}}
        onChange={onChange}
        onApply={onApply}
        onReset={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'CLOSED' } });
    expect(onChange).toHaveBeenCalledWith({ status: 'CLOSED' });
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(onApply).toHaveBeenCalled();
  });
});
