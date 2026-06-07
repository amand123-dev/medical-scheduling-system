import type { WaitlistEntry } from "../types";
import client from "./client";

export const fetchWaitlist = (providerId?: string, status?: string) =>
  client
    .get<WaitlistEntry[]>("/waitlist", { params: { provider_id: providerId, status } })
    .then((r) => r.data);

export const addToWaitlist = (body: {
  patient_uuid: string;
  provider_id: string;
  visit_type_id: string;
  priority?: number;
}) => client.post<WaitlistEntry>("/waitlist", body).then((r) => r.data);

export const acceptOffer = (entryId: string) =>
  client.patch(`/waitlist/${entryId}/accept`).then((r) => r.data);

export const declineOffer = (entryId: string) =>
  client.patch<WaitlistEntry>(`/waitlist/${entryId}/decline`).then((r) => r.data);

export const offerSlot = (entryId: string) =>
  client.post<WaitlistEntry>(`/waitlist/${entryId}/offer`).then((r) => r.data);
