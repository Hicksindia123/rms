import { createElement } from 'react';
import {
  type LucideIcon,
  ArrowLeftRight,
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
  Package,
  PackageOpen,
  PlusCircle,
  Receipt,
  ShieldAlert,
  Split,
  Tags,
  Trash2,
  Truck,
  Warehouse,
  Wrench,
  FileCheck2,
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
  STORE_ACCEPT: Warehouse,
  DEPT_ROUTING: Building2,
  DEPT_ISSUE: FolderInput,
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
