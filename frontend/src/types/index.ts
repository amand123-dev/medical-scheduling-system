export type StaffRole = "admin" | "provider" | "front_desk";
export type AppointmentStatus = "scheduled" | "completed" | "cancelled" | "no_show";
export type WaitlistStatus = "waiting" | "offered" | "booked" | "declined" | "expired";
export type RiskBucket = "low" | "medium" | "high" | "insufficient_data";

export interface Provider {
  id: string;
  name: string;
  specialty: string | null;
  is_active: boolean;
  work_days: string | null;
  work_start_hour: number | null;
  work_end_hour: number | null;
}

export interface VisitType {
  id: string;
  name: string;
  duration_minutes: number;
  is_new_patient: boolean;
}

export interface Appointment {
  id: string;
  provider_id: string;
  patient_uuid: string;
  visit_type_id: string;
  start_time: string;
  end_time: string;
  status: AppointmentStatus;
  no_show_risk: number | null;
  created_at: string;
}

export interface WaitlistEntry {
  id: string;
  patient_uuid: string;
  provider_id: string;
  visit_type_id: string;
  priority: number;
  requested_at: string;
  earliest_window: string | null;
  latest_window: string | null;
  status: WaitlistStatus;
  decline_count: number;
  offered_at: string | null;
  offered_slot_start: string | null;
  offered_slot_end: string | null;
}

export type ReminderChannel = "sms" | "email" | "call";
export type ReminderMessageType = "standard" | "followup" | "call_requested";

export interface ReminderLog {
  id: string;
  appointment_id: string;
  sent_at: string;
  channel: ReminderChannel;
  message_type: ReminderMessageType;
}

export interface RiskScore {
  patient_uuid: string;
  score: number | null;
  bucket: RiskBucket;
  based_on: number;
}

export interface DashboardMetrics {
  fill_rate: number;
  no_show_rate: number;
  slots_recovered: number;
  days: number;
}

export interface PracticeSettings {
  matcher_w1: number;
  matcher_w2: number;
  matcher_w3: number;
  hold_window_minutes: number;
  risk_low_threshold: number;
  risk_high_threshold: number;
  work_start_hour: number;
  work_end_hour: number;
  buffer_minutes: number;
}

export interface ScheduleBlock {
  id: string;
  provider_id: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;
  created_at: string;
}

export interface NextAvailable {
  provider_id: string;
  visit_type_id: string;
  start_time: string;
  end_time: string;
}

export interface OutreachEvent {
  id: string;
  at: string;
  patient_uuid: string;
  event_type: string;
  message_preview: string;
  status: string;
  slot_time: string | null;
  provider_name: string | null;
  visit_type_name: string | null;
}

export interface PatientIdentityResponse {
  patient_uuid: string;
  first_name: string;
  last_name: string;
  dob: string;
  phone: string;
  email: string;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  patient_uuid: string;
  accessed_by: string;
  accessed_by_username: string | null;
  action: string;
  at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface MLRiskScore {
  patient_uuid: string;
  probability: number;
  bucket: string;
  note: string;
  features_used: Record<string, number>;
  wait_days: number;
}
