import type {
  AcEntryLine,
  AcEntryLineIn,
  AcGsEntry,
  DispatchIn,
  Drafts,
  LineDraft,
  SaveGsEntryIn,
} from './types';

/**
 * Pure helpers of the Accounts entry / Dispatch screens (change plan Phase 8; AMD-18; DEC-26).
 * The server and the DB enforce G-22; these only give Accounts immediate feedback. Which fields a
 * line takes comes from its flags (requires_cn / requires_challan), never from action codes.
 */

export function toDraft(line: AcEntryLine): LineDraft {
  return {
    cn_no: line.cn_no ?? '',
    cn_date: line.cn_date ?? '',
    cn_value: line.cn_value ?? '',
    challan_no: line.challan_no ?? '',
    challan_date: line.challan_date ?? '',
  };
}

export function initialDrafts(lines: AcEntryLine[]): Drafts {
  return Object.fromEntries(lines.map((l) => [l.id, toDraft(l)]));
}

const same = (a: LineDraft, b: LineDraft) =>
  a.cn_no.trim() === b.cn_no.trim() &&
  a.cn_date === b.cn_date &&
  normaliseAmount(a.cn_value) === normaliseAmount(b.cn_value) &&
  a.challan_no.trim() === b.challan_no.trim() &&
  a.challan_date === b.challan_date;

function normaliseAmount(raw: string): string {
  const v = raw.trim();
  if (v === '') return '';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : v;
}

export function changedLines(lines: AcEntryLine[], drafts: Drafts): AcEntryLine[] {
  return lines.filter((l) => {
    const d = drafts[l.id];
    return d !== undefined && !same(d, toDraft(l));
  });
}

export function isDirty(lines: AcEntryLine[], drafts: Drafts): boolean {
  return changedLines(lines, drafts).length > 0;
}

/** Problems in one line's draft (empty = fine). Mirrors the server checks for quick feedback. */
export function draftIssues(line: AcEntryLine, d: LineDraft, today: string): string[] {
  const issues: string[] = [];
  if (line.requires_cn) {
    const parts = [d.cn_no.trim(), d.cn_date, d.cn_value.trim()];
    if (parts.some(Boolean) && !parts.every(Boolean)) {
      issues.push('CN No., CN Date and CN Value are entered together.');
    }
    if (d.cn_value.trim() !== '') {
      const n = Number(d.cn_value);
      if (!Number.isFinite(n) || n <= 0) issues.push('CN Value must be a positive amount.');
      else if (!/^\d+(\.\d{1,2})?$/.test(d.cn_value.trim())) {
        issues.push('CN Value takes at most 2 decimals.');
      }
    }
    if (d.cn_date && d.cn_date > today) issues.push('CN Date cannot be in the future.');
  }
  if (line.requires_challan) {
    const parts = [d.challan_no.trim(), d.challan_date];
    if (parts.some(Boolean) && !parts.every(Boolean)) {
      issues.push('Challan No. and Challan Date are entered together.');
    }
    if (d.challan_date && d.challan_date > today) {
      issues.push('Challan Date cannot be in the future.');
    }
  }
  return issues;
}

export function draftComplete(line: AcEntryLine, d: LineDraft): boolean {
  const cnOk = !line.requires_cn || (d.cn_no.trim() && d.cn_date && d.cn_value.trim());
  const chOk = !line.requires_challan || (d.challan_no.trim() && d.challan_date);
  return Boolean(cnOk && chOk);
}

/** Only changed lines, and only the field groups the line's flags allow. */
export function toSaveLines(lines: AcEntryLine[], drafts: Drafts): AcEntryLineIn[] {
  return changedLines(lines, drafts).map((l) => {
    const d = drafts[l.id] ?? toDraft(l);
    const v = (s: string) => (s.trim() === '' ? null : s.trim());
    return {
      line_id: l.id,
      cn_no: l.requires_cn ? v(d.cn_no) : null,
      cn_date: l.requires_cn ? v(d.cn_date) : null,
      cn_value: l.requires_cn ? v(d.cn_value) : null,
      challan_no: l.requires_challan ? v(d.challan_no) : null,
      challan_date: l.requires_challan ? v(d.challan_date) : null,
    };
  });
}

/** Local calendar date YYYY-MM-DD (the date inputs work in the user's local day). */
export function localToday(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${String(now.getFullYear())}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/** DEC-26 tracking data check for the dispatch form (null = OK). */
export function dispatchIssue(form: DispatchIn, today: string): string | null {
  if (!form.dispatch_date) return 'Enter the dispatch date.';
  if (form.dispatch_date > today) return 'The dispatch date cannot be in the future.';
  if (!form.transporter.trim()) return 'Enter the transporter / courier.';
  if (!form.docket_no?.trim() && !form.vehicle_no?.trim()) {
    return 'Enter a docket number or a vehicle number.';
  }
  return null;
}

// --- DEC-71 (P11): one Challan / Credit Note per goods slip ---------------------------------

/** Editable values of the goods slip's entry (form strings; '' = empty). */
export interface GsEntryDraft {
  challan_no: string;
  challan_date: string;
  cn_no: string;
  cn_date: string;
  cn_value: string;
}

export function toGsDraft(e: AcGsEntry): GsEntryDraft {
  return {
    challan_no: e.challan_no ?? '',
    challan_date: e.challan_date ?? '',
    cn_no: e.cn_no ?? '',
    cn_date: e.cn_date ?? '',
    cn_value: e.cn_value ?? '',
  };
}

export function gsDraftDirty(e: AcGsEntry, d: GsEntryDraft): boolean {
  const b = toGsDraft(e);
  return (
    b.challan_no.trim() !== d.challan_no.trim() ||
    b.challan_date !== d.challan_date ||
    b.cn_no.trim() !== d.cn_no.trim() ||
    b.cn_date !== d.cn_date ||
    normaliseAmount(b.cn_value) !== normaliseAmount(d.cn_value)
  );
}

/** Problems in the goods slip's draft (empty = fine); only the groups the goods slip needs. */
export function gsDraftIssues(e: AcGsEntry, d: GsEntryDraft, today: string): string[] {
  const issues: string[] = [];
  if (e.requires_challan) {
    const parts = [d.challan_no.trim(), d.challan_date];
    if (parts.some(Boolean) && !parts.every(Boolean)) {
      issues.push('Challan No. and Challan Date are entered together.');
    }
    if (d.challan_date && d.challan_date > today)
      issues.push('Challan Date cannot be in the future.');
  }
  if (e.requires_cn) {
    const parts = [d.cn_no.trim(), d.cn_date, d.cn_value.trim()];
    if (parts.some(Boolean) && !parts.every(Boolean)) {
      issues.push('CN No., CN Date and CN Value are entered together.');
    }
    if (d.cn_value.trim() !== '') {
      const n = Number(d.cn_value);
      if (!Number.isFinite(n) || n <= 0) issues.push('CN Value must be a positive amount.');
      else if (!/^\d+(\.\d{1,2})?$/.test(d.cn_value.trim())) {
        issues.push('CN Value takes at most 2 decimals.');
      }
    }
    if (d.cn_date && d.cn_date > today) issues.push('CN Date cannot be in the future.');
  }
  return issues;
}

export function gsDraftComplete(e: AcGsEntry, d: GsEntryDraft): boolean {
  const ch = !e.requires_challan || (d.challan_no.trim() && d.challan_date);
  const cn = !e.requires_cn || (d.cn_no.trim() && d.cn_date && d.cn_value.trim());
  return Boolean(ch && cn);
}

/** The save body: a group the goods slip does not need is never sent (DEC-71). */
export function toGsEntryBody(
  e: AcGsEntry,
  d: GsEntryDraft,
): Omit<SaveGsEntryIn, 'ac_action_slip_id'> {
  const v = (s: string) => (s.trim() === '' ? null : s.trim());
  return {
    ...(e.requires_challan ? { challan_no: v(d.challan_no), challan_date: v(d.challan_date) } : {}),
    ...(e.requires_cn ? { cn_no: v(d.cn_no), cn_date: v(d.cn_date), cn_value: v(d.cn_value) } : {}),
  };
}
