import type { RuleCondition, ValidationSpec } from '@/lib/rules';

export type ControlType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'date'
  | 'dropdown'
  | 'radio'
  | 'checkbox'
  | 'multiselect'
  | 'file'
  | 'master_ref';

export interface FormOptionSnapshot {
  code: string;
  label: string;
  sort_order: number;
  allowed_status?: 'YES' | 'NO' | 'CONDITIONAL' | undefined;
  rule_text?: string | null | undefined;
  is_active?: boolean | undefined;
}

export interface FormFieldSnapshot {
  id?: string | undefined;
  field_key: string;
  label: string;
  control_type: ControlType;
  help_text?: string | null | undefined;
  is_core?: boolean | undefined;
  is_active?: boolean | undefined;
  sort_order: number;
  section?: string | null | undefined;
  required?: boolean | undefined;
  visible_when?: RuleCondition | null | undefined;
  required_when?: RuleCondition | null | undefined;
  validation?: ValidationSpec | null | undefined;
  option_set_code?: string | null | undefined;
  options?: FormOptionSnapshot[] | null | undefined;
}

export interface FormSnapshot {
  form_code: string;
  name: string;
  version: number;
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED';
  published_at?: string | null | undefined;
  change_notes?: string | null | undefined;
  fields: FormFieldSnapshot[];
}

export interface FormVersionSummary {
  id: string;
  form_id: string;
  version: number;
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED';
  change_notes?: string | null | undefined;
  published_at?: string | null | undefined;
  created_at: string;
}

export interface FormDefinitionSummary {
  id: string;
  code: string;
  name: string;
  description?: string | null | undefined;
  category?: string | null | undefined;
  is_active: boolean;
  latest_version?: number | undefined;
  has_published: boolean;
}

export interface VersionDiffResult {
  v1: number;
  v2: number;
  added_fields: FormFieldSnapshot[];
  removed_fields: FormFieldSnapshot[];
  modified_fields: Array<{
    field_key: string;
    before: Partial<FormFieldSnapshot>;
    after: Partial<FormFieldSnapshot>;
  }>;
}
