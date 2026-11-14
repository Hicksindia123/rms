import type { AppNotification } from './api';

type Can = (module: string, action: string) => boolean;

/**
 * Deep link of a notification: the screen where it is acted on (P2-03 bell routing, extended in
 * P4-03 for the new events). Keys off the stable `type` / `entity_type` codes, never labels.
 * Returns null when there is nothing to open.
 */
export function notificationPath(n: AppNotification, can: Can): string | null {
  if (n.entity_type === 'container_audit_day' || n.type.startsWith('CONTAINER_AUDIT')) {
    return '/container-audit';
  }
  // Change plan Phase 7/8 (AMD-17, AMD-18): A/c Actions slip events -> the Accounts entry for
  // Accounts (enters data, does not edit actions), else the Final Actions screen (RM).
  if (n.entity_type === 'ac_action_slips' && n.gs_id) {
    return can('ac_entry', 'edit') && !can('final_actions', 'edit')
      ? `/accounts-entry/${n.gs_id}`
      : `/gs/${n.gs_id}/final-actions`;
  }
  // Change plan Phase 8 (AMD-19): Dispatch Slip ready / dispatched.
  if (n.entity_type === 'dispatch_slips') {
    if (can('dispatch', 'view')) return '/dispatch-slips';
    if (n.gs_id && can('ac_entry', 'view')) return `/accounts-entry/${n.gs_id}`;
  }
  if (n.entity_type === 'custody_transfer' && n.entity_id) {
    return `/custody/transfers/${n.entity_id}`;
  }
  if (n.entity_id && n.entity_type === 'goods_slip') {
    if (
      (n.type === 'GS_DOCUMENTS_RECEIVED' || n.type === 'GS_DOCUMENT_FOUND') &&
      can('credit_notes', 'view')
    ) {
      return '/accounts';
    }
    if (n.type.startsWith('MISSING_DOC_EXCEPTION')) return `/gs/${n.entity_id}/unboxing`;
    if (
      (n.type === 'CSR_APPROVAL_REQUIRED' || n.type === 'ITEM_CORRECTION_REQUESTED') &&
      can('itemization', 'approve')
    ) {
      return '/approvals';
    }
    if (
      n.type === 'CSR_DECIDED' ||
      n.type === 'TRANSFER_PROPOSED' ||
      n.type.startsWith('ITEM_CORRECTION')
    ) {
      return `/gs/${n.entity_id}/itemization`;
    }
    return `/gs/${n.entity_id}`;
  }
  switch (n.entity_type) {
    case 'battery_type':
      return '/batteries';
    case 'technician_batch':
      return '/servicing';
    case 'dismantle_batch':
      return '/dismantling';
    case 'store_issue':
      return '/store-issues';
    case 'segregation_check_run':
    case 'stock_adjustment':
      return '/inventory';
    default:
      break;
  }
  // Other GS-scoped events (CN, dispatch, RM actions …) open the goods slip.
  if (n.gs_id) return `/gs/${n.gs_id}`;
  if (n.entity_type === 'goods_slips' && n.entity_id) return `/gs/${n.entity_id}`;
  return null;
}
