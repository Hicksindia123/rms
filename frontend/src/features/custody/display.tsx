import { Badge, type BadgeVariant } from '@/components/ui';
import { humanize } from '@/features/goods-slips/format';
import type { TransferStatus } from './types';

/** Engine statuses are system codes (§8.5); shown humanised like GS statuses. */
const STATUS_VARIANT: Record<TransferStatus, BadgeVariant> = {
  INITIATED: 'info',
  ACCEPTED: 'success',
  DISCREPANCY: 'danger',
  RECONCILED: 'success',
  CANCELLED: 'neutral',
};

export function TransferStatusBadge({
  status,
  inTransit,
}: {
  status: TransferStatus;
  inTransit?: boolean;
}) {
  return (
    <Badge variant={STATUS_VARIANT[status]}>
      {status === 'INITIATED' && inTransit ? 'In transit' : humanize(status)}
    </Badge>
  );
}
