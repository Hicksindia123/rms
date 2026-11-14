import type { Allocations, FinalActionLine, SaveFinalActionsIn } from './types';

/**
 * Pure helpers of the Final Actions screen (change plan Phase 7; AMD-16; G-21).
 * The server and the DB enforce G-21; these only give the RM immediate feedback.
 */

/** Allocations as currently saved (0 for every allowed action without a saved qty). */
export function initialAllocations(lines: FinalActionLine[]): Allocations {
  const out: Allocations = {};
  for (const line of lines) {
    const row: Record<string, number> = {};
    for (const a of line.allowed_actions) row[a.code] = 0;
    for (const a of line.current_actions) row[a.action_code] = a.qty;
    out[line.gs_item_id] = row;
  }
  return out;
}

export function lineTotal(row: Record<string, number> | undefined): number {
  if (!row) return 0;
  return Object.values(row).reduce((sum, q) => sum + (Number.isFinite(q) ? q : 0), 0);
}

/** G-21 feedback for one line: null when Σ action qty = qty available for action. */
export function lineIssue(
  line: FinalActionLine,
  row: Record<string, number> | undefined,
): string | null {
  const total = lineTotal(row);
  if (total === line.available_qty) return null;
  if (total < line.available_qty) {
    return `${String(line.available_qty - total)} pc(s) still to allocate`;
  }
  return `${String(total - line.available_qty)} pc(s) over the available qty`;
}

export function allBalanced(lines: FinalActionLine[], allocs: Allocations): boolean {
  return lines.every((l) => lineIssue(l, allocs[l.gs_item_id]) === null);
}

/** True when the edited split differs from the saved one (zero rows ignored). */
export function isDirty(lines: FinalActionLine[], allocs: Allocations): boolean {
  const saved = initialAllocations(lines);
  return lines.some((l) => {
    const a = allocs[l.gs_item_id] ?? {};
    const b = saved[l.gs_item_id] ?? {};
    const codes = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const c of codes) if ((a[c] ?? 0) !== (b[c] ?? 0)) return true;
    return false;
  });
}

/** Parse a qty input: whole numbers ≥ 0 only (anything else → 0). */
export function parseQty(raw: string): number {
  if (!/^\d{1,7}$/.test(raw.trim())) return 0;
  return Number.parseInt(raw.trim(), 10);
}

export function toSavePayload(
  lines: FinalActionLine[],
  allocs: Allocations,
  reason: string | null,
): SaveFinalActionsIn {
  return {
    lines: lines.map((l) => ({
      gs_item_id: l.gs_item_id,
      actions: Object.entries(allocs[l.gs_item_id] ?? {})
        .filter(([, qty]) => qty > 0)
        .map(([action_code, qty]) => ({ action_code, qty })),
    })),
    reason: reason && reason.trim() ? reason.trim() : null,
  };
}
