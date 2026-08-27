import client from "./client";
import type { PatientContextResponse, ProtocolSearchResponse } from "../types";

// Protocol docs carry no PHI, so any authenticated staff role may search them.
export async function searchProtocols(q: string, k = 5): Promise<ProtocolSearchResponse> {
  const res = await client.get("/rag/protocols/search", { params: { q, k } });
  return res.data;
}

// Identity-resolving: admin/provider only, and every call writes an
// identity_access_log row server-side.
export async function fetchPatientContext(
  uuid: string,
  q: string,
  k = 5,
): Promise<PatientContextResponse> {
  const res = await client.get(`/rag/patients/${uuid}/context`, { params: { q, k } });
  return res.data;
}
