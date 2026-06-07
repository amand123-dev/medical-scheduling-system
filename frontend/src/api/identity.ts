import client from "./client";
import type { AuditLogEntry, PatientIdentityResponse } from "../types";

export async function fetchAuditLog(limit = 100, offset = 0): Promise<AuditLogEntry[]> {
  const res = await client.get("/identity/audit-log", { params: { limit, offset } });
  return res.data;
}

export async function fetchPatientIdentity(uuid: string): Promise<PatientIdentityResponse> {
  const res = await client.get(`/identity/patients/${uuid}`);
  return res.data;
}
