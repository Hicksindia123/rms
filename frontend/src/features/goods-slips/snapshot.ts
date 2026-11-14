import type { ControlType, FormFieldSnapshot, FormSnapshot } from '@/features/config/forms/types';
import type { ValidationSpec } from '@/lib/rules';

import type { BackendFormSnapshot } from './api';

const CONTROL_TYPES: ReadonlySet<string> = new Set([
  'text',
  'textarea',
  'number',
  'date',
  'dropdown',
  'radio',
  'checkbox',
  'multiselect',
  'file',
  'master_ref',
]);

/**
 * Maps the published form snapshot stored by the backend (option_items / is_required /
 * version_no) to the shape DynamicForm renders. Labels, options and rules all come from it.
 * `extraValidation` adds DB-configured checks (e.g. the contact phone pattern setting).
 */
export function toDynamicFormSnapshot(
  snapshot: BackendFormSnapshot,
  extraValidation: Record<string, ValidationSpec> = {},
): FormSnapshot {
  const fields: FormFieldSnapshot[] = snapshot.fields.map((f): FormFieldSnapshot => {
    const control = (CONTROL_TYPES.has(f.control_type) ? f.control_type : 'text') as ControlType;
    const validation = {
      ...((f.validation ?? {}) as ValidationSpec),
      ...(extraValidation[f.field_key] ?? {}),
    };
    return {
      field_key: f.field_key,
      label: f.label,
      control_type: control,
      help_text: f.help_text ?? null,
      is_core: f.is_core ?? false,
      sort_order: f.sort_order,
      section: f.section ?? null,
      required: f.is_required,
      visible_when: f.visible_when ?? null,
      required_when: f.required_when ?? null,
      validation: Object.keys(validation).length > 0 ? validation : null,
      options: (f.option_items ?? [])
        .filter((o) => o.is_active !== false)
        .map((o) => ({
          code: o.code,
          label: o.label,
          sort_order: o.sort_order,
          allowed_status: o.allowed_status,
          rule_text: o.rule_text ?? null,
        })),
    };
  });

  // v1 forms only (single "Accompanying Document" field). Form v2 (AMD-04) carries files per
  // document row instead.
  const isV1 = fields.some((f) => f.field_key === 'accompanying_doc');
  if (isV1 && !fields.some((f) => f.field_key === 'gate_doc_image')) {
    const dateIdx = fields.findIndex((f) => f.field_key === 'gate_doc_date');
    const insertIdx = dateIdx >= 0 ? dateIdx + 1 : fields.length;
    fields.splice(insertIdx, 0, {
      field_key: 'gate_doc_image',
      label: 'Document Picture / Image',
      control_type: 'file',
      help_text: 'Take photo or upload image of the physical invoice or slip',
      is_core: false,
      sort_order: 145,
      section: 'Documentation',
      required: false,
      visible_when: {
        field: 'accompanying_doc',
        op: 'in',
        value: ['INVOICE', 'DEBIT_NOTE', 'DELIVERY_CHALLAN', 'HANDWRITTEN_SLIP'],
      },
      required_when: null,
      validation: null,
      options: [],
    });
  }

  return {
    form_code: snapshot.form_code,
    name: snapshot.name,
    version: snapshot.version_no,
    status: 'PUBLISHED',
    fields,
  };
}

/** Initial values from field defaults (e.g. GS Creation Format = AUTO_STANDARD, DD r10). */
export function defaultValues(snapshot: BackendFormSnapshot): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of snapshot.fields) {
    if (f.default_value !== null && f.default_value !== undefined)
      out[f.field_key] = f.default_value;
  }
  return out;
}

export function optionOf(snapshot: BackendFormSnapshot, fieldKey: string, code: unknown) {
  const field = snapshot.fields.find((f) => f.field_key === fieldKey);
  return field?.option_items?.find((o) => o.code === code);
}
