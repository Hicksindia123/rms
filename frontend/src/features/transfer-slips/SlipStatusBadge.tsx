import { Badge, type BadgeVariant } from '@/components/ui';

import type { SlipStatus } from './api';

// DEC-65: system status codes of a transfer slip (not business dropdowns).
const LABEL: Record<SlipStatus, string> = {
  GENERATED: 'Generated',
  ACKNOWLEDGED: 'Acknowledged',
  VOIDED: 'Voided',
};
const VARIANT: Record<SlipStatus, BadgeVariant> = {
  GENERATED: 'warning',
  ACKNOWLEDGED: 'success',
  VOIDED: 'neutral',
};

export function SlipStatusBadge({ status }: { status: SlipStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
