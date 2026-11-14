import { hashPath } from '@/app/router';

import type { LayoutWidget } from './api';

export const CHART_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)'] as const;

/** The list screen a widget opens (the card's "Open" link). */
export const WIDGET_LINKS: Record<string, string> = {
  MY_TASKS: '/mywork',
  GS_PIPELINE: '/gs',
  GATE_INWARDS_TODAY: '/gs',
  EVIDENCE_PENDING: hashPath('/gs', { status: ['GATE_CREATED', 'UNBOXING'] }),
  CSR_APPROVALS_PENDING: '/approvals',
  INSPECTIONS_PENDING: hashPath('/gs', { status: 'INSPECTION' }),
  CONTAINER_AUDIT: '/container-audit',
  OPEN_PENDENCIES: '/pendencies',
  TRANSFERS_ATTENTION: '/custody',
  TECHNICIAN_WIP: '/servicing',
  BATTERY_STOCK: '/batteries',
  DISMANTLING: '/dismantling',
  FUNCTIONAL_STOCK: '/inventory/functional',
  NON_FUNCTIONAL_STOCK: '/inventory/non-functional',
  HAZARD_QUARANTINE: '/inventory/holds',
  CN_PIPELINE: '/credit-notes',
  CN_ISSUED: '/credit-notes',
  GS_TREND: '/gs',
  ACCOUNTS_DOC_QUEUE: '/accounts',
  ADMIN_HEALTH: '/history',
};

/** Phones stack actionable widgets first (§11); the configured order is kept within each group. */
export function orderForDevice(widgets: LayoutWidget[], phone: boolean): LayoutWidget[] {
  if (!phone) return widgets;
  return [
    ...widgets.filter((w) => w.priority === 'action'),
    ...widgets.filter((w) => w.priority !== 'action'),
  ];
}
