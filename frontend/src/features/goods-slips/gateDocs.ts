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
