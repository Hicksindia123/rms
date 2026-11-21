import { lazy, Suspense, useCallback, useState, type ReactNode } from 'react';
import {
  type LucideIcon,
  Layers,
  CheckSquare,
  Users,
  Shield,
  FileCode,
  GitMerge,
  Database,
  Sliders,
  Hash,
  Settings,
  Printer,
  FileClock,
  ShieldCheck,
  LayoutTemplate,
  BellRing,
  Columns3,
  LogOut,
  LogIn,
  Menu,
  ChevronDown,
  ChevronRight,
  Loader2,
  RotateCcw,
  Route,
  Warehouse,
} from 'lucide-react';

import { parseHashQuery, useHashRoute } from '@/app/router';
import hicksLogo from '@/assets/logo.png';
import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { AuthProvider } from '@/features/auth/AuthContext';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';
import { GoodsSlipDetailPage } from '@/features/goods-slips/GoodsSlipDetailPage';
import { GoodsSlipListPage } from '@/features/goods-slips/GoodsSlipListPage';
import { GsTagPrintPage } from '@/features/goods-slips/GsTagPrintPage';
import { NewGoodsSlipPage } from '@/features/goods-slips/NewGoodsSlipPage';
import { ChangePasswordScreen } from '@/features/auth/ChangePasswordScreen';
import { LoginForm } from '@/features/auth/LoginForm';
import { MyWorkView } from '@/features/mywork/MyWorkView';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { DocumentQueuePage } from '@/features/accounts/DocumentQueuePage';
import { InspectionPage } from '@/features/inspection/InspectionPage';
import { NotificationBell } from '@/features/notifications/NotificationBell';
import type { AppNotification } from '@/features/notifications/api';
import { notificationPath } from '@/features/notifications/links';
import { ApprovalsPage } from '@/features/unboxing/ApprovalsPage';
import { DailyAuditPage } from '@/features/container-audit/DailyAuditPage';
import { ItemizationPage } from '@/features/itemization/ItemizationPage';
import { RmReviewPage } from '@/features/rm-review/RmReviewPage';
import { UnboxingPage } from '@/features/unboxing/UnboxingPage';
import { RmSegregationPage } from '@/features/rm-actions/RmSegregationPage';
import { ReplacementSlipPrintPage } from '@/features/rm-actions/ReplacementSlipPrintPage';
import { PendencyRegisterPage } from '@/features/pendency/PendencyRegisterPage';
import { HandoverPage } from '@/features/custody/HandoverPage';
import { TransferDetailPage } from '@/features/custody/TransferDetailPage';
import { TransferNotePrintPage } from '@/features/custody/TransferNotePrintPage';
import { TransfersPage } from '@/features/custody/TransfersPage';
import { TechnicianBoardPage } from '@/features/servicing/TechnicianBoardPage';
import { AllotBatchPage } from '@/features/servicing/AllotBatchPage';
import { ReceiveBatchPage } from '@/features/servicing/ReceiveBatchPage';
import { BatteryStockPage } from '@/features/inventory/batteries/BatteryStockPage';
import { InventoryPage } from '@/features/inventory/InventoryPage';
import { toInventoryTab } from '@/features/inventory/rules';
import { GlobalSearchBar } from '@/features/search/GlobalSearchBar';
import { fetchMyJourney, type JourneyEntry } from '@/features/journey/api';
import { EntryIcon, entryPath, entryTab } from '@/features/journey/screens';

// Route-level code splitting for heavy / admin / reporting / auxiliary modules (P4-05)
const FormBuilder = lazy(() =>
  import('@/features/config/forms/FormBuilder').then((m) => ({ default: m.FormBuilder })),
);
const ItemFieldProfilesPage = lazy(() =>
  import('@/features/config/field-profiles/ItemFieldProfilesPage').then((m) => ({
    default: m.ItemFieldProfilesPage,
  })),
);
const OptionSetsManager = lazy(() =>
  import('@/features/config/options/OptionSetsManager').then((m) => ({
    default: m.OptionSetsManager,
  })),
);
const WorkflowDesigner = lazy(() =>
  import('@/features/config/workflow/WorkflowDesigner').then((m) => ({
    default: m.WorkflowDesigner,
  })),
);
const NumberSeriesManager = lazy(() =>
  import('@/features/config/numbering/NumberSeriesManager').then((m) => ({
    default: m.NumberSeriesManager,
  })),
);
const SystemSettingsManager = lazy(() =>
  import('@/features/config/settings/SystemSettingsManager').then((m) => ({
    default: m.SystemSettingsManager,
  })),
);
const PrintTemplatesManager = lazy(() =>
  import('@/features/config/templates/PrintTemplatesManager').then((m) => ({
    default: m.PrintTemplatesManager,
  })),
);
const ConfigHistoryViewer = lazy(() =>
  import('@/features/config/history/ConfigHistoryViewer').then((m) => ({
    default: m.ConfigHistoryViewer,
  })),
);
const SystemGuardsViewer = lazy(() =>
  import('@/features/config/guards/SystemGuardsViewer').then((m) => ({
    default: m.SystemGuardsViewer,
  })),
);
const DashboardLayoutEditor = lazy(() =>
  import('@/features/admin/dashboard-config/DashboardLayoutEditor').then((m) => ({
    default: m.DashboardLayoutEditor,
  })),
);
const ReportColumnDefaultsEditor = lazy(() =>
  import('@/features/admin/report-columns/ReportColumnDefaultsEditor').then((m) => ({
    default: m.ReportColumnDefaultsEditor,
  })),
);
const ReportPrintPage = lazy(() =>
  import('@/features/reports/ReportPrintPage').then((m) => ({ default: m.ReportPrintPage })),
);
const ReportsCataloguePage = lazy(() =>
  import('@/features/reports/ReportsCataloguePage').then((m) => ({
    default: m.ReportsCataloguePage,
  })),
);
const ReportViewerPage = lazy(() =>
  import('@/features/reports/ReportViewerPage').then((m) => ({ default: m.ReportViewerPage })),
);
const UsersView = lazy(() =>
  import('@/features/users/UsersView').then((m) => ({ default: m.UsersView })),
);
const PermissionMatrixView = lazy(() =>
  import('@/features/users/PermissionMatrixView').then((m) => ({
    default: m.PermissionMatrixView,
  })),
);
const MastersView = lazy(() =>
  import('@/features/masters/MastersView').then((m) => ({ default: m.MastersView })),
);
const NotificationCentrePage = lazy(() =>
  import('@/features/notifications/NotificationCentrePage').then((m) => ({
    default: m.NotificationCentrePage,
  })),
);
const NotificationPreferencesPage = lazy(() =>
  import('@/features/notifications/NotificationPreferencesPage').then((m) => ({
    default: m.NotificationPreferencesPage,
  })),
);
const NotificationAdminPage = lazy(() =>
  import('@/features/admin/notifications/NotificationAdminPage').then((m) => ({
    default: m.NotificationAdminPage,
  })),
);
const DismantlingQueuePage = lazy(() =>
  import('@/features/dismantling/DismantlingQueuePage').then((m) => ({
    default: m.DismantlingQueuePage,
  })),
);
const RecoveryPage = lazy(() =>
  import('@/features/dismantling/RecoveryPage').then((m) => ({ default: m.RecoveryPage })),
);
const ScrapRegisterPage = lazy(() =>
  import('@/features/dismantling/ScrapRegisterPage').then((m) => ({
    default: m.ScrapRegisterPage,
  })),
);
const CreditNoteWorkspacePage = lazy(() =>
  import('@/features/credit-notes/CreditNoteWorkspacePage').then((m) => ({
    default: m.CreditNoteWorkspacePage,
  })),
);
const CreditNotePrintPage = lazy(() =>
  import('@/features/credit-notes/CreditNotePrintPage').then((m) => ({
    default: m.CreditNotePrintPage,
  })),
);
const AccountsCreditNoteQueuePage = lazy(() =>
  import('@/features/credit-notes/AccountsCreditNoteQueuePage').then((m) => ({
    default: m.AccountsCreditNoteQueuePage,
  })),
);
const RmCnDecisionPage = lazy(() =>
  import('@/features/credit-notes/RmCnDecisionPage').then((m) => ({ default: m.RmCnDecisionPage })),
);
const StoreIssuePage = lazy(() =>
  import('@/features/store-issue/StoreIssuePage').then((m) => ({ default: m.StoreIssuePage })),
);
const StoreIssuePrintPage = lazy(() =>
  import('@/features/store-issue/StoreIssuePrintPage').then((m) => ({
    default: m.StoreIssuePrintPage,
  })),
);
const DispatchQueuePage = lazy(() =>
  import('@/features/dispatch/DispatchQueuePage').then((m) => ({ default: m.DispatchQueuePage })),
);
const AuditExplorerPage = lazy(() =>
  import('@/features/admin/audit/AuditExplorerPage').then((m) => ({
    default: m.AuditExplorerPage,
  })),
);
const UserActivityPage = lazy(() =>
  import('@/features/users/UserActivityPage').then((m) => ({ default: m.UserActivityPage })),
);
const SearchPage = lazy(() =>
  import('@/features/search/SearchPage').then((m) => ({ default: m.SearchPage })),
);
const ClosureCertificatePage = lazy(() =>
  import('@/features/closure/ClosureCertificatePage').then((m) => ({
    default: m.ClosureCertificatePage,
  })),
);
const PartyNotificationPage = lazy(() =>
  import('@/features/party-notifications/PartyNotificationPage').then((m) => ({
    default: m.PartyNotificationPage,
  })),
);
const ResolutionBoardPage = lazy(() =>
  import('@/features/rm-actions/ResolutionBoardPage').then((m) => ({
    default: m.ResolutionBoardPage,
  })),
);
const RmRoutingQueuePage = lazy(() =>
  import('@/features/department-routing/RmRoutingQueuePage').then((m) => ({
    default: m.RmRoutingQueuePage,
  })),
);
// Change plan Phase 7 (AMD-16, AMD-17): RM final actions + A/c Actions slip.
const FinalActionsPage = lazy(() =>
  import('@/features/final-actions/FinalActionsPage').then((m) => ({
    default: m.FinalActionsPage,
  })),
);
// Change plan Phase 8 (AMD-18, AMD-19): Accounts entry per action line + Dispatch Slips.
const AccountsEntryQueuePage = lazy(() =>
  import('@/features/ac-entry/AccountsEntryQueuePage').then((m) => ({
    default: m.AccountsEntryQueuePage,
  })),
);
const AccountsEntryPage = lazy(() =>
  import('@/features/ac-entry/AccountsEntryPage').then((m) => ({
    default: m.AccountsEntryPage,
  })),
);
const DispatchSlipsPage = lazy(() =>
  import('@/features/ac-entry/DispatchSlipsPage').then((m) => ({
    default: m.DispatchSlipsPage,
  })),
);
// Phase P1 20-11-2026 (DEC-61): Admin -> Intermediate Stores.
const IntermediateStoresPage = lazy(() =>
  import('@/features/intermediate-stores/IntermediateStoresPage').then((m) => ({
    default: m.IntermediateStoresPage,
  })),
);
// Change plan Phase 10 (AMD-22): Admin -> Role Journeys.
const RoleJourneysPage = lazy(() =>
  import('@/features/journey/RoleJourneysPage').then((m) => ({ default: m.RoleJourneysPage })),
);
const DepartmentReceivingQueuePage = lazy(() =>
  import('@/features/department-routing/DepartmentReceivingQueuePage').then((m) => ({
    default: m.DepartmentReceivingQueuePage,
  })),
);
// Gap plan G2 (DEC-55): Store Manager issues planned routing to departments.
const TransferSlipsPage = lazy(() =>
  import('@/features/transfer-slips/TransferSlipsPage').then((m) => ({
    default: m.TransferSlipsPage,
  })),
);
const TransferSlipDetailPage = lazy(() =>
  import('@/features/transfer-slips/TransferSlipDetailPage').then((m) => ({
    default: m.TransferSlipDetailPage,
  })),
);
const DepartmentIssuePage = lazy(() =>
  import('@/features/department-routing/DepartmentIssuePage').then((m) => ({
    default: m.DepartmentIssuePage,
  })),
);
const DepartmentIssueNotePrintPage = lazy(() =>
  import('@/features/department-routing/DepartmentIssueNotePrintPage').then((m) => ({
    default: m.DepartmentIssueNotePrintPage,
  })),
);

type NavTab =
  | 'login'
  | 'gs'
  | 'gs-new'
  | 'mywork'
  | 'dashboard'
  | 'dashboard-config'
  | 'notifications'
  | 'notification-preferences'
  | 'notification-admin'
  | 'reports'
  | 'report-columns'
  | 'accounts'
  | 'credit-notes'
  | 'approvals'
  | 'container-audit'
  | 'pendencies'
  | 'custody'
  | 'users'
  | 'permissions'
  | 'forms'
  | 'workflow'
  | 'masters'
  | 'options'
  | 'field-profiles'
  | 'numbering'
  | 'settings'
  | 'templates'
  | 'history'
  | 'servicing'
  | 'batteries'
  | 'inventory'
  | 'dismantling'
  | 'scrap'
  | 'store-issues'
  | 'dispatch'
  | 'department-routing'
  | 'department-issue'
  | 'transfer-slips'
  | 'department-receiving'
  | 'accounts-entry'
  | 'dispatch-slips'
  | 'guards'
  | 'role-journeys'
  | 'intermediate-stores'
  | 'search'
  | 'audit';

const STATIC_TABS: ReadonlySet<string> = new Set([
  'login',
  'mywork',
  'dashboard',
  'dashboard-config',
  'notifications',
  'notification-preferences',
  'notification-admin',
  'reports',
  'report-columns',
  'accounts',
  'credit-notes',
  'approvals',
  'container-audit',
  'pendencies',
  'custody',
  'users',
  'permissions',
  'forms',
  'workflow',
  'masters',
  'options',
  'field-profiles',
  'numbering',
  'settings',
  'templates',
  'history',
  'servicing',
  'batteries',
  'inventory',
  'dismantling',
  'scrap',
  'store-issues',
  'dispatch',
  'department-routing',
  'department-issue',
  'transfer-slips',
  'department-receiving',
  'accounts-entry',
  'dispatch-slips',
  'guards',
  'role-journeys',
  'intermediate-stores',
  'search',
  'audit',
]);

// Admin screens (the collapsed "Administration" group opens while one of them is shown).
const ADMIN_TABS: ReadonlySet<string> = new Set([
  'role-journeys',
  'intermediate-stores',
  'users',
  'permissions',
  'forms',
  'workflow',
  'masters',
  'options',
  'field-profiles',
  'numbering',
  'settings',
  'templates',
  'history',
  'guards',
  'dashboard-config',
  'notification-admin',
  'report-columns',
]);

export function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}

/** GS screens need a signed-in user (all business data flows through the authenticated API). */
function RequireAuth({ children, onSignIn }: { children: ReactNode; onSignIn: () => void }) {
  const { status, error } = useAuth();
  if (status === 'loading') return <LoadingState />;
  if (status === 'error') {
    return <ErrorState error={{ message: error ?? 'Your session could not be loaded.' }} />;
  }
  if (status === 'signed-out') {
    return (
      <EmptyState
        title="Sign in required"
        hint="Sign in to work with goods slips."
        action={
          <Button type="button" variant="primary" onClick={onSignIn}>
            Sign In
          </Button>
        }
      />
    );
  }
  return <>{children}</>;
}

function Shell() {
  const { status, me, can, signOut } = useAuth();
  const [segments, navigate] = useHashRoute();
  const [first, second, third] = segments;
  const hashQuery = parseHashQuery(window.location.hash);
  const signedIn = status === 'signed-in';
  // Phase 10 (AMD-22): a signed-in user without a route lands on My Work (their journey home).
  const activeTab: NavTab =
    first === 'gs'
      ? second === 'new'
        ? 'gs-new'
        : 'gs'
      : (first === 'admin' && second === 'audit') || first === 'audit'
        ? 'audit'
        : first && STATIC_TABS.has(first)
          ? (first as NavTab)
          : signedIn
            ? 'mywork'
            : 'login';
  const setActiveTab = (tab: NavTab) => {
    navigate(
      tab === 'gs'
        ? '/gs'
        : tab === 'gs-new'
          ? '/gs/new'
          : tab === 'audit'
            ? '/admin/audit'
            : `/${tab}`,
    );
  };
  const roleCodes = me?.roles.map((r) => r.code) ?? [];
  const isSuperAdmin = Boolean(me?.profile.is_super_admin);
  const isCoordinatorOrAdmin =
    isSuperAdmin || roleCodes.includes('TECHNICIAN_COORDINATOR') || roleCodes.includes('ADMIN');
  const isSpmOrAdmin =
    isSuperAdmin || roleCodes.includes('SPARE_PARTS_MANAGER') || roleCodes.includes('ADMIN');
  const isAdminOrRm =
    isSuperAdmin || roleCodes.includes('ADMIN') || roleCodes.includes('REPLACEMENT_MANAGER');

  // Bell / notification centre → the screen where the notification is acted on (P4-03 links.ts).
  const openNotification = (n: AppNotification): boolean => {
    const path = notificationPath(n, can);
    if (path) navigate(path);
    return path !== null;
  };

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [logoError, setLogoError] = useState(false);
  // Phase 10: rarely used admin items start collapsed; open while an admin screen is shown.
  const [adminExpanded, setAdminExpanded] = useState(false);
  const adminOpen = adminExpanded || ADMIN_TABS.has(activeTab);

  // Phase 10 (AMD-22): the menu + counts; refetched when the user moves to another section, so
  // the counts follow the work just done.
  // P1-05 / DEC-50: nothing but /me is reachable until a temporary password is replaced.
  const appReady = signedIn && !me?.profile.must_change_password;
  const journeyFetcher = useCallback(
    () =>
      appReady
        ? fetchMyJourney().then((j) => ({ j, at: Date.now(), section: first ?? '' }))
        : Promise.resolve(null),
    [appReady, first],
  );
  const journeyQuery = useApiQuery(journeyFetcher);
  const journey = journeyQuery.data?.j ?? null;
  const journeyError = journeyQuery.error;
  const reloadJourney = journeyQuery.reload;

  const userInitials = me?.profile.full_name
    ? me.profile.full_name
        .split(' ')
        .filter(Boolean)
        .slice(0, 2)
        .map((p) => p[0]?.toUpperCase() ?? '')
        .join('')
    : 'U';
  const roleTitle = me?.roles[0]?.name ?? (isSuperAdmin ? 'Super Admin' : 'Staff');

  type NavEntry = {
    id: NavTab;
    label: string;
    icon: LucideIcon;
  };

  // Change plan Phase 10 (AMD-22): the role's menu comes from DB config (GET /me/journey), in the
  // order of its working journey; steps then tools. On-hold modules (AMD-21) are left out by the
  // API. Admin items below stay permission-based and collapsed (rarely used).
  const journeySteps = (journey?.entries ?? []).filter((e) => e.kind === 'STEP');
  const journeyTools = (journey?.entries ?? []).filter((e) => e.kind === 'TOOL');
  const journeyParam = activeTab === 'mywork' ? hashQuery.get('journey') : null;
  const isEntryActive = (e: JourneyEntry): boolean => {
    if (e.screen_key === 'journey-queue') return journeyParam === e.code;
    if (e.screen_key === 'gs-new') return activeTab === 'gs-new';
    if (e.screen_key === 'gs-list') return activeTab === 'gs';
    // '/admin/audit' is the audit tab; every other entry's first path segment is its tab.
    return entryTab(e) === (activeTab === 'audit' ? 'admin' : activeTab);
  };

  const renderJourneyBtn = (e: JourneyEntry) => {
    const active = isEntryActive(e);
    return (
      <button
        key={e.code}
        type="button"
        className={`saas-nav-item ${active ? 'active' : ''}`}
        data-testid={`nav-${e.code}`}
        title={e.hint ?? undefined}
        onClick={() => {
          navigate(entryPath(e));
          setSidebarOpen(false);
        }}
      >
        <EntryIcon code={e.code} />
        <span className="saas-nav-item__label">{e.label}</span>
        {e.count !== null && e.count > 0 ? (
          <span
            className={`saas-nav-count ${active ? 'saas-nav-count--active' : ''}`}
            aria-label={`${String(e.count)} waiting`}
          >
            {e.count}
          </span>
        ) : null}
      </button>
    );
  };

  const adminItems: NavEntry[] = [
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'role-journeys' as const, label: 'Role Journeys', icon: Route }]
      : []),
    ...(signedIn && (can('intermediate_stores', 'view') || isSuperAdmin)
      ? [{ id: 'intermediate-stores' as const, label: 'Intermediate Stores', icon: Warehouse }]
      : []),
    ...(signedIn && (can('users', 'view') || isSuperAdmin)
      ? [{ id: 'users' as const, label: 'Users', icon: Users }]
      : []),
    ...(signedIn && (can('roles', 'view') || isSuperAdmin)
      ? [{ id: 'permissions' as const, label: 'Permission Matrix', icon: Shield }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'forms' as const, label: 'Form Builder', icon: FileCode }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'workflow' as const, label: 'Workflow Designer', icon: GitMerge }]
      : []),
    ...(signedIn && (can('masters', 'view') || isSuperAdmin)
      ? [{ id: 'masters' as const, label: 'Masters', icon: Database }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'options' as const, label: 'Option Sets', icon: Sliders }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'field-profiles' as const, label: 'Item Field Profiles', icon: Layers }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'numbering' as const, label: 'Number Series', icon: Hash }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'settings' as const, label: 'System Settings', icon: Settings }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'templates' as const, label: 'Print Templates', icon: Printer }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'history' as const, label: 'Config History', icon: FileClock }]
      : []),
    ...(signedIn && (can('config', 'view') || isSuperAdmin)
      ? [{ id: 'guards' as const, label: 'System Guards', icon: ShieldCheck }]
      : []),
    ...(signedIn && (can('dashboards', 'configure') || isSuperAdmin)
      ? [{ id: 'dashboard-config' as const, label: 'Dashboard Layouts', icon: LayoutTemplate }]
      : []),
    ...(signedIn && (can('notifications', 'configure') || isSuperAdmin)
      ? [{ id: 'notification-admin' as const, label: 'Notification Rules', icon: BellRing }]
      : []),
    ...(signedIn && ((can('reports', 'configure') && can('reports', 'view')) || isSuperAdmin)
      ? [{ id: 'report-columns' as const, label: 'Report Columns', icon: Columns3 }]
      : []),
  ];

  const renderNavBtn = (item: NavEntry) => {
    const Icon = item.icon;
    const isActive = activeTab === item.id;
    return (
      <button
        key={item.id}
        type="button"
        className={`saas-nav-item ${isActive ? 'active' : ''}`}
        onClick={() => {
          setActiveTab(item.id);
          setSidebarOpen(false);
        }}
      >
        <Icon size={17} aria-hidden="true" />
        <span>{item.label}</span>
      </button>
    );
  };

  if (status === 'loading') {
    return (
      <div className="auth-root auth-root--loading" role="status" aria-live="polite">
        <Loader2 size={22} className="auth-spin" aria-hidden="true" />
        <span className="sr-only">Loading…</span>
      </div>
    );
  }

  // P1-05 / DEC-50: an admin-issued temporary password must be replaced before anything else.
  if (signedIn && me?.profile.must_change_password) {
    return <ChangePasswordScreen />;
  }

  if (!signedIn || activeTab === 'login') {
    return (
      <LoginForm
        onSuccess={() => {
          setActiveTab('mywork');
        }}
      />
    );
  }

  return (
    <div
      className="app-shell"
      style={{ minHeight: '100vh', backgroundColor: '#f8fafc', overflowX: 'hidden' }}
    >
      {/* SaaS Sticky Topbar */}
      <header className="saas-topbar no-print">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            type="button"
            className="saas-sidebar-toggle"
            onClick={() => setSidebarOpen((prev) => !prev)}
            aria-label="Toggle navigation menu"
            title="Toggle menu"
          >
            <Menu size={18} />
          </button>
          <div className="saas-brand">
            <div className="saas-logo-badge" title="Hicks India Limited">
              {!logoError ? (
                <img
                  src={hicksLogo}
                  alt="Hicks India"
                  className="saas-logo-img"
                  onError={() => setLogoError(true)}
                />
              ) : (
                <div className="saas-logo-icon" aria-hidden="true">
                  <Layers size={18} />
                </div>
              )}
            </div>
            <div className="saas-brand-text">
              <h1 className="saas-title">Replacement Management System</h1>
              <span className="saas-company-tag">Hicks India Limited</span>
            </div>
          </div>
        </div>

        <div style={{ flex: 1, maxWidth: '440px', margin: '0 1rem' }}>
          <GlobalSearchBar onNavigate={navigate} />
        </div>

        {/* Phase 10: no global "New Goods Slip" here; Gate Entry is the gate role's journey step. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {signedIn && me ? (
            <NotificationBell
              userId={me.profile.id}
              onOpen={(n) => {
                openNotification(n);
              }}
              onViewAll={() => {
                navigate('/notifications');
              }}
            />
          ) : null}

          {signedIn && me ? (
            <div className="saas-profile-pill">
              <div className="saas-avatar-circle" title={me.profile.email ?? undefined}>
                {userInitials}
              </div>
              <div className="saas-profile-name">
                <span style={{ fontWeight: 600, fontSize: '0.8125rem', color: '#f8fafc' }}>
                  {me.profile.full_name}
                </span>
                <span style={{ fontSize: '0.6875rem', color: '#94a3b8' }}>{roleTitle}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  void signOut();
                }}
                aria-label="Sign out"
                className="saas-btn-signout"
                title="Sign out of RMS"
              >
                <LogOut size={13} aria-hidden="true" />
                <span>Sign out</span>
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setActiveTab('login')}
              style={{
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                color: '#f8fafc',
                borderRadius: '6px',
                padding: '0.4rem 0.85rem',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                minHeight: '36px',
              }}
            >
              <LogIn size={15} />
              <span>Sign In</span>
            </button>
          )}
        </div>
      </header>

      {sidebarOpen ? (
        <div
          className="saas-backdrop no-print"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <div className="saas-layout">
        <aside
          className={`saas-sidebar no-print ${sidebarOpen ? 'open' : ''}`}
          aria-label="Main Navigation"
        >
          <nav className="saas-sidebar-nav" aria-label="Main Navigation">
            <div className="saas-nav-group">
              <button
                type="button"
                className={`saas-nav-item ${activeTab === 'mywork' && !journeyParam ? 'active' : ''}`}
                data-testid="nav-mywork"
                onClick={() => {
                  setActiveTab('mywork');
                  setSidebarOpen(false);
                }}
              >
                <CheckSquare size={17} aria-hidden="true" />
                <span className="saas-nav-item__label">My Work</span>
              </button>
            </div>

            {journeyError ? (
              <div className="saas-nav-group" role="alert">
                <span className="saas-group-header">Menu unavailable</span>
                <button type="button" className="saas-nav-item" onClick={reloadJourney}>
                  <RotateCcw size={17} aria-hidden="true" />
                  <span className="saas-nav-item__label">
                    Retry{journeyError.requestId ? ` (${journeyError.requestId})` : ''}
                  </span>
                </button>
              </div>
            ) : !journey ? (
              <div className="saas-nav-group">
                <LoadingState label="Loading menu…" />
              </div>
            ) : null}

            {journeySteps.length > 0 ? (
              <div className="saas-nav-group" data-testid="nav-journey">
                <span className="saas-group-header">My Journey</span>
                {journeySteps.map(renderJourneyBtn)}
              </div>
            ) : null}

            {journeyTools.length > 0 ? (
              <div className="saas-nav-group" data-testid="nav-tools">
                <span className="saas-group-header">Tools</span>
                {journeyTools.map(renderJourneyBtn)}
              </div>
            ) : null}

            {adminItems.length > 0 ? (
              <div className="saas-nav-group">
                <button
                  type="button"
                  className="saas-accordion-header"
                  onClick={() => setAdminExpanded((prev) => !prev)}
                  aria-expanded={adminOpen}
                >
                  <span>Administration</span>
                  {adminOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                {adminOpen ? adminItems.map(renderNavBtn) : null}
              </div>
            ) : null}
          </nav>
        </aside>

        {/* Main Container */}
        <main className="saas-main">
          <Suspense fallback={<LoadingState label="Loading view..." />}>
            {activeTab === 'dashboard' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {me ? <DashboardPage userId={me.profile.id} /> : <LoadingState />}
              </RequireAuth>
            )}
            {activeTab === 'reports' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {second && third === 'print' ? (
                  <ReportPrintPage
                    code={second}
                    query={hashQuery}
                    onBack={() => {
                      const qs = hashQuery.toString();
                      navigate(`/reports/${second}${qs ? `?${qs}` : ''}`);
                    }}
                  />
                ) : second ? (
                  <ReportViewerPage code={second} query={hashQuery} navigate={navigate} />
                ) : (
                  <ReportsCataloguePage
                    onOpen={(code) => {
                      navigate(`/reports/${code}`);
                    }}
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'report-columns' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <ReportColumnDefaultsEditor />
              </RequireAuth>
            )}
            {activeTab === 'notifications' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {me ? (
                  <NotificationCentrePage
                    userId={me.profile.id}
                    onOpen={openNotification}
                    onPreferences={() => {
                      navigate('/notification-preferences');
                    }}
                  />
                ) : null}
              </RequireAuth>
            )}
            {activeTab === 'notification-preferences' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <NotificationPreferencesPage />
              </RequireAuth>
            )}
            {activeTab === 'notification-admin' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <NotificationAdminPage />
              </RequireAuth>
            )}
            {activeTab === 'dashboard-config' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <DashboardLayoutEditor />
              </RequireAuth>
            )}
            {activeTab === 'mywork' && (
              <MyWorkView
                stepFilter={hashQuery.get('step')}
                journeyCode={hashQuery.get('journey')}
                journey={journey}
                journeyFetchedAt={journeyQuery.data?.at ?? 0}
                onNavigate={navigate}
                onOpenAudit={() => {
                  navigate('/container-audit');
                }}
              />
            )}
            {activeTab === 'gs-new' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <NewGoodsSlipPage
                  onOpenTag={(id) => {
                    navigate(`/gs/${id}/tag`);
                  }}
                  onOpenGs={(id) => {
                    navigate(`/gs/${id}`);
                  }}
                />
              </RequireAuth>
            )}
            {activeTab === 'gs' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {second && third === 'handover' ? (
                  <HandoverPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onOpenTransfer={(id) => {
                      navigate(`/custody/transfers/${id}`);
                    }}
                  />
                ) : second && third === 'inspection' ? (
                  <InspectionPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second && third === 'rm-actions' ? (
                  <RmSegregationPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onOpenSlip={() => {
                      navigate(`/gs/${second}/replacement-slip`);
                    }}
                  />
                ) : second && third === 'final-actions' ? (
                  <FinalActionsPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second && third === 'resolution-board' ? (
                  <ResolutionBoardPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onRevise={() => {
                      navigate(`/gs/${second}/rm-actions`);
                    }}
                    onOpenCnDecision={() => {
                      navigate(`/gs/${second}/cn-decision`);
                    }}
                  />
                ) : second && third === 'cn-decision' ? (
                  <RmCnDecisionPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onSubmitted={() => {
                      navigate(`/gs/${second}/resolution-board`);
                    }}
                  />
                ) : second && third === 'party-notification' ? (
                  <PartyNotificationPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second && third === 'closure-certificate' ? (
                  <ClosureCertificatePage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second && third === 'replacement-slip' ? (
                  <ReplacementSlipPrintPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second && third === 'rm-review' ? (
                  <RmReviewPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onOpenTransfer={(trfId) => {
                      navigate(`/custody/transfers/${trfId}/note`);
                    }}
                  />
                ) : second && third === 'itemization' ? (
                  <ItemizationPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    {...(can('transfer_slips', 'view') || isSuperAdmin
                      ? {
                          onOpenSlip: (id: string) => {
                            navigate(`/transfer-slips/${id}`);
                          },
                        }
                      : {})}
                  />
                ) : second && third === 'unboxing' ? (
                  <UnboxingPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                    onOpenGs={(id) => {
                      navigate(`/gs/${id}`);
                    }}
                    onNext={(id) => {
                      navigate(`/gs/${id}/itemization`);
                    }}
                  />
                ) : second && third === 'tag' ? (
                  <GsTagPrintPage
                    gsId={second}
                    onBack={() => {
                      navigate(`/gs/${second}`);
                    }}
                  />
                ) : second ? (
                  <GoodsSlipDetailPage
                    gsId={second}
                    onBack={() => {
                      navigate('/gs');
                    }}
                    onOpenTag={(id) => {
                      navigate(`/gs/${id}/tag`);
                    }}
                    onOpenUnboxing={(id) => {
                      navigate(`/gs/${id}/unboxing`);
                    }}
                    onOpenItemization={(id) => {
                      navigate(`/gs/${id}/itemization`);
                    }}
                    onOpenInspection={(id) => {
                      navigate(`/gs/${id}/inspection`);
                    }}
                    onOpenRmActions={(id) => {
                      navigate(`/gs/${id}/rm-actions`);
                    }}
                    onOpenRmReview={(id) => {
                      navigate(`/gs/${id}/rm-review`);
                    }}
                    onOpenFinalActions={(id) => {
                      navigate(`/gs/${id}/final-actions`);
                    }}
                    onOpenReplacementSlip={(id) => {
                      navigate(`/gs/${id}/replacement-slip`);
                    }}
                    onOpenResolutionBoard={(id) => {
                      navigate(`/gs/${id}/resolution-board`);
                    }}
                    onOpenCnDecision={(id) => {
                      navigate(`/gs/${id}/cn-decision`);
                    }}
                    onOpenHandover={(id) => {
                      navigate(`/gs/${id}/handover`);
                    }}
                    onOpenPartyNotification={(id) => {
                      navigate(`/gs/${id}/party-notification`);
                    }}
                    onOpenClosureCertificate={(id) => {
                      navigate(`/gs/${id}/closure-certificate`);
                    }}
                    onNavigate={navigate}
                  />
                ) : (
                  <GoodsSlipListPage
                    key={window.location.hash}
                    initialStatuses={hashQuery.getAll('status')}
                    initialDateFrom={hashQuery.get('date_from')}
                    initialDateTo={hashQuery.get('date_to')}
                    initialFlags={hashQuery.getAll('flag')}
                    onClearFilters={() => {
                      navigate('/gs');
                    }}
                    canCreate={can('goods_slips', 'create')}
                    onOpen={(id) => {
                      navigate(`/gs/${id}`);
                    }}
                    onNew={() => {
                      setActiveTab('gs-new');
                    }}
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'accounts' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <DocumentQueuePage
                  onOpenGs={(id) => {
                    navigate(`/gs/${id}`);
                  }}
                />
              </RequireAuth>
            )}
            {activeTab === 'credit-notes' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {second && third === 'print' ? (
                  <CreditNotePrintPage
                    cnId={second}
                    onBack={() => {
                      navigate(`/credit-notes/${second}`);
                    }}
                  />
                ) : second ? (
                  <CreditNoteWorkspacePage
                    cnId={second}
                    onBack={() => {
                      navigate('/credit-notes');
                    }}
                    onOpenPrint={() => {
                      navigate(`/credit-notes/${second}/print`);
                    }}
                  />
                ) : (
                  <AccountsCreditNoteQueuePage
                    onOpenCn={(id) => {
                      navigate(`/credit-notes/${id}`);
                    }}
                    onOpenGs={(id) => {
                      navigate(`/gs/${id}`);
                    }}
                    onOpenCnDecision={(id) => {
                      navigate(`/gs/${id}/cn-decision`);
                    }}
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'approvals' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <ApprovalsPage
                  onOpenItemization={(id) => {
                    navigate(`/gs/${id}/itemization`);
                  }}
                />
              </RequireAuth>
            )}
            {activeTab === 'container-audit' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <DailyAuditPage />
              </RequireAuth>
            )}
            {activeTab === 'pendencies' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                <PendencyRegisterPage
                  onOpenGs={(id) => {
                    navigate(`/gs/${id}`);
                  }}
                />
              </RequireAuth>
            )}
            {activeTab === 'custody' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {second === 'transfers' && third && segments[3] === 'note' ? (
                  <TransferNotePrintPage
                    transferId={third}
                    onBack={() => {
                      navigate(`/custody/transfers/${third}`);
                    }}
                  />
                ) : second === 'transfers' && third ? (
                  <TransferDetailPage
                    transferId={third}
                    onBack={() => {
                      navigate('/custody');
                    }}
                    onOpenTransfer={(id) => {
                      navigate(`/custody/transfers/${id}`);
                    }}
                    onOpenNote={(id) => {
                      navigate(`/custody/transfers/${id}/note`);
                    }}
                    onOpenGs={(id) => {
                      navigate(`/gs/${id}`);
                    }}
                  />
                ) : (
                  <TransfersPage
                    key={window.location.hash}
                    initialStatus={hashQuery.get('status') ?? ''}
                    tab={second === 'store' ? 'store' : 'transfers'}
                    onTab={(t) => {
                      navigate(t === 'store' ? '/custody/store' : '/custody');
                    }}
                    onOpen={(id) => {
                      navigate(`/custody/transfers/${id}`);
                    }}
                    onOpenGs={(id) => {
                      navigate(`/gs/${id}`);
                    }}
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'servicing' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('servicing', 'view') || isSuperAdmin ? (
                  second === 'allot' ? (
                    <AllotBatchPage
                      currentUserName={me?.profile.full_name ?? 'Coordinator'}
                      onBack={() => {
                        navigate('/servicing');
                      }}
                      onCreated={() => {
                        navigate('/servicing');
                      }}
                    />
                  ) : second === 'batches' && third && segments[3] === 'receive' ? (
                    <ReceiveBatchPage
                      batchId={third}
                      onBack={() => {
                        navigate('/servicing');
                      }}
                      onCompleted={() => {
                        navigate('/servicing');
                      }}
                    />
                  ) : (
                    <TechnicianBoardPage
                      canAllot={isCoordinatorOrAdmin}
                      onAllot={() => {
                        navigate('/servicing/allot');
                      }}
                      onReceive={(id) => {
                        navigate(`/servicing/batches/${id}/receive`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Servicing Workshop."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'batteries' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('inventory', 'view') || isSuperAdmin ? (
                  <BatteryStockPage canManage={isSpmOrAdmin} canApprove={isAdminOrRm} />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Battery Inventory."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'inventory' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('inventory', 'view') || isSuperAdmin ? (
                  <InventoryPage
                    tab={toInventoryTab(second)}
                    onTab={(t) => {
                      navigate(`/inventory/${t}`);
                    }}
                    onOpenTransfer={(id) => {
                      navigate(`/custody/transfers/${id}`);
                    }}
                  />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Inventory."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'dismantling' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('dismantling', 'view') || isSuperAdmin ? (
                  second === 'batches' && third && segments[3] === 'recover' ? (
                    <RecoveryPage
                      batchId={third}
                      onBack={() => {
                        navigate('/dismantling');
                      }}
                      onCompleted={() => {
                        navigate('/dismantling');
                      }}
                    />
                  ) : (
                    <DismantlingQueuePage
                      onRecover={(id) => {
                        navigate(`/dismantling/batches/${id}/recover`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Dismantling."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'scrap' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('dismantling', 'view') || isSuperAdmin ? (
                  <ScrapRegisterPage />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Scrap Register."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'store-issues' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('inventory', 'view') || can('custody', 'view') || isSuperAdmin ? (
                  second && third === 'print' ? (
                    <StoreIssuePrintPage
                      issueId={second}
                      onBack={() => {
                        navigate('/store-issues');
                      }}
                    />
                  ) : (
                    <StoreIssuePage
                      onPrint={(id: string) => {
                        navigate(`/store-issues/${id}/print`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Store Issues."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'dispatch' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('dispatch', 'view') || isSuperAdmin ? (
                  <DispatchQueuePage />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Dispatch Queue."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'department-routing' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('department_routing', 'view') || isSuperAdmin ? (
                  second && third === 'print' ? (
                    <DepartmentIssueNotePrintPage
                      routingId={second}
                      onBack={() => {
                        navigate('/department-routing');
                      }}
                    />
                  ) : second === 'receiving' ? (
                    <DepartmentReceivingQueuePage
                      onOpenGs={(id: string) => {
                        navigate(`/gs/${id}`);
                      }}
                      onOpenPrint={(id: string) => {
                        navigate(`/department-routing/${id}/print`);
                      }}
                    />
                  ) : (
                    <RmRoutingQueuePage
                      canPlan={can('department_routing', 'create') || isSuperAdmin}
                      onOpenGs={(id: string) => {
                        navigate(`/gs/${id}`);
                      }}
                      onOpenFinalActions={(id: string) => {
                        navigate(`/gs/${id}/final-actions`);
                      }}
                      onOpenPrint={(id: string) => {
                        navigate(`/department-routing/${id}/print`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Department Routing."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'transfer-slips' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('transfer_slips', 'view') || isSuperAdmin ? (
                  second ? (
                    <TransferSlipDetailPage
                      slipId={second}
                      onBack={() => {
                        navigate('/transfer-slips');
                      }}
                      onOpenGs={(id: string) => {
                        navigate(`/gs/${id}`);
                      }}
                    />
                  ) : (
                    <TransferSlipsPage
                      canGenerate={can('transfer_slips', 'create') || isSuperAdmin}
                      onOpenGs={(id: string) => {
                        navigate(`/gs/${id}`);
                      }}
                      onOpenSlip={(id: string) => {
                        navigate(`/transfer-slips/${id}`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Transfer Slips."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'department-issue' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('department_routing', 'view') || isSuperAdmin ? (
                  <DepartmentIssuePage
                    canIssue={can('department_routing', 'approve') || isSuperAdmin}
                    onOpenGs={(id: string) => {
                      navigate(`/gs/${id}`);
                    }}
                    onOpenPrint={(id: string) => {
                      navigate(`/department-routing/${id}/print`);
                    }}
                  />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Department Issue."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'department-receiving' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('department_routing', 'view') || isSuperAdmin ? (
                  <DepartmentReceivingQueuePage
                    onOpenGs={(id: string) => {
                      navigate(`/gs/${id}`);
                    }}
                    onOpenPrint={(id: string) => {
                      navigate(`/department-routing/${id}/print`);
                    }}
                  />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Department Receiving."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'accounts-entry' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('ac_entry', 'view') || isSuperAdmin ? (
                  second ? (
                    <AccountsEntryPage
                      gsId={second}
                      onBack={() => {
                        navigate('/accounts-entry');
                      }}
                      onOpenGs={(id: string) => {
                        navigate(`/gs/${id}`);
                      }}
                      onOpenPartyNotification={(id: string) => {
                        navigate(`/gs/${id}/party-notification`);
                      }}
                    />
                  ) : (
                    <AccountsEntryQueuePage
                      onOpen={(id: string) => {
                        navigate(`/accounts-entry/${id}`);
                      }}
                    />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view the Accounts entry."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'dispatch-slips' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('dispatch', 'view') || isSuperAdmin ? (
                  <DispatchSlipsPage
                    onOpenGs={(id: string) => {
                      navigate(`/gs/${id}`);
                    }}
                  />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Dispatch Slips."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'users' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('users', 'view') || isSuperAdmin ? (
                  second && third === 'activity' ? (
                    <UserActivityPage
                      userId={second}
                      onBack={() => {
                        navigate('/users');
                      }}
                    />
                  ) : (
                    <UsersView />
                  )
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view User Management."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'search' && (
              <SearchPage initialQuery={hashQuery.get('q') ?? ''} onNavigate={navigate} />
            )}
            {activeTab === 'audit' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('audit', 'view') || isSuperAdmin ? (
                  <AuditExplorerPage />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Audit Explorer."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'permissions' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('roles', 'view') || isSuperAdmin ? (
                  <PermissionMatrixView />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view the Permission Matrix."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'forms' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <FormBuilder />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Form Builder."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'workflow' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <WorkflowDesigner />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Workflow Designer."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'masters' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('masters', 'view') || isSuperAdmin ? (
                  <MastersView />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Master Data Management."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'options' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <OptionSetsManager />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Option Sets."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'field-profiles' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('config', 'view') || isSuperAdmin ? (
                  <ItemFieldProfilesPage />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Item Field Profiles."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'numbering' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <NumberSeriesManager />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Number Series."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'settings' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <SystemSettingsManager />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view System Settings."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'templates' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <PrintTemplatesManager />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Print Templates."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'history' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <ConfigHistoryViewer />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Config History."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'role-journeys' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('config', 'view') || isSuperAdmin ? (
                  <RoleJourneysPage canEdit={can('config', 'configure') || isSuperAdmin} />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Role Journeys."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'intermediate-stores' && (
              <RequireAuth
                onSignIn={() => {
                  setActiveTab('login');
                }}
              >
                {can('intermediate_stores', 'view') || isSuperAdmin ? (
                  <IntermediateStoresPage
                    canCreate={can('intermediate_stores', 'create') || isSuperAdmin}
                    canEdit={can('intermediate_stores', 'edit') || isSuperAdmin}
                    canConfigure={can('intermediate_stores', 'configure') || isSuperAdmin}
                  />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view Intermediate Stores."
                  />
                )}
              </RequireAuth>
            )}
            {activeTab === 'guards' && (
              <RequireAuth onSignIn={() => setActiveTab('login')}>
                {can('config', 'view') || isSuperAdmin ? (
                  <SystemGuardsViewer />
                ) : (
                  <EmptyState
                    title="Access Restricted"
                    hint="You do not have permission to view System Guards."
                  />
                )}
              </RequireAuth>
            )}
          </Suspense>
        </main>
      </div>

      <nav
        className="mobile-bottom-bar no-print"
        aria-label="Mobile Navigation"
        data-testid="mobile-bottom-bar"
      >
        <button
          type="button"
          className={`mobile-bottom-bar__item ${activeTab === 'mywork' ? 'mobile-bottom-bar__item--active' : ''}`}
          onClick={() => {
            setActiveTab('mywork');
          }}
          aria-label="My Work"
        >
          <span>My Work</span>
        </button>
        {signedIn && can('goods_slips', 'view') ? (
          <button
            type="button"
            className={`mobile-bottom-bar__item ${activeTab === 'gs' ? 'mobile-bottom-bar__item--active' : ''}`}
            onClick={() => {
              setActiveTab('gs');
            }}
            aria-label="Goods Slips"
          >
            <span>Goods Slips</span>
          </button>
        ) : null}
        {signedIn && can('goods_slips', 'create') ? (
          <button
            type="button"
            className={`mobile-bottom-bar__item ${activeTab === 'gs-new' ? 'mobile-bottom-bar__item--active' : ''}`}
            onClick={() => {
              setActiveTab('gs-new');
            }}
            aria-label="New GS"
          >
            <span>+ New</span>
          </button>
        ) : null}
        {signedIn && can('dashboards', 'view') ? (
          <button
            type="button"
            className={`mobile-bottom-bar__item ${activeTab === 'dashboard' ? 'mobile-bottom-bar__item--active' : ''}`}
            onClick={() => {
              setActiveTab('dashboard');
            }}
            aria-label="Dashboard"
          >
            <span>Dashboard</span>
          </button>
        ) : null}
        {signedIn ? (
          <button
            type="button"
            className={`mobile-bottom-bar__item ${activeTab === 'notifications' ? 'mobile-bottom-bar__item--active' : ''}`}
            onClick={() => {
              setActiveTab('notifications');
            }}
            aria-label="Notifications"
          >
            <span>Alerts</span>
          </button>
        ) : null}
      </nav>
    </div>
  );
}
