import React from 'react';

import { Badge } from '@/components/ui';

import type { Ticket } from './types';

function duration(minutes: number): string {
  const m = Math.abs(minutes);
  const h = Math.floor(m / 60);
  return h > 0 ? `${String(h)} h ${String(m % 60)} min` : `${String(m)} min`;
}

/** DEC-73 (Q3): SLA breach is flagged in-app only (no email / escalation). */
export const SlaChip: React.FC<{ ticket: Ticket }> = ({ ticket }) => {
  switch (ticket.sla_state) {
    case 'OVERDUE':
      return (
        <Badge variant="danger" data-testid="sla-overdue">
          OVERDUE{ticket.minutes_to_due !== null ? ` by ${duration(ticket.minutes_to_due)}` : ''}
        </Badge>
      );
    case 'ON_TIME':
      return (
        <Badge variant="warning" data-testid="sla-on-time">
          {ticket.minutes_to_due !== null ? `${duration(ticket.minutes_to_due)} left` : 'Due'}
        </Badge>
      );
    case 'RAISED_LATE':
      return <Badge variant="neutral">Raised late</Badge>;
    default:
      return <Badge variant="success">Raised on time</Badge>;
  }
};

const STATUS_VARIANT: Record<
  string,
  'default' | 'success' | 'danger' | 'warning' | 'info' | 'neutral'
> = {
  DRAFT: 'warning',
  IN_CHECKING: 'info',
  PENDING_TICKET: 'warning',
  TICKET_RAISED: 'info',
  CLOSED: 'success',
  VOIDED: 'neutral',
};

/** Status chip; the text is the configured label (ECOM_RETURN_STATUS option set). */
export const EcomStatusChip: React.FC<{ status: string; label: string }> = ({ status, label }) => (
  <Badge variant={STATUS_VARIANT[status] ?? 'default'}>{label}</Badge>
);
