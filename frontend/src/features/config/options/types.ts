export type AllowedStatus = 'YES' | 'NO' | 'CONDITIONAL';

export type SystemBehavior = 'ALLOW' | 'HAZARD' | 'SCRAP' | 'RTV' | 'HOLD' | 'ESCALATE';

export interface OptionItem {
  id: string;
  option_set_id: string;
  code: string;
  label: string;
  sort_order: number;
  is_active: boolean;
  allowed_status: AllowedStatus;
  rule_text?: string | null | undefined;
  next_action_text?: string | null | undefined;
  remarks?: string | null | undefined;
  system_behavior: SystemBehavior;
  metadata?: Record<string, unknown> | undefined;
  created_at?: string | undefined;
  updated_at?: string | undefined;
}

export interface OptionSet {
  id: string;
  code: string;
  name: string;
  description?: string | null | undefined;
  scope?: string | null | undefined;
  is_active: boolean;
  items_count?: number | undefined;
  items?: OptionItem[] | undefined;
}
