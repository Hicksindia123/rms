import { AlertTriangle, Clock, FileWarning, ShieldAlert, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';

import { humanize } from './format';
import { useStatusLabels } from './statusLabels';

// Phase 10: one colour per kind of state. Neutral = not started / cancelled, info = being worked,
// warning = waiting for a decision or another team, success = held safely / closed.
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  GATE_CREATED: 'neutral',
  CLOSED: 'success',
  CANCELLED: 'neutral',
  CSR_APPROVAL_PENDING: 'warning',
  RM_REVIEW: 'warning',
  CATEGORISATION: 'info',
  // DEC-64: locked and waiting for the RM's transfer slip; Complete Sales Return parked (Q11).
  PENDING_TRANSFER_SLIP: 'warning',
  TRANSFER_SLIP_GENERATED: 'info', // DEC-65: in transit to the Intermediate Stores
  STORE_ACKNOWLEDGED: 'success', // DEC-66: every slip acknowledged by its store
  STORE_PROCESSING: 'info', // DEC-67: the stores route / work on the goods
  // DEC-71 (P11): with Accounts / Dispatch; on hold when every decision is Not Allowed (Q21).
  ACCOUNTS_PENDING: 'warning',
  NOT_ALLOWED_HOLD: 'danger',
  DISPATCH_PENDING: 'warning',
  SALES_RETURN_HOLD: 'warning',
  HELD_AT_INTERMEDIATE_STORE: 'success',
  COMMERCIAL_RESOLUTION: 'warning',
  AWAITING_NOTIFICATION: 'warning',
};

/** AMD-08: the label comes from the GS_STATUS configuration (e.g. UNBOXING = Carton Opening). */
export function StatusChip({ status }: { status: string }) {
  const label = useStatusLabels();
  return <Badge variant={STATUS_VARIANT[status] ?? 'info'}>{label(status)}</Badge>;
}

interface Flags {
  missing_documentation: boolean;
  has_open_pendency: boolean;
  has_discrepancy: boolean;
  has_hazard: boolean;
  has_rejections: boolean;
}

const FLAG_ICONS = [
  { key: 'missing_documentation', Icon: FileWarning, color: 'var(--color-warning)' },
  { key: 'has_open_pendency', Icon: Clock, color: '#7c3aed' },
  { key: 'has_discrepancy', Icon: AlertTriangle, color: 'var(--color-warning)' },
  { key: 'has_hazard', Icon: ShieldAlert, color: 'var(--color-danger)' },
  { key: 'has_rejections', Icon: XCircle, color: 'var(--color-danger)' },
] as const;

export function FlagIcons({ flags }: { flags: Flags }) {
  const active = FLAG_ICONS.filter((f) => flags[f.key]);
  if (active.length === 0) return null;
  return (
    <span style={{ display: 'inline-flex', gap: '0.25rem', verticalAlign: 'middle' }}>
      {active.map(({ key, Icon, color }) => (
        <span key={key} title={humanize(key)} role="img" aria-label={humanize(key)}>
          <Icon size={16} color={color} aria-hidden="true" />
        </span>
      ))}
    </span>
  );
}
