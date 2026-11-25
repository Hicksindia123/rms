/** DEC-75: pieces picked for Management approval (helpers shared by the analysis screens). */
import type { ManagementLineIn } from './types';

export interface PickRow {
  key: string;
  gs_item_id: string;
  condition_field_id: string | null;
  line_no: number;
  product_name: string;
  condition_label?: string | null | undefined;
  from_code: string;
  from_label: string;
  /** Pieces of this decision that may still be sent. */
  max: number;
}

export interface Pick {
  qty: number;
  proposal: string | null;
}

export type Picks = Record<string, Pick>;

export function picksToLines(rows: PickRow[], picks: Picks): ManagementLineIn[] {
  return rows.flatMap((r) => {
    const p = picks[r.key];
    if (!p || p.qty <= 0 || !p.proposal) return [];
    return [
      {
        gs_item_id: r.gs_item_id,
        condition_field_id: r.condition_field_id,
        from_action_code: r.from_code,
        proposed_action_code: p.proposal,
        qty: Math.min(p.qty, r.max),
      },
    ];
  });
}

/** "X items · Y pcs" of the picked pieces, and how many picks still lack a proposal. */
export function pickSummary(rows: PickRow[], picks: Picks) {
  let pcs = 0;
  let missing = 0;
  const items = new Set<string>();
  for (const r of rows) {
    const p = picks[r.key];
    if (!p || p.qty <= 0) continue;
    if (!p.proposal) {
      missing += 1;
      continue;
    }
    pcs += Math.min(p.qty, r.max);
    items.add(r.gs_item_id);
  }
  return { items: items.size, pcs, missing };
}
