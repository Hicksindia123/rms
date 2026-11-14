import { age, humanize } from '@/features/goods-slips/format';

export interface TaskItem {
  id: string;
  gs_id: string;
  step_code: string;
  step_label: string | null;
  assigned_role_name: string | null;
  due_at: string | null;
  created_at: string;
  gs_no: string;
  gs_status: string;
  box_count: number;
  /** AMD-03: number of cartons (box_count is the deprecated mirror). */
  carton_count: number;
  missing_documentation: boolean;
  party_name: string | null;
  station_name: string | null;
}

export interface TaskPage {
  items: TaskItem[];
  total: number;
}

export const PAGE_SIZE = 100;
const DUE_SOON_MS = 4 * 60 * 60 * 1000;

/**
 * The screen that performs a step (UI navigation, not business values). Steps without a dedicated
 * screen open the goods slip, whose detail page offers the next action.
 */
export function stepScreen(stepCode: string, gsId: string): string {
  switch (stepCode) {
    case 'S1_UNBOX':
      return `/gs/${gsId}/unboxing`;
    case 'S1_ITEMIZE':
      return `/gs/${gsId}/itemization`;
    case 'S1_CSR_APPROVAL':
      return '/approvals';
    case 'S1_INSPECT':
      return `/gs/${gsId}/inspection`;
    case 'S1A_RM_ACTION':
      return `/gs/${gsId}/rm-actions`;
    case 'S2_HANDOVER':
      return `/gs/${gsId}/handover`;
    case 'S6_CN_DECISION':
      return `/gs/${gsId}/cn-decision`;
    case 'S6_ACCOUNTS_CN':
      return '/credit-notes';
    case 'S6_NOTIFY':
      return `/gs/${gsId}/party-notification`;
    default:
      return `/gs/${gsId}`;
  }
}

export type Urgency = 'overdue' | 'due-soon' | 'normal';

export function urgency(t: TaskItem, now: number): Urgency {
  if (!t.due_at) return 'normal';
  const due = new Date(t.due_at).getTime();
  if (due < now) return 'overdue';
  return due - now < DUE_SOON_MS ? 'due-soon' : 'normal';
}

/** Overdue first, then the earliest due, then the oldest task. */
export function compareTasks(a: TaskItem, b: TaskItem): number {
  const ad = a.due_at ? new Date(a.due_at).getTime() : Number.POSITIVE_INFINITY;
  const bd = b.due_at ? new Date(b.due_at).getTime() : Number.POSITIVE_INFINITY;
  if (ad !== bd) return ad - bd;
  return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
}

export interface Group {
  code: string;
  label: string;
  tasks: TaskItem[];
  overdue: number;
}

export function groupTasks(tasks: TaskItem[], now: number): Group[] {
  const map = new Map<string, Group>();
  for (const t of tasks) {
    const g = map.get(t.step_code) ?? {
      code: t.step_code,
      label: t.step_label ?? humanize(t.step_code),
      tasks: [],
      overdue: 0,
    };
    g.tasks.push(t);
    if (urgency(t, now) === 'overdue') g.overdue += 1;
    map.set(t.step_code, g);
  }
  const groups = Array.from(map.values());
  for (const g of groups) g.tasks.sort(compareTasks);
  return groups.sort((a, b) => {
    if (a.overdue !== b.overdue) return b.overdue - a.overdue;
    const first = a.tasks[0] && b.tasks[0] ? compareTasks(a.tasks[0], b.tasks[0]) : 0;
    return first !== 0 ? first : a.label.localeCompare(b.label);
  });
}

export function dueText(t: TaskItem, u: Urgency, now: number): string | null {
  if (!t.due_at) return null;
  if (u === 'overdue') return `Overdue by ${age(t.due_at, now)}`;
  const mins = Math.max(0, Math.round((new Date(t.due_at).getTime() - now) / 60000));
  if (mins < 60) return `Due in ${String(mins)}m`;
  const hours = Math.round(mins / 60);
  return hours < 48 ? `Due in ${String(hours)}h` : `Due in ${String(Math.round(hours / 24))}d`;
}
