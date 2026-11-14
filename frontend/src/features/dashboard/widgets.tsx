import type { ReactNode } from 'react';

import { hashPath } from '@/app/router';
import { age, humanize } from '@/features/goods-slips/format';

import type {
  AccountsQueueData,
  AdminHealthData,
  BatteryData,
  CnIssuedData,
  CnPipelineData,
  ContainerAuditData,
  DismantlingData,
  FunctionalStockData,
  GateTodayData,
  GsPipelineData,
  GsQueueData,
  GsTrendData,
  HazardData,
  MyTasksData,
  NonFunctionalStockData,
  PendencyData,
  TechnicianWipData,
  TransfersData,
} from './api';
import { GroupedBars, HorizontalBars, StackedBars } from './charts';
import { CHART_COLORS, WIDGET_LINKS } from './layout';

/**
 * Widget renderers (P4-01). Every number links to the list screen it was counted from, with the
 * same filter (the API guarantees the numbers match those lists). Routes are UI navigation, not
 * business values; labels of statuses are humanised system codes (as on the list screens).
 */

const num = new Intl.NumberFormat('en-IN');
const money = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

function Kpi({
  label,
  value,
  href,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  href?: string | undefined;
  tone?: 'warning' | 'danger' | 'success' | undefined;
  hint?: string | undefined;
}) {
  const body = (
    <>
      <span className="dash-kpi__value">{value}</span>
      <span className="dash-kpi__label">{label}</span>
      {hint ? <span className="dash-kpi__hint">{hint}</span> : null}
    </>
  );
  const cls = `dash-kpi${tone ? ` dash-kpi--${tone}` : ''}`;
  return href ? (
    <a className={`${cls} dash-kpi--link`} href={`#${href}`}>
      {body}
    </a>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function KpiRow({ children }: { children: ReactNode }) {
  return <div className="dash-kpis">{children}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="dash-empty">{children}</p>;
}

function oldest(iso: string | null): string | undefined {
  return iso ? `oldest ${age(iso)}` : undefined;
}

function fmtDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
  });
}

function fmtMonth(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
  });
}

// --- renderers -----------------------------------------------------------------------------------
function MyTasks({ d }: { d: MyTasksData }) {
  if (d.total === 0) return <Empty>No open tasks for your roles. New work appears here.</Empty>;
  return (
    <>
      <KpiRow>
        <Kpi label="Open tasks" value={num.format(d.total)} href="/mywork" />
        <Kpi
          label="Overdue"
          value={num.format(d.overdue)}
          href="/mywork"
          tone={d.overdue > 0 ? 'danger' : undefined}
        />
      </KpiRow>
      <ul className="dash-list">
        {d.by_step.map((s) => (
          <li key={s.step_code}>
            <a href={`#${hashPath('/mywork', { step: s.step_code })}`}>
              <span>{s.step_label ?? humanize(s.step_code)}</span>
              <span className="dash-list__meta">
                {s.overdue > 0 ? (
                  <span className="dash-chip dash-chip--danger">{s.overdue} overdue</span>
                ) : null}
                <strong>{s.count}</strong>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

function GsPipeline({ d }: { d: GsPipelineData }) {
  if (d.total_open === 0) return <Empty>No open goods slips.</Empty>;
  const rows = d.by_status.filter((s) => s.count > 0);
  return (
    <>
      <KpiRow>
        <Kpi label="Open goods slips" value={num.format(d.total_open)} href="/gs" />
      </KpiRow>
      <HorizontalBars
        label="Open goods slips by status"
        valueName="Goods slips"
        data={rows.map((s) => ({ name: humanize(s.status), value: s.count }))}
      />
      <ul className="dash-list">
        {rows.map((s) => (
          <li key={s.status}>
            <a href={`#${hashPath('/gs', { status: s.status })}`}>
              <span>{humanize(s.status)}</span>
              <span className="dash-list__meta">
                <span className="dash-muted">avg {s.avg_age_days.toFixed(1)} d</span>
                <strong>{s.count}</strong>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

function GateToday({ d }: { d: GateTodayData }) {
  const href = hashPath('/gs', { date_from: d.date, date_to: d.date });
  return (
    <KpiRow>
      <Kpi label="Goods slips today" value={num.format(d.count)} href={href} />
      <Kpi label="Boxes" value={num.format(d.boxes)} />
      {d.missing_documentation > 0 ? (
        <Kpi
          label="Missing documents"
          value={num.format(d.missing_documentation)}
          href={hashPath('/gs', {
            date_from: d.date,
            date_to: d.date,
            flag: 'missing_documentation',
          })}
          tone="warning"
        />
      ) : null}
    </KpiRow>
  );
}

function GsQueue({ d, label, href }: { d: GsQueueData; label: string; href: string }) {
  return (
    <KpiRow>
      <Kpi
        label={label}
        value={num.format(d.count)}
        href={href}
        tone={d.count > 0 ? 'warning' : 'success'}
        hint={oldest(d.oldest_created_at)}
      />
    </KpiRow>
  );
}

function ContainerAudit({ d }: { d: ContainerAuditData }) {
  const done = d.today_status === 'CONFIRMED' || d.today_status === 'LATE';
  return (
    <KpiRow>
      <Kpi
        label="Today's audit"
        value={humanize(d.today_status)}
        href="/container-audit"
        tone={done ? 'success' : 'warning'}
      />
      <Kpi
        label={`Compliance (${String(d.window_days)} days)`}
        value={`${d.compliance_pct.toFixed(1)}%`}
        href="/container-audit"
        tone={d.compliance_pct >= 95 ? 'success' : d.compliance_pct >= 80 ? 'warning' : 'danger'}
        hint={`${String(d.confirmed_on_time)} on time · ${String(d.confirmed_late)} late · ${String(
          d.missed_or_pending,
        )} missed`}
      />
    </KpiRow>
  );
}

function Pendencies({ d }: { d: PendencyData }) {
  return (
    <KpiRow>
      <Kpi
        label="Open pendencies"
        value={num.format(d.open_count)}
        href="/pendencies"
        tone={d.open_count > 0 ? 'warning' : 'success'}
        hint={oldest(d.oldest_opened_at)}
      />
      <Kpi label="Pieces held" value={num.format(d.open_qty)} href="/pendencies" />
      {d.blocking_count > 0 ? (
        <Kpi
          label="Blocking the GS"
          value={num.format(d.blocking_count)}
          href="/pendencies"
          tone="danger"
        />
      ) : null}
    </KpiRow>
  );
}

function Transfers({ d }: { d: TransfersData }) {
  return (
    <KpiRow>
      <Kpi
        label="Awaiting acceptance"
        value={num.format(d.awaiting_acceptance)}
        href={hashPath('/custody', { status: 'INITIATED' })}
        tone={d.awaiting_acceptance > 0 ? 'warning' : undefined}
        hint={oldest(d.oldest_awaiting_at)}
      />
      <Kpi
        label="In discrepancy"
        value={num.format(d.in_discrepancy)}
        href={hashPath('/custody', { status: 'DISCREPANCY' })}
        tone={d.in_discrepancy > 0 ? 'danger' : undefined}
      />
    </KpiRow>
  );
}

function TechnicianWip({ d }: { d: TechnicianWipData }) {
  if (d.open_batches === 0) return <Empty>No batches with technicians.</Empty>;
  return (
    <>
      <KpiRow>
        <Kpi label="Open batches" value={num.format(d.open_batches)} href="/servicing" />
        <Kpi
          label="Pieces with technicians"
          value={num.format(d.pieces_with_technicians)}
          href="/servicing"
        />
        <Kpi
          label="Oldest batch"
          value={d.oldest_age_days === null ? '—' : `${String(d.oldest_age_days)} d`}
          hint={d.avg_age_days === null ? undefined : `avg ${d.avg_age_days.toFixed(1)} d`}
        />
      </KpiRow>
      <ul className="dash-list">
        {d.by_status
          .filter((s) => s.count > 0)
          .map((s) => (
            <li key={s.status}>
              <a href="#/servicing">
                <span>{humanize(s.status)}</span>
                <strong>{s.count}</strong>
              </a>
            </li>
          ))}
      </ul>
    </>
  );
}

function Batteries({ d }: { d: BatteryData }) {
  return (
    <>
      <KpiRow>
        <Kpi label="In battery store" value={num.format(d.total_balance)} href="/batteries" />
        <Kpi label="Installed · 7 days" value={num.format(d.consumed_7d)} href="/batteries" />
        <Kpi label="Installed · 30 days" value={num.format(d.consumed_30d)} href="/batteries" />
      </KpiRow>
      {d.by_type.length === 0 ? (
        <Empty>No active battery types.</Empty>
      ) : (
        <ul className="dash-list">
          {d.by_type.map((b) => (
            <li key={b.code}>
              <a href="#/batteries">
                <span>{b.name}</span>
                <strong>{num.format(b.balance)}</strong>
              </a>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Dismantling({ d }: { d: DismantlingData }) {
  return (
    <>
      <KpiRow>
        <Kpi
          label="Lots in queue"
          value={num.format(d.queue_lots)}
          href="/dismantling"
          hint={`${num.format(d.queue_qty)} pieces`}
        />
        <Kpi label="Parts recovered · 30 days" value={num.format(d.recovered_30d)} />
      </KpiRow>
      {d.recovered_by_type.length === 0 ? (
        <Empty>No parts recovered in the last 30 days.</Empty>
      ) : (
        <ul className="dash-list">
          {d.recovered_by_type.map((p) => (
            <li key={p.part_type}>
              <a href="#/inventory/spare-parts">
                <span>{p.label}</span>
                <strong>{num.format(p.qty)}</strong>
              </a>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function FunctionalStock({ d }: { d: FunctionalStockData }) {
  if (d.total_qty === 0) return <Empty>No functional stock.</Empty>;
  return (
    <>
      <KpiRow>
        <Kpi
          label="Functional pieces"
          value={num.format(d.total_qty)}
          href="/inventory/functional"
          hint={`${num.format(d.total_rows)} stock rows`}
        />
      </KpiRow>
      <ul className="dash-list">
        {d.by_condition.map((c) => (
          <li key={c.key}>
            <a href="#/inventory/functional">
              <span>{humanize(c.key)}</span>
              <strong>{num.format(c.qty)}</strong>
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

function NonFunctional({ d }: { d: NonFunctionalStockData }) {
  return (
    <KpiRow>
      <Kpi
        label="Non-functional pieces"
        value={num.format(d.non_functional_qty)}
        href="/inventory/non-functional"
        hint={`${num.format(d.non_functional_rows)} stock rows`}
      />
      {d.spare_parts_visible ? (
        <Kpi
          label="Spare parts"
          value={num.format(d.spare_parts_qty ?? 0)}
          href="/inventory/spare-parts"
          hint={`${num.format(d.spare_parts_rows ?? 0)} stock rows`}
        />
      ) : (
        <Kpi label="Spare parts" value="—" hint="Restricted to the spare-parts ledger roles" />
      )}
    </KpiRow>
  );
}

function Hazard({ d }: { d: HazardData }) {
  return (
    <KpiRow>
      <Kpi
        label="Pieces in quarantine"
        value={num.format(d.qty)}
        href="/inventory/holds"
        tone={d.qty > 0 ? 'danger' : 'success'}
        hint={`${num.format(d.rows)} stock rows`}
      />
    </KpiRow>
  );
}

function CnPipeline({ d }: { d: CnPipelineData }) {
  return (
    <KpiRow>
      <Kpi
        label="GS awaiting credit"
        value={num.format(d.awaiting_credit_gs)}
        href="/credit-notes"
        tone={d.awaiting_credit_gs > 0 ? 'warning' : undefined}
      />
      <Kpi label="Draft" value={num.format(d.draft)} href="/credit-notes" />
      <Kpi label="Verified" value={num.format(d.verified)} href="/credit-notes" />
      <Kpi label="Issued · 30 days" value={num.format(d.issued_30d)} href="/credit-notes" />
    </KpiRow>
  );
}

function CnIssued({ d }: { d: CnIssuedData }) {
  if (d.total_count === 0) {
    return <Empty>No credit notes issued in the last {d.months} months.</Empty>;
  }
  const months = Array.from(new Set(d.rows.map((r) => r.month))).sort();
  const data = months.map((m) => {
    const row: Record<string, string | number> = { x: fmtMonth(m) };
    for (const t of d.types) {
      row[t.code] = d.rows.find((r) => r.month === m && r.cn_type_code === t.code)?.value ?? 0;
    }
    return row;
  });
  return (
    <>
      <KpiRow>
        <Kpi label="Credit notes issued" value={num.format(d.total_count)} href="/credit-notes" />
        <Kpi label="Value (₹)" value={money.format(d.total_value)} />
      </KpiRow>
      <StackedBars
        label={`Issued credit note value by type, last ${String(d.months)} months`}
        xHeader="Month"
        data={data}
        format={(v) => money.format(v)}
        series={d.types.map((t, i) => ({
          key: t.code,
          name: t.label,
          color: CHART_COLORS[i] ?? 'var(--chart-1)',
        }))}
      />
    </>
  );
}

function GsTrend({ d }: { d: GsTrendData }) {
  const opened = d.rows.reduce((a, r) => a + r.opened, 0);
  const closed = d.rows.reduce((a, r) => a + r.closed, 0);
  return (
    <>
      <KpiRow>
        <Kpi label={`Opened · ${String(d.weeks)} weeks`} value={num.format(opened)} href="/gs" />
        <Kpi
          label={`Closed · ${String(d.weeks)} weeks`}
          value={num.format(closed)}
          href={hashPath('/gs', { status: 'CLOSED' })}
        />
      </KpiRow>
      <GroupedBars
        label={`Goods slips opened vs closed per week, last ${String(d.weeks)} weeks`}
        xHeader="Week of"
        data={d.rows.map((r) => ({ x: fmtDate(r.week_start), opened: r.opened, closed: r.closed }))}
        series={[
          { key: 'opened', name: 'Opened', color: 'var(--chart-1)' },
          { key: 'closed', name: 'Closed', color: 'var(--chart-2)' },
        ]}
      />
    </>
  );
}

function AccountsQueue({ d }: { d: AccountsQueueData }) {
  return (
    <KpiRow>
      <Kpi
        label="GS with unacknowledged documents"
        value={num.format(d.count)}
        href="/accounts"
        tone={d.count > 0 ? 'warning' : 'success'}
        hint={oldest(d.oldest_created_at)}
      />
    </KpiRow>
  );
}

function AdminHealth({ d }: { d: AdminHealthData }) {
  return (
    <>
      <KpiRow>
        <Kpi
          label="Active users"
          value={num.format(d.users_active)}
          hint={`${num.format(d.users_inactive)} inactive`}
        />
        <Kpi
          label={`Logins · ${String(d.window_days)} days`}
          value={num.format(d.logins)}
          hint={`${num.format(d.users_logged_in)} users`}
        />
        <Kpi
          label={`Config changes · ${String(d.window_days)} days`}
          value={num.format(d.config_changes)}
          href="/history"
        />
        <Kpi
          label="Guard violations attempted"
          value={num.format(d.guard_violations)}
          href="/guards"
          tone={d.guard_violations > 0 ? 'warning' : undefined}
        />
        <Kpi
          label={`Failed jobs · ${String(d.window_days)} days`}
          value={num.format(d.failed_jobs)}
          tone={d.failed_jobs > 0 ? 'danger' : 'success'}
          hint={
            d.last_failed_job
              ? `last: ${humanize(d.last_failed_job)}`
              : `${num.format(d.job_runs)} runs`
          }
        />
      </KpiRow>
      {d.guard_violations_by_code.length > 0 ? (
        <ul className="dash-list">
          {d.guard_violations_by_code.map((g) => (
            <li key={g.guard_code}>
              <a href="#/guards">
                <span>{g.guard_code}</span>
                <strong>{num.format(g.count)}</strong>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

/** A widget's data by code. Unknown codes render nothing (the API never sends them). */
export function WidgetBody({ code, data }: { code: string; data: unknown }): ReactNode {
  switch (code) {
    case 'MY_TASKS':
      return <MyTasks d={data as MyTasksData} />;
    case 'GS_PIPELINE':
      return <GsPipeline d={data as GsPipelineData} />;
    case 'GATE_INWARDS_TODAY':
      return <GateToday d={data as GateTodayData} />;
    case 'EVIDENCE_PENDING':
      return (
        <GsQueue
          d={data as GsQueueData}
          label="Awaiting unboxing evidence"
          href={WIDGET_LINKS.EVIDENCE_PENDING ?? '/gs'}
        />
      );
    case 'CSR_APPROVALS_PENDING':
      return <GsQueue d={data as GsQueueData} label="Awaiting CSR decision" href="/approvals" />;
    case 'INSPECTIONS_PENDING':
      return (
        <GsQueue
          d={data as GsQueueData}
          label="In inspection"
          href={WIDGET_LINKS.INSPECTIONS_PENDING ?? '/gs'}
        />
      );
    case 'CONTAINER_AUDIT':
      return <ContainerAudit d={data as ContainerAuditData} />;
    case 'OPEN_PENDENCIES':
      return <Pendencies d={data as PendencyData} />;
    case 'TRANSFERS_ATTENTION':
      return <Transfers d={data as TransfersData} />;
    case 'TECHNICIAN_WIP':
      return <TechnicianWip d={data as TechnicianWipData} />;
    case 'BATTERY_STOCK':
      return <Batteries d={data as BatteryData} />;
    case 'DISMANTLING':
      return <Dismantling d={data as DismantlingData} />;
    case 'FUNCTIONAL_STOCK':
      return <FunctionalStock d={data as FunctionalStockData} />;
    case 'NON_FUNCTIONAL_STOCK':
      return <NonFunctional d={data as NonFunctionalStockData} />;
    case 'HAZARD_QUARANTINE':
      return <Hazard d={data as HazardData} />;
    case 'CN_PIPELINE':
      return <CnPipeline d={data as CnPipelineData} />;
    case 'CN_ISSUED':
      return <CnIssued d={data as CnIssuedData} />;
    case 'GS_TREND':
      return <GsTrend d={data as GsTrendData} />;
    case 'ACCOUNTS_DOC_QUEUE':
      return <AccountsQueue d={data as AccountsQueueData} />;
    case 'ADMIN_HEALTH':
      return <AdminHealth d={data as AdminHealthData} />;
    default:
      return null;
  }
}
