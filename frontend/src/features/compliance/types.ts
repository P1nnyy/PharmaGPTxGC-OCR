// Shapes returned by /compliance/*.

export type Urgency =
  | 'DONE' | 'INFORMATIONAL' | 'TIME_BARRED' | 'OVERDUE' | 'URGENT' | 'SOON' | 'SCHEDULED';

export type StageState = 'DONE' | 'CURRENT' | 'BLOCKED' | 'PENDING' | 'NOT_APPLICABLE';

export interface ScheduleItem {
  kind: 'GSTR1' | 'GSTR3B' | 'PMT06' | 'GSTR2B' | 'IFF';
  label: string;
  period: string;
  covers_months: string[];
  due_date: string;
  days_remaining: number;
  is_filing: boolean;
  is_optional: boolean;
  note: string;
  is_done: boolean;
  done_at: string | null;
  arn: string | null;
  urgency: Urgency;
  blocking_count: number;
  current_stage: string | null;
  link: string | null;
  barred_on: string | null;
  days_until_barred: number | null;
  is_time_barred: boolean;
  bar_is_near: boolean;
  reason?: 'TIME_BAR' | 'OVERDUE' | 'NEXT_DUE';
  headline?: string;
}

export interface NextAction {
  as_of: string;
  filing_frequency: string | null;
  next_action: ScheduleItem | null;
  time_bar: { already_barred_count: number; closing_soon_count: number; has_anything: boolean };
  note: string | null;
}

export interface CalendarReport {
  as_of: string;
  financial_year: number;
  label: string;
  filing_frequency: string | null;
  effective_filing_frequency: string;
  state_code: string | null;
  frequency_is_set: boolean;
  items: ScheduleItem[];
  next_action: ScheduleItem | null;
  open_years: number[];
}

export interface ValidationRef {
  id: string; code: string; message: string;
  record_type: string; record_id: string | null;
}

export interface Stage {
  id: string;
  label: string;
  state: StageState;
  detail: string;
  link: string | null;
  blocking: ValidationRef[];
  warnings: ValidationRef[];
  blocking_count: number;
  completed_at: string | null;
  evidence: {
    id: string; arn: string; filed_at: string;
    filed_by: string | null; has_payload: boolean;
  } | null;
}

export interface TimelineReport {
  period: string;
  period_label: string;
  covers_months: string[];
  filing_frequency: string;
  stages: Stage[];
  current_stage: string | null;
  is_nil_return: boolean;
  obligations: Array<{
    kind: string; label: string; due_date: string; days_remaining: number;
    is_filing: boolean; is_optional: boolean; note: string; barred_on: string | null;
  }>;
}

export interface TimeBarReport {
  as_of: string;
  rule: string;
  already_barred: ScheduleItem[];
  closing_soon: ScheduleItem[];
  already_barred_count: number;
  closing_soon_count: number;
  has_anything: boolean;
}

export interface FilingRow {
  id: string; period: string; return_type: string; arn: string;
  filed_at: string; filed_by: string | null; covers_months: string[];
  note: string | null; recorded_at: string; superseded_by: string | null;
  has_payload: boolean;
}

export interface ReminderSettings {
  enabled: boolean; days_before: number[]; channel: string; is_default: boolean;
}

export interface RemindersReport {
  as_of: string;
  settings: ReminderSettings;
  due: Array<{
    key: string; kind: string; period: string; label: string; due_date: string;
    days_remaining: number; tone: string; message: string; link: string | null;
  }>;
  preview: Array<{ key: string; message: string; tone: string; would_fire_on: string }> | null;
  note: string | null;
}
