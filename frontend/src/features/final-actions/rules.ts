import type { Allocations, FinalActionGroup, FinalActionLine, SaveFinalActionsIn } from './types';

/**
 * Pure helpers of the Final Actions screen (change plan Phase 7; AMD-16; G-21; gap plan G4,
 * DEC-57: allocations per item + current condition). The server and the DB enforce G-21; these
 * only give the RM immediate feedback.
 */

/** Allocation key of a group: the item id alone for an item without a condition split. */
export function groupKey(itemId: string, conditionFieldId: string | null): string {
  return conditionFieldId ? `${itemId}::${conditionFieldId}` : itemId;
}

/** The groups of a line; older payloads without groups are one group for the whole line. */
export function groupsOf(line: FinalActionLine): FinalActionGroup[] {
  if (line.groups && line.groups.length > 0) return line.groups;
  return [
    {
      condition_field_id: null,
      condition_code: null,
      condition_label: null,
      current_qty: line.counted_qty,
      at_departments_qty: line.at_departments_qty,
      available_qty: line.available_qty,
      actioned_qty: line.actioned_qty,
      is_balanced: line.is_balanced,
      current_actions: line.current_actions,
    },
  ];
}

/** Allocations as currently saved (0 for every allowed action without a saved qty). */
export function initialAllocations(lines: FinalActionLine[]): Allocations {
  const out: Allocations = {};
  for (const line of lines) {
    for (const g of groupsOf(line)) {
      const row: Record<string, number> = {};
      for (const a of line.allowed_actions) row[a.code] = 0;
      for (const a of g.current_actions) row[a.action_code] = a.qty;
      out[groupKey(line.gs_item_id, g.condition_field_id)] = row;
    }
  }
  return out;
}

export function lineTotal(row: Record<string, number> | undefined): number {
  if (!row) return 0;
  return Object.values(row).reduce((sum, q) => sum + (Number.isFinite(q) ? q : 0), 0);
}

/** G-21 feedback for one group: null when Σ action qty = the qty it must allocate. */
export function groupIssue(
  available: number,
  row: Record<string, number> | undefined,
): string | null {
  const total = lineTotal(row);
  if (total === available) return null;
  if (total < available) return `${String(available - total)} pc(s) still to allocate`;
  return `${String(total - available)} pc(s) over the available qty`;
}

/** G-21 feedback for a line without a condition split (one group). */
export function lineIssue(
  line: FinalActionLine,
  row: Record<string, number> | undefined,
): string | null {
  return groupIssue(line.available_qty, row);
}

export function allBalanced(lines: FinalActionLine[], allocs: Allocations): boolean {
  return lines.every((l) =>
    groupsOf(l).every(
      (g) =>
        groupIssue(g.available_qty, allocs[groupKey(l.gs_item_id, g.condition_field_id)]) === null,
    ),
  );
}

/** True when the edited split differs from the saved one (zero rows ignored). */
export function isDirty(lines: FinalActionLine[], allocs: Allocations): boolean {
  const saved = initialAllocations(lines);
  return Object.keys(saved).some((key) => {
    const a = allocs[key] ?? {};
    const b = saved[key] ?? {};
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
    lines: lines.flatMap((l) =>
      groupsOf(l).map((g) => ({
        gs_item_id: l.gs_item_id,
        ...(g.condition_field_id ? { condition_field_id: g.condition_field_id } : {}),
        actions: Object.entries(allocs[groupKey(l.gs_item_id, g.condition_field_id)] ?? {})
          .filter(([, qty]) => qty > 0)
          .map(([action_code, qty]) => ({ action_code, qty })),
      })),
    ),
    reason: reason && reason.trim() ? reason.trim() : null,
  };
}
