import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { hashPath, parseHashQuery } from '@/app/router';
import type { LayoutWidget } from '@/features/dashboard/api';
import { orderForDevice, WIDGET_LINKS } from '@/features/dashboard/layout';
import { WidgetBody } from '@/features/dashboard/widgets';
import { compareTasks, groupTasks, stepScreen, type TaskItem } from '@/features/mywork/tasks';

const w = (code: string, priority: 'action' | 'insight'): LayoutWidget => ({
  code,
  title: code,
  description: null,
  size: 'M',
  priority,
  live: false,
});

describe('dashboard layout (P4-01)', () => {
  it('keeps the configured order on desktop and puts actionable widgets first on phones', () => {
    const layout = [
      w('GS_TREND', 'insight'),
      w('MY_TASKS', 'action'),
      w('CN_ISSUED', 'insight'),
      w('OPEN_PENDENCIES', 'action'),
    ];
    expect(orderForDevice(layout, false).map((x) => x.code)).toEqual([
      'GS_TREND',
      'MY_TASKS',
      'CN_ISSUED',
      'OPEN_PENDENCIES',
    ]);
    expect(orderForDevice(layout, true).map((x) => x.code)).toEqual([
      'MY_TASKS',
      'OPEN_PENDENCIES',
      'GS_TREND',
      'CN_ISSUED',
    ]);
  });

  it('builds and parses filtered list links', () => {
    expect(WIDGET_LINKS.EVIDENCE_PENDING).toBe('/gs?status=GATE_CREATED&status=UNBOXING');
    const q = parseHashQuery('#/gs?status=GATE_CREATED&status=UNBOXING&date_from=2026-11-06');
    expect(q.getAll('status')).toEqual(['GATE_CREATED', 'UNBOXING']);
    expect(q.get('date_from')).toBe('2026-11-06');
    expect(hashPath('/custody', { status: 'INITIATED', x: undefined })).toBe(
      '/custody?status=INITIATED',
    );
    expect(parseHashQuery('#/gs').toString()).toBe('');
  });

  it('renders KPI links to the matching filtered list and an explicit empty state', () => {
    const { rerender } = render(
      <WidgetBody
        code="TRANSFERS_ATTENTION"
        data={{ awaiting_acceptance: 3, in_discrepancy: 1, oldest_awaiting_at: null }}
      />,
    );
    expect(screen.getByRole('link', { name: /Awaiting acceptance/ })).toHaveAttribute(
      'href',
      '#/custody?status=INITIATED',
    );
    expect(screen.getByRole('link', { name: /In discrepancy/ })).toHaveAttribute(
      'href',
      '#/custody?status=DISCREPANCY',
    );
    rerender(<WidgetBody code="MY_TASKS" data={{ total: 0, overdue: 0, by_step: [] }} />);
    expect(screen.getByText(/No open tasks for your roles/)).toBeInTheDocument();
  });

  it('gives every chart a data table for screen readers and a visible table view', () => {
    render(
      <WidgetBody
        code="GS_PIPELINE"
        data={{
          total_open: 5,
          by_status: [
            { status: 'INSPECTION', count: 3, avg_age_days: 2.5 },
            { status: 'UNBOXING', count: 2, avg_age_days: 1 },
            { status: 'CLOSED', count: 0, avg_age_days: 0 },
          ],
        }}
      />,
    );
    const table = screen.getByRole('table', { name: 'Open goods slips by status' });
    expect(within(table).getByText('Inspection')).toBeInTheDocument();
    expect(within(table).getByText('3')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByRole('button', { name: 'Chart' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('link', { name: /Inspection/ })).toHaveAttribute(
      'href',
      '#/gs?status=INSPECTION',
    );
  });
});

const task = (over: Partial<TaskItem>): TaskItem => ({
  id: Math.random().toString(36),
  gs_id: 'g1',
  step_code: 'S1_UNBOX',
  step_label: 'Step-2 Unboxing',
  assigned_role_name: null,
  due_at: null,
  created_at: '2026-11-01T00:00:00Z',
  gs_no: 'GS/1',
  gs_status: 'UNBOXING',
  box_count: 1,
  carton_count: 1,
  missing_documentation: false,
  party_name: 'P',
  station_name: null,
  ...over,
});

describe('My Work grouping (P4-01)', () => {
  const now = new Date('2026-11-06T12:00:00Z').getTime();

  it('sorts overdue and due tasks before undated ones, oldest first', () => {
    const a = task({ id: 'a', due_at: null, created_at: '2026-10-01T00:00:00Z' });
    const b = task({ id: 'b', due_at: '2026-11-07T00:00:00Z' });
    const c = task({ id: 'c', due_at: '2026-11-05T00:00:00Z' });
    expect([a, b, c].sort(compareTasks).map((t) => t.id)).toEqual(['c', 'b', 'a']);
  });

  it('groups by step with overdue groups first', () => {
    const groups = groupTasks(
      [
        task({ step_code: 'S1_ITEMIZE', step_label: 'Itemise' }),
        task({ step_code: 'S1_UNBOX', due_at: '2026-11-05T00:00:00Z' }),
        task({ step_code: 'S1_UNBOX' }),
      ],
      now,
    );
    expect(groups.map((g) => [g.code, g.tasks.length, g.overdue])).toEqual([
      ['S1_UNBOX', 2, 1],
      ['S1_ITEMIZE', 1, 0],
    ]);
  });

  it('opens the screen that performs the step', () => {
    expect(stepScreen('S1_INSPECT', 'g9')).toBe('/gs/g9/inspection');
    expect(stepScreen('S2_HANDOVER', 'g9')).toBe('/gs/g9/handover');
    expect(stepScreen('S1_CSR_APPROVAL', 'g9')).toBe('/approvals');
    expect(stepScreen('UNKNOWN', 'g9')).toBe('/gs/g9');
  });
});
