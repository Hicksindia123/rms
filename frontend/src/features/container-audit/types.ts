export interface ContainerAuditLine {
  id: string | null;
  container_id: string;
  container_code: string;
  container_barcode: string;
  container_name: string | null;
  counted_qty: number;
  sellable_packaging_qty: number;
  remarks: string | null;
  yesterday_counted_qty: number | null;
  yesterday_sellable_packaging_qty: number | null;
}

export interface ContainerAuditDay {
  id: string;
  audit_date: string;
  status: 'PENDING' | 'CONFIRMED' | 'LATE' | 'MISSED';
  is_late: boolean;
  late_reason: string | null;
  confirmed: boolean;
  confirmed_by: string | null;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  remarks: string | null;
  created_at: string;
}

export interface TodayAuditData {
  day: ContainerAuditDay;
  containers: ContainerAuditLine[];
  checkbox_label: string;
  can_edit: boolean;
  can_confirm: boolean;
}

export interface CalendarDay {
  audit_date: string;
  status: 'PENDING' | 'CONFIRMED' | 'LATE' | 'MISSED';
  is_late: boolean;
  confirmed: boolean;
  confirmed_at: string | null;
  total_containers_counted: number;
  total_sellable_packaging_qty: number;
  remarks: string | null;
}

export interface CalendarSummary {
  from_date: string;
  to_date: string;
  days: CalendarDay[];
  today_status: string;
}
