import type { Appointment, DashboardMetrics, MLRiskScore, NextAvailable, Provider, ReminderLog, RiskScore, ScheduleBlock, VisitType } from "../types";
import client from "./client";

export const fetchProviders = () =>
  client.get<Provider[]>("/providers").then((r) => r.data);

export const fetchVisitTypes = () =>
  client.get<VisitType[]>("/visit-types").then((r) => r.data);

export const fetchAppointments = (providerId?: string, date?: string) =>
  client
    .get<Appointment[]>("/appointments", {
      params: { provider_id: providerId, date },
    })
    .then((r) => r.data);

export const createAppointment = (body: {
  provider_id: string;
  patient_uuid: string;
  visit_type_id: string;
  start_time: string;
}) => client.post<Appointment>("/appointments", body).then((r) => r.data);

export const cancelAppointment = (id: string) =>
  client.patch<Appointment>(`/appointments/${id}/cancel`).then((r) => r.data);

export const completeAppointment = (id: string) =>
  client.patch<Appointment>(`/appointments/${id}/complete`).then((r) => r.data);

export const noShowAppointment = (id: string) =>
  client.patch<Appointment>(`/appointments/${id}/no-show`).then((r) => r.data);

export const fetchRisk = (patientUuid: string) =>
  client.get<RiskScore>(`/scorer/risk/${patientUuid}`).then((r) => r.data);

export const fetchMLRisk = (patientUuid: string) =>
  client.get<MLRiskScore>(`/scorer/ml-risk/${patientUuid}`).then((r) => r.data);

export const fetchReminders = (apptId: string) =>
  client.get<ReminderLog[]>(`/appointments/${apptId}/reminders`).then((r) => r.data);

export const fetchDashboardMetrics = (days = 30) =>
  client.get<DashboardMetrics>("/dashboard/metrics", { params: { days } }).then((r) => r.data);

export const fetchBlocks = (providerId?: string) =>
  client.get<ScheduleBlock[]>("/schedule-blocks", { params: { provider_id: providerId } }).then((r) => r.data);

export const createBlock = (body: { provider_id?: string | null; start_date: string; end_date: string; reason?: string | null }) =>
  client.post<ScheduleBlock>("/schedule-blocks", body).then((r) => r.data);

export const deleteBlock = (id: string) => client.delete(`/schedule-blocks/${id}`);

export const findNextAvailable = (providerId: string, visitTypeId: string, after?: string) =>
  client
    .get<NextAvailable>("/appointments/next-available", {
      params: { provider_id: providerId, visit_type_id: visitTypeId, after },
    })
    .then((r) => r.data);
