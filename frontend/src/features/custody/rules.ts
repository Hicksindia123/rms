/** Pure helpers of the custody screens (no React; unit-tested in tests/unit/custody.test.ts). */

export function lineTitle(line: { line_no: number | null; product_name: string | null }): string {
  const no = line.line_no !== null ? `#${String(line.line_no)} ` : '';
  return `${no}${line.product_name ?? 'Item'}`;
}

/** Count outcome for the receive screen: any line that differs is a discrepancy (DD r46). */
export function countMismatches(
  lines: Array<{ lot_id: string; qty_sent: number | null }>,
  counts: Record<string, number>,
): string[] {
  return lines
    .filter((l) => l.qty_sent !== null && (counts[l.lot_id] ?? 0) !== l.qty_sent)
    .map((l) => l.lot_id);
}

interface Section {
  id: string;
  title: string;
  fields: string[];
}

/** Sections of the published TRANSFER_NOTE layout (a nested array is flattened). */
export function noteSections(layout: Record<string, unknown>): Section[] {
  const raw = Array.isArray(layout.sections) ? (layout.sections as unknown[]) : [];
  return raw
    .flat()
    .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
    .map((s) => ({
      id: typeof s.id === 'string' ? s.id : '',
      title: typeof s.title === 'string' ? s.title : '',
      fields: Array.isArray(s.fields)
        ? s.fields.filter((f): f is string => typeof f === 'string')
        : [],
    }));
}

/** A template layout value as text (non-strings render as nothing). */
export function layoutText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
