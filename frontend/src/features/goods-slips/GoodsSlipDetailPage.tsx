import { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft,
  ClipboardCheck,
  Clock,
  FileText,
  ListChecks,
  PackageOpen,
  Printer,
  Split,
  Truck,
  FileCheck2,
  Send,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { ClosurePanel } from '@/features/closure/ClosurePanel';
import { ItemsTab } from '@/features/itemization/ItemsTab';
import { ITEMS_VISIBLE, useItemization } from '@/features/itemization/useItemization';
import { InspectionTab } from '@/features/inspection/InspectionTab';
import { RejectionsTab } from '@/features/inspection/RejectionsTab';
import { INSPECTION_VISIBLE, useInspection } from '@/features/inspection/useInspection';
import { PendencyTab } from '@/features/pendency/PendencyTab';
import { GsActivityTab } from '@/features/goods-slips/GsActivityTab';
import { StampPanel } from '@/features/management-approval/ApprovalStamp';
import { departmentRoutingApi } from '@/features/department-routing/api';
import type {
  GsReconciliationOut,
  DepartmentLegOut,
  GsRoutingState,
  DepartmentRoutingOut,
} from '@/features/department-routing/types';
import { DepartmentReconciliationPanel } from '@/features/department-routing/DepartmentReconciliationPanel';
import { DepartmentLegsTimeline } from '@/features/department-routing/DepartmentLegsTimeline';
import { RmRoutingPlanModal } from '@/features/department-routing/RmRoutingPlanModal';
import { DepartmentReceiveModal } from '@/features/department-routing/DepartmentReceiveModal';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import { gsApi, type GsDetail } from './api';
import { FlagIcons, StatusChip } from './display';
import { formatDate, formatDateTime, humanize } from './format';
import { GateDocumentsList } from './GateDocumentsList';
import { useStatusLabels } from './statusLabels';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenTag: (id: string) => void;
  onOpenUnboxing: (id: string) => void;
  onOpenItemization: (id: string) => void;
  onOpenInspection: (id: string) => void;
  onOpenRmActions?: (id: string) => void;
  onOpenRmReview?: (id: string) => void;
  /** Change plan Phase 7 (AMD-16): RM final actions + A/c Actions slip. */
  onOpenFinalActions?: (id: string) => void;
  onOpenReplacementSlip?: (id: string) => void;
  onOpenResolutionBoard?: (id: string) => void;
  onOpenHandover?: (id: string) => void;
  onOpenCnDecision?: (id: string) => void;
  onOpenPartyNotification?: (id: string) => void;
  onOpenClosureCertificate?: (id: string) => void;
  /** Hash navigation for the closure checklist's fix links. */
  onNavigate?: (path: string) => void;
}

type Tab = 'overview' | 'items' | 'inspection' | 'rejections' | 'pendency' | 'closure' | 'timeline' | 'department_routing';

// P3-07: closure checklist from the in-process stage on (§6.5).
const CLOSURE_VISIBLE = new Set([
  'IN_PROCESS',
  'COMMERCIAL_RESOLUTION',
  'AWAITING_NOTIFICATION',
  'CLOSED',
]);
const NOTIFY_VISIBLE = new Set(['IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION']);

// Step-2 evidence exists from GATE_CREATED on (start) and stays viewable afterwards.
const UNBOXING_VISIBLE = new Set(['GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION']);
// Step-3 work happens in these statuses (Counting, then Categorisation; AMD-08).
const STEP3_ACTIVE = new Set(['ITEMIZATION', 'CATEGORISATION']);

const RM_ACTIONS_VISIBLE = new Set([
  'RM_REVIEW',
  'IN_PROCESS',
  'REPAIR_PENDING',
  'AWAITING_PARTS',
  'REPAIR_IN_PROGRESS',
  'STAGED_FOR_DISPATCH',
  'DISPATCHED',
  'CLOSED',
]);

export function GoodsSlipDetailPage({
  gsId,
  onBack,
  onOpenTag,
  onOpenUnboxing,
  onOpenItemization,
  onOpenInspection,
  onOpenRmActions,
  onOpenRmReview,
  onOpenFinalActions,
  onOpenReplacementSlip,
  onOpenResolutionBoard,
  onOpenHandover,
  onOpenCnDecision,
  onOpenPartyNotification,
  onOpenClosureCertificate,
  onNavigate,
}: Props) {
  const fetcher = useCallback(() => gsApi.detail(gsId), [gsId]);
  const query = useApiQuery<GsDetail>(fetcher);
  const detail = query.data?.goods_slip.id === gsId ? query.data : null;
  const { can, me } = useAuth();
  const isSuperAdmin = Boolean(me?.profile.is_super_admin);
  const itemsVisible =
    !!detail && ITEMS_VISIBLE.has(detail.goods_slip.status) && can('itemization', 'view');
  const items = useItemization(gsId, itemsVisible);
  const inspectionVisible =
    !!detail && INSPECTION_VISIBLE.has(detail.goods_slip.status) && can('inspection', 'view');
  const inspection = useInspection(gsId, inspectionVisible);
  const error = query.error;
  const load = query.reload;
  const [tab, setTab] = useState<Tab>('overview');
  const [cancelOpen, setCancelOpen] = useState(false);
  const statusLabel = useStatusLabels(); // AMD-08 step / status labels from configuration

  const [reconData, setReconData] = useState<GsReconciliationOut | null>(null);
  const [loadingRecon, setLoadingRecon] = useState(false);
  const [deptLegs, setDeptLegs] = useState<DepartmentLegOut[]>([]);
  const [dispatchModalState, setDispatchModalState] = useState<GsRoutingState | null>(null);
  const [receiveModalRouting, setReceiveModalRouting] = useState<DepartmentRoutingOut | null>(null);

  // Only users who may see department routing load it (e.g. Accounts got 403s here; Phase 7 check).
  const canViewRouting = isSuperAdmin || can('department_routing', 'view');
  // T4 / DEC-55: the RM plans (department_routing/create); the store issues (approve).
  const canPlanRouting = isSuperAdmin || can('department_routing', 'create');
  const loadDeptData = useCallback(() => {
    if (!canViewRouting) return;
    setLoadingRecon(true);
    departmentRoutingApi
      .getGsReconciliation(gsId)
      .then(setReconData)
      .catch(() => setReconData(null))
      .finally(() => setLoadingRecon(false));

    departmentRoutingApi
      .getGsDepartmentLegs(gsId)
      .then(setDeptLegs)
      .catch(() => setDeptLegs([]));
  }, [gsId, canViewRouting]);

  useEffect(() => {
    loadDeptData();
  }, [loadDeptData]);

  const handleOpenDispatchModal = async () => {
    try {
      const state = await departmentRoutingApi.getGsRoutingState(gsId);
      setDispatchModalState(state);
    } catch (err: any) {
      alert(err?.message || 'Failed to open department routing modal');
    }
  };

  const back = (
    <Button type="button" variant="ghost" onClick={onBack} className="no-print">
      <ArrowLeft size={16} aria-hidden="true" /> Goods slips
    </Button>
  );

  if (error) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Goods slip</h1>
        <ErrorState error={error} onRetry={load} />
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Goods slip</h1>
        <LoadingState />
      </div>
    );
  }

  const gs = detail.goods_slip;
  const rmActionsVisible = RM_ACTIONS_VISIBLE.has(gs.status);
  const label = (key: string, fallback: string) => detail.labels_snapshot[key]?.label ?? fallback;
  // Only tabs whose data exists are shown (no placeholder tabs).
  const tabs: Array<{ id: Tab; title: string }> = [
    { id: 'overview', title: 'Overview' },
    ...(itemsVisible && (items.data?.items.length ?? 0) > 0
      ? [{ id: 'items' as const, title: 'Items' }]
      : []),
    ...(inspectionVisible && (inspection.data?.lines.length ?? 0) > 0
      ? [{ id: 'inspection' as const, title: 'Inspection' }]
      : []),
    ...(inspectionVisible && (inspection.data?.totals.total_rejected_qty ?? 0) > 0
      ? [{ id: 'rejections' as const, title: 'Rejections' }]
      : []),
    ...(gs.has_open_pendency || rmActionsVisible
      ? [{ id: 'pendency' as const, title: `Pendency${gs.has_open_pendency ? ' (BP)' : ''}` }]
      : []),
    ...(gs.status === 'HELD_AT_INTERMEDIATE_STORE' || deptLegs.length > 0
      ? [{ id: 'department_routing' as const, title: 'Dept Routing & Recon' }]
      : []),
    ...(CLOSURE_VISIBLE.has(gs.status) && onNavigate
      ? [
          {
            id: 'closure' as const,
            title: gs.status === 'CLOSED' ? 'Closure' : 'Closure checklist',
          },
        ]
      : []),
    { id: 'timeline' as const, title: 'Activity' },
  ];

  const transport = [
    gs.courier_name,
    gs.docket_no,
    gs.vehicle_no,
    gs.transporter_name,
    gs.rep_name,
    gs.rep_contact,
  ].filter(Boolean);
  const legacyDocImage =
    typeof detail.form_values.gate_doc_image === 'string'
      ? detail.form_values.gate_doc_image
      : null;

  return (
    <div className="page">
      {back}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '0.75rem',
          flexWrap: 'wrap',
          alignItems: 'flex-start',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
            {gs.gs_no}
          </h1>
          <p
            className="page__subtitle"
            style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}
          >
            <StatusChip status={gs.status} />
            {gs.has_open_pendency ? (
              <Badge variant="warning">
                <Clock size={12} style={{ marginRight: '0.25rem', verticalAlign: 'middle' }} />
                Pending (BP)
              </Badge>
            ) : null}
            <FlagIcons flags={gs} />
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {gs.status !== 'CANCELLED' ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenTag(gs.id);
              }}
            >
              <Printer size={16} aria-hidden="true" /> Print tag
            </Button>
          ) : null}
          {UNBOXING_VISIBLE.has(gs.status) ? (
            <Button
              type="button"
              variant={STEP3_ACTIVE.has(gs.status) ? 'outline' : 'primary'}
              onClick={() => {
                onOpenUnboxing(gs.id);
              }}
            >
              <PackageOpen size={16} aria-hidden="true" /> {statusLabel('UNBOXING')}
            </Button>
          ) : null}
          {itemsVisible ? (
            <Button
              type="button"
              variant={STEP3_ACTIVE.has(gs.status) ? 'primary' : 'outline'}
              onClick={() => {
                onOpenItemization(gs.id);
              }}
            >
              <ListChecks size={16} aria-hidden="true" />{' '}
              {gs.status === 'CATEGORISATION'
                ? statusLabel('CATEGORISATION')
                : statusLabel('ITEMIZATION')}
            </Button>
          ) : null}
          {inspectionVisible ? (
            <Button
              type="button"
              variant={gs.status === 'INSPECTION' ? 'primary' : 'outline'}
              onClick={() => {
                onOpenInspection(gs.id);
              }}
            >
              <ClipboardCheck size={16} aria-hidden="true" /> Inspection
            </Button>
          ) : null}
          {gs.status === 'RM_REVIEW' && onOpenRmReview ? (
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                onOpenRmReview(gs.id);
              }}
            >
              <FileCheck2 size={16} aria-hidden="true" /> RM Review
            </Button>
          ) : null}
          {gs.status === 'HELD_AT_INTERMEDIATE_STORE' && canPlanRouting ? (
            <Button type="button" variant="primary" onClick={handleOpenDispatchModal}>
              <Send size={16} aria-hidden="true" /> Plan Routing
            </Button>
          ) : null}
          {gs.status === 'HELD_AT_INTERMEDIATE_STORE' &&
          onOpenFinalActions &&
          (can('final_actions', 'view') || isSuperAdmin) ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenFinalActions(gs.id);
              }}
            >
              <Split size={16} aria-hidden="true" /> Final Actions
            </Button>
          ) : null}
          {rmActionsVisible && onOpenRmActions ? (
            <Button
              type="button"
              variant={gs.status === 'RM_REVIEW' && !onOpenRmReview ? 'primary' : 'outline'}
              onClick={() => {
                onOpenRmActions(gs.id);
              }}
            >
              <Split size={16} aria-hidden="true" /> RM Actions
            </Button>
          ) : null}
          {rmActionsVisible && onOpenReplacementSlip ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenReplacementSlip(gs.id);
              }}
            >
              <FileText size={16} aria-hidden="true" /> Replacement Slip
            </Button>
          ) : null}
          {rmActionsVisible && onOpenResolutionBoard ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenResolutionBoard(gs.id);
              }}
            >
              <ClipboardCheck size={16} aria-hidden="true" /> Resolution Board
            </Button>
          ) : null}
          {rmActionsVisible && onOpenCnDecision ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenCnDecision(gs.id);
              }}
            >
              <FileCheck2 size={16} aria-hidden="true" /> CN Decision
            </Button>
          ) : null}
          {NOTIFY_VISIBLE.has(gs.status) &&
          onOpenPartyNotification &&
          can('credit_notes', 'view') ? (
            <Button
              type="button"
              variant={gs.status === 'AWAITING_NOTIFICATION' ? 'primary' : 'outline'}
              onClick={() => {
                onOpenPartyNotification(gs.id);
              }}
            >
              <Send size={16} aria-hidden="true" /> Notify party
            </Button>
          ) : null}
          {gs.status === 'IN_PROCESS' && onOpenHandover && can('custody', 'view') ? (
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                onOpenHandover(gs.id);
              }}
            >
              <Truck size={16} aria-hidden="true" /> Handover
            </Button>
          ) : null}
          {detail.can_cancel ? (
            <Button
              type="button"
              variant="danger"
              onClick={() => {
                setCancelOpen(true);
              }}
            >
              Cancel GS
            </Button>
          ) : null}
        </div>
      </div>

      {gs.missing_documentation ? (
        <div className="banner" role="status" style={{ marginBottom: '1rem' }}>
          {typeof detail.labels_snapshot.accompanying_doc?.value_label === 'string'
            ? detail.labels_snapshot.accompanying_doc.value_label
            : (detail.labels_snapshot.no_document?.label ?? humanize('missing_documentation'))}
          {' — '}
          verify at Step-2.
        </div>
      ) : null}

      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setTab(t.id);
            }}
          >
            {t.title}
          </button>
        ))}
      </div>

      {tab === 'overview' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <section className="card" style={{ padding: '1rem' }}>
            <dl className="kv">
              {gs.return_type_code ? (
                <div>
                  <dt>{label('return_type', 'Return type')}</dt>
                  <dd>{gs.return_type_label ?? humanize(gs.return_type_code)}</dd>
                </div>
              ) : null}
              {gs.gate_entry_no ? (
                <div>
                  <dt>
                    {label('gate_entry_no', 'Gate entry no.')} /{' '}
                    {label('gate_entry_date', 'Gate entry date')}
                  </dt>
                  <dd>
                    {String(gs.gate_entry_no)} · {formatDate(gs.gate_entry_date)}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>{label('party_name', 'Party')}</dt>
                <dd>
                  {gs.party_name}
                  {gs.party_is_provisional ? ' (provisional)' : ''}
                </dd>
              </div>
              <div>
                <dt>
                  {label('state', 'State')} / {label('station', 'Station')}
                </dt>
                <dd>
                  {[gs.state_name, gs.station_name].filter(Boolean).join(' / ')}
                  {gs.state_station_overridden ? ' (overridden at gate)' : ''}
                </dd>
              </div>
              <div>
                <dt>{label('carton_count', label('box_count', 'Cartons'))}</dt>
                <dd>{gs.carton_count}</dd>
              </div>
              <div>
                <dt>{label('delivery_mode', 'Delivery mode')}</dt>
                <dd>
                  {gs.delivery_mode_label ?? humanize(gs.delivery_mode_code)}
                  {transport.length > 0 ? ` · ${transport.join(' · ')}` : ''}
                </dd>
              </div>
              <div>
                <dt>Gate documents</dt>
                <dd>
                  {gs.missing_documentation ? (
                    (detail.labels_snapshot.no_document?.label ?? humanize('missing_documentation'))
                  ) : (
                    <GateDocumentsList documents={gs.documents} />
                  )}
                  {/* Form v1 stored one picture in the form values; shown for those GS only. */}
                  {legacyDocImage ? (
                    <div style={{ marginTop: '0.5rem' }}>
                      <a
                        href={legacyDocImage}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'inline-block' }}
                        title="Click to view full document picture"
                      >
                        <img
                          src={legacyDocImage}
                          alt="Physical document attached at gate"
                          style={{
                            maxWidth: '160px',
                            maxHeight: '120px',
                            borderRadius: '6px',
                            border: '1px solid var(--color-border)',
                          }}
                        />
                      </a>
                    </div>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>
                  {formatDateTime(gs.created_at)}
                  {gs.created_by_name ? ` · ${gs.created_by_name}` : ''}
                </dd>
              </div>
              {gs.cancel_reason ? (
                <div>
                  <dt>Cancelled</dt>
                  <dd>
                    {formatDateTime(gs.cancelled_at)} · {gs.cancel_reason}
                  </dd>
                </div>
              ) : null}
            </dl>
          </section>

          {/* DEC-70: Management e-approval stamp + Verify (nothing when not approved). */}
          <StampPanel gsId={gs.id} status={gs.status} />

          {detail.tasks.length > 0 ? (
            <section>
              <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Tasks</h2>
              <ul
                style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}
              >
                {detail.tasks.map((t) => (
                  <li key={t.id} className="card" style={{ padding: '0.75rem 1rem' }}>
                    <strong>{t.step_label ?? t.step_code}</strong> ·{' '}
                    {humanize(t.assigned_role_code)} · {humanize(t.status)}
                    {t.due_at ? (
                      <span style={{ color: 'var(--color-muted)' }}>
                        {' '}
                        · due {formatDateTime(t.due_at)}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {detail.attachments.length > 0 ? (
            <section>
              <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Attachments</h2>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {detail.attachments.map((a) => (
                  <li key={`${a.kind}-${a.status}`}>
                    {humanize(a.kind)} · {humanize(a.status)}: {a.count}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : tab === 'items' ? (
        <ItemsTab
          state={items.data ?? null}
          error={items.error}
          loading={items.loading}
          onRetry={items.reload}
        />
      ) : tab === 'inspection' ? (
        <InspectionTab
          data={inspection.data ?? null}
          loading={inspection.loading}
          onOpenInspectionPage={() => {
            onOpenInspection(gs.id);
          }}
        />
      ) : tab === 'rejections' ? (
        <RejectionsTab data={inspection.data ?? null} loading={inspection.loading} />
      ) : tab === 'pendency' ? (
        <PendencyTab gsId={gs.id} onCleared={load} />
      ) : tab === 'department_routing' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <DepartmentReconciliationPanel
            reconciliation={reconData}
            loading={loadingRecon}
            onRefresh={loadDeptData}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '0.5rem',
              }}
            >
              <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0 }}>
                Department Dispatches & Timeline Legs
              </h3>
              {gs.status === 'HELD_AT_INTERMEDIATE_STORE' && canPlanRouting ? (
                <Button type="button" variant="primary" onClick={handleOpenDispatchModal}>
                  <Send size={16} aria-hidden="true" /> Plan Routing
                </Button>
              ) : null}
            </div>
            <DepartmentLegsTimeline
              legs={deptLegs}
              onPrintRoutingNote={(routingId) =>
                onNavigate?.(`/department-routing/${routingId}/print`)
              }
              onReceiveRouting={(routingId) => {
                departmentRoutingApi.getRouting(routingId).then(setReceiveModalRouting);
              }}
              canReceive={can('department_routing', 'edit') || isSuperAdmin}
            />
          </div>
        </div>
      ) : tab === 'closure' && onNavigate ? (
        <ClosurePanel
          gsId={gs.id}
          onNavigate={onNavigate}
          onOpenCertificate={() => {
            onOpenClosureCertificate?.(gs.id);
          }}
          onChanged={load}
        />
      ) : (
        <GsActivityTab gsId={gs.id} />
      )}

      {cancelOpen ? (
        <CancelDialog
          gsNo={gs.gs_no}
          onClose={() => {
            setCancelOpen(false);
          }}
          onConfirm={async (reason) => {
            query.setData(await gsApi.cancel(gs.id, reason));
            setCancelOpen(false);
          }}
        />
      ) : null}
      {dispatchModalState && (
        <RmRoutingPlanModal
          state={dispatchModalState}
          canPlan={canPlanRouting}
          onClose={() => setDispatchModalState(null)}
          onSuccess={() => {
            setDispatchModalState(null);
            load();
            loadDeptData();
          }}
        />
      )}

      {receiveModalRouting && (
        <DepartmentReceiveModal
          routing={receiveModalRouting}
          onClose={() => setReceiveModalRouting(null)}
          onSuccess={() => {
            setReceiveModalRouting(null);
            load();
            loadDeptData();
          }}
        />
      )}
    </div>
  );
}

function CancelDialog({
  gsNo,
  onClose,
  onConfirm,
}: {
  gsNo: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <Modal isOpen onClose={onClose} title={`Cancel ${gsNo}`}>
      <label
        htmlFor="cancel-reason"
        style={{ display: 'block', fontWeight: 500, marginBottom: '0.375rem' }}
      >
        Reason (mandatory)
      </label>
      <Textarea
        id="cancel-reason"
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      {error ? (
        <div style={{ marginTop: '0.75rem' }}>
          <ErrorState error={error} title="Cancellation failed" />
        </div>
      ) : null}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          justifyContent: 'flex-end',
          marginTop: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
          Keep GS
        </Button>
        <Button
          type="button"
          variant="danger"
          isLoading={busy}
          disabled={reason.trim().length < 3}
          onClick={() => {
            setBusy(true);
            setError(null);
            onConfirm(reason.trim())
              .catch((err: unknown) => {
                setError(toApiError(err));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          Cancel GS
        </Button>
      </div>
    </Modal>
  );
}
