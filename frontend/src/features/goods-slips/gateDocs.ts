// AMD-04 gate document row drafts (shared by the editor and the gate page).
import type { GateDocumentInput } from './api';

/** Accepted gate document files (mirrors the GATE_DOC allow-list: images and PDF). */
export const GATE_DOC_ACCEPT = 'image/jpeg,image/png,image/heic,image/heif,application/pdf';

export interface DocDraft {
  key: string;
  doc_type_code: string;
  doc_no: string;
  doc_date: string;
  remarks: string;
  files: File[];
}

export function newDocDraft(): DocDraft {
  return {
    key: crypto.randomUUID(),
    doc_type_code: '',
    doc_no: '',
    doc_date: '',
    remarks: '',
    files: [],
  };
}

export function toDocumentInputs(rows: DocDraft[]): GateDocumentInput[] {
  return rows.map((r) => ({
    doc_type_code: r.doc_type_code,
    doc_no: r.doc_no.trim() || null,
    doc_date: r.doc_date || null,
    remarks: r.remarks.trim() || null,
  }));
}

/** DEC-62: value of the party type select that stands for "No Documents From Party" (the GS-level
 * BR-03 flag, option code NO_DOCUMENT); never sent as a document row. */
export const NO_DOCUMENT_CHOICE = 'NO_DOCUMENT';

/** DEC-62: client checks before the summary sheet: every row needs a type and at least one file. */
export function checkDocRows(rows: DocDraft[]): Record<string, { type?: string; files?: string }> {
  const out: Record<string, { type?: string; files?: string }> = {};
  for (const row of rows) {
    const e: { type?: string; files?: string } = {};
    if (!row.doc_type_code) e.type = 'Choose the document type';
    if (row.files.length === 0) e.files = 'Attach a photo or PDF of the document';
    if (e.type ?? e.files) out[row.key] = e;
  }
  return out;
}
