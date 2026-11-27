import { createElement } from 'react';
import {
  type LucideIcon,
  ArrowLeftRight,
  ShoppingCart,
  Ticket,
  BarChart3,
  BatteryMedium,
  Boxes,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  Clock,
  FileSpreadsheet,
  FolderInput,
  Hammer,
  History,
  LayoutDashboard,
  ListChecks,
  Mail,
  MessageSquareWarning,
  Package,
  PackageCheck,
  PackageOpen,
  PlusCircle,
  Receipt,
  Send,
  ShieldAlert,
  Split,
  Tags,
  Trash2,
  Truck,
  Warehouse,
  Wrench,
  FileCheck2,
  BadgeCheck,
  Search,
} from 'lucide-react';

/**
 * Change plan Phase 10 (AMD-22): screen keys used by the journey config (journey_steps.screen_key /
 * item_screen_key) mapped to hash routes. This is UI navigation only (which page shows a screen);
 * labels, order and who sees what come from the DB. The DB CHECK constraints list the same keys,
 * so configuration cannot point at a screen that does not exist (rule j).
 */
const SCREEN_PATHS: Record<string, string> = {
  'gs-new': '/gs/new',
  'gs-list': '/gs',
  dashboard: '/dashboard',
  pendencies: '/pendencies',
  'container-audit': '/container-audit',
  reports: '/reports',
  audit: '/admin/audit',
  custody: '/custody',
  inventory: '/inventory',
  'store-issues': '/store-issues',
  servicing: '/servicing',
  batteries: '/batteries',
  dismantling: '/dismantling',
  scrap: '/scrap',
  'credit-notes': '/credit-notes',
  approvals: '/approvals',
  'dispatch-queue': '/dispatch',
  'department-routing': '/department-routing',
  'department-issue': '/department-issue',
  'store-routing': '/store-routing', // DEC-67
  'store-receiving': '/store-receiving', // DEC-68
  'store-analysis': '/store-analysis', // DEC-69
  'management-approval': '/management-approval', // DEC-70
  'ecom-return-new': '/ecom-returns/new', // DEC-73
  'ecom-returns': '/ecom-returns', // DEC-73
  'ecom-tickets': '/ecom-tickets', // DEC-73
  'ecom-portal-check': '/ecom-portal-check', // DEC-76
  'ecom-unboxing': '/ecom-unboxing', // DEC-76
  'ecom-store-receipts': '/ecom-store-receipts', // DEC-76
  'ecom-action-sheets': '/ecom-action-sheets', // DEC-76
  'transfer-slips': '/transfer-slips',
  'transfer-slip-acks': '/transfer-slips/acknowledge', // DEC-66
  'department-receiving': '/department-receiving',
  'accounts-entry': '/accounts-entry',
  'accounts-docs': '/accounts',
  'dispatch-slips': '/dispatch-slips',
};

/** Where a menu entry goes. A queue step without its own page opens its list inside My Work. */
export function entryPath(entry: { code: string; screen_key: string }): string {
  if (entry.screen_key === 'journey-queue') {
    return `/mywork?journey=${encodeURIComponent(entry.code)}`;
  }
  return SCREEN_PATHS[entry.screen_key] ?? '/mywork';
}

/** Where one GS of a step's queue opens ("next GS to act on"). */
export function itemPath(
  itemScreenKey: string | null,
  item: { gs_id: string; target_id: string },
): string {
  switch (itemScreenKey) {
    case 'gs-unboxing':
      return `/gs/${item.gs_id}/unboxing`;
    case 'gs-itemization':
      return `/gs/${item.gs_id}/itemization`;
    case 'gs-inspection':
      return `/gs/${item.gs_id}/inspection`;
    case 'gs-rm-review':
      return `/gs/${item.gs_id}/rm-review`;
    case 'gs-final-actions':
      return `/gs/${item.gs_id}/final-actions`;
    case 'gs-party-notification':
      return `/gs/${item.gs_id}/party-notification`;
    case 'custody-transfer':
      return `/custody/transfers/${item.target_id}`;
    case 'accounts-entry-gs':
      return `/accounts-entry/${item.gs_id}`;
    case 'department-receiving':
      return '/department-receiving';
    case 'department-issue':
      return '/department-issue';
    case 'transfer-slips':
      return '/transfer-slips';
    case 'gs-store-routing': // DEC-67: the store routes its goods of this GS
      return `/store-routing/${item.gs_id}`;
    case 'gs-store-receiving': // DEC-68: the store receives its goods of this GS back
      return `/store-receiving/${item.gs_id}`;
    case 'gs-store-analysis': // DEC-69: the store analyses its goods of this GS
      return `/store-analysis/${item.gs_id}`;
    case 'gs-management-approval': // DEC-70: Management reviews / approves this GS
      return `/management-approval/${item.gs_id}`;
    case 'ecom-return': // DEC-73: an E-Commerce Return (not a goods slip)
      return `/ecom-returns/${item.target_id}`;
    case 'ecom-action-sheet': // DEC-76: an E-Commerce Action Sheet
      return `/ecom-action-sheets/${item.target_id}`;
    case 'transfer-slip': // DEC-66: the queue item is the slip itself
      return `/transfer-slips/${item.target_id}`;
    case 'accounts-docs':
      return '/accounts';
    case 'dispatch-slips':
      return '/dispatch-slips';
    default:
      return `/gs/${item.gs_id}`;
  }
}

/** First path segment of an entry's route, to highlight the active menu entry. */
export function entryTab(entry: { code: string; screen_key: string }): string {
  const path = entryPath(entry);
  return path.split('?')[0]?.split('/').filter(Boolean)[0] ?? '';
}

const ICONS: Record<string, LucideIcon> = {
  GATE_ENTRY: PlusCircle,
  CARTON_OPENING: PackageOpen,
  COUNTING: ListChecks,
  CATEGORISATION: Tags,
  INSPECTION: ClipboardCheck,
  RM_REVIEW: FileCheck2,
  TRANSFER_SLIPS: Send,
  EDIT_REQUESTS: MessageSquareWarning,
  STORE_ACCEPT: Warehouse,
  ACK_TRANSFER_SLIPS: PackageCheck,
  DEPT_ROUTING: Building2,
  DEPT_ISSUE: FolderInput,
  STORE_DEPT_ROUTING: Building2,
  STORE_DEPT_RECEIVING: CheckCircle2,
  STORE_ANALYSIS: Split, // DEC-69
  MANAGEMENT_APPROVAL: BadgeCheck, // DEC-70
  ECOM_GATE_ENTRY: ShoppingCart, // DEC-73
  ECOM_TICKETS: Ticket, // DEC-73
  ECOM_RETURNS: ShoppingCart, // DEC-73
  ECOM_PORTAL_CHECK: Search, // DEC-76
  ECOM_UNBOXING: PackageOpen, // DEC-76
  ECOM_STORE_RECEIPTS: PackageCheck, // DEC-76
  ECOM_ACTION_SHEETS: FileSpreadsheet, // DEC-76
  DEPT_RECEIVING: CheckCircle2,
  FINAL_ACTIONS: Split,
  ACCOUNTS_DOCS: FileSpreadsheet,
  ACCOUNTS_ENTRY: Receipt,
  DISPATCH_SLIP: Truck,
  PARTY_EMAIL: Mail,
  GS_LIST: Package,
  DASHBOARD: LayoutDashboard,
  PENDENCIES: Clock,
  CONTAINER_AUDIT: Boxes,
  APPROVALS: ShieldAlert,
  CUSTODY: ArrowLeftRight,
  INVENTORY: Boxes,
  STORE_ISSUES: FolderInput,
  SERVICING: Wrench,
  BATTERIES: BatteryMedium,
  DISMANTLING: Hammer,
  SCRAP: Trash2,
  CREDIT_NOTES: Receipt,
  DISPATCH_QUEUE: Truck,
  REPORTS: BarChart3,
  AUDIT: History,
};

/** The icon of a journey entry (by code; a generic icon for entries added later). */
export function EntryIcon({ code, size = 17 }: { code: string; size?: number }) {
  return createElement(ICONS[code] ?? ClipboardList, { size, 'aria-hidden': true });
}
