import type { Appointment, NextAvailable, Provider, VisitType, WaitlistEntry } from "../types";
import client from "./client";

export interface PatientMe {
  patient_uuid: string;
  email: string;
  first_name: string;
  last_name: string;
  dob: string;
  phone: string;
}

export const patientRegister = (body: {
  first_name: string;
  last_name: string;
  dob: string;
  phone: string;
  email: string;
  password: string;
}) => client.post<{ access_token: string }>("/auth/patient/register", body).then((r) => r.data);

export const patientLogin = (email: string, password: string) =>
  client
    .post<{ access_token: string }>("/auth/patient/login", { email, password })
    .then((r) => r.data);

export const fetchPatientMe = () =>
  client.get<PatientMe>("/patient/me").then((r) => r.data);

export const fetchMyAppointments = () =>
  client.get<Appointment[]>("/patient/appointments").then((r) => r.data);

export const bookMyAppointment = (body: {
  provider_id: string;
  patient_uuid: string;
  visit_type_id: string;
  start_time: string;
}) => client.post<Appointment>("/patient/appointments", body).then((r) => r.data);

export const cancelMyAppointment = (id: string) =>
  client.patch<Appointment>(`/patient/appointments/${id}/cancel`).then((r) => r.data);

export const fetchMyWaitlist = () =>
  client.get<WaitlistEntry[]>("/patient/waitlist").then((r) => r.data);

export const acceptMyOffer = (entryId: string) =>
  client.patch<Appointment>(`/patient/waitlist/${entryId}/accept`).then((r) => r.data);

export const declineMyOffer = (entryId: string) =>
  client.patch<{ status: string }>(`/patient/waitlist/${entryId}/decline`).then((r) => r.data);

export const confirmWaitlistToken = (token: string) =>
  client
    .get<{ status: string; message: string }>(`/waitlist-confirm/${token}/accept`)
    .then((r) => r.data);

export const declineWaitlistToken = (token: string) =>
  client
    .get<{ status: string; message: string }>(`/waitlist-confirm/${token}/decline`)
    .then((r) => r.data);

// Reuse existing public endpoints
export const fetchProvidersPublic = () =>
  client.get<Provider[]>("/providers").then((r) => r.data);

export const fetchVisitTypesPublic = () =>
  client.get<VisitType[]>("/visit-types").then((r) => r.data);

export const findNextAvailablePublic = (
  providerId: string,
  visitTypeId: string,
  after?: string
) =>
  client
    .get<NextAvailable>("/appointments/next-available", {
      params: {
        provider_id: providerId,
        visit_type_id: visitTypeId,
        after,
        tz_offset: new Date().getTimezoneOffset(),
      },
    })
    .then((r) => r.data);
