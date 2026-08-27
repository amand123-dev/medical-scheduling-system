import client from "./client";
import type {
  PatientAnswerResponse,
  PatientContextResponse,
  ProtocolAnswerResponse,
  ProtocolSearchResponse,
} from "../types";

const GENERATION_TIMEOUT_MS = 90_000;

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

// Grounded generation over the protocol corpus. No PHI involved, so this is
// open to the same roles as plain protocol search.
export async function askProtocols(q: string, k = 5): Promise<ProtocolAnswerResponse> {
  // Generation is slower than retrieval, and the API sleeps when idle -- the
  // client default of 30s can expire on a cold start plus a long answer.
  const res = await client.post("/rag/protocols/ask", { q, k }, { timeout: GENERATION_TIMEOUT_MS });
  return res.data;
}

// Sends de-identified patient passages to an external model. Disabled server-side
// by default (patient_generation_enabled); a 403 here means the practice has not
// turned it on, which is the expected state without a BAA in place.
export async function askPatient(
  uuid: string, q: string, k = 5,
): Promise<PatientAnswerResponse> {
  const res = await client.post(
    `/rag/patients/${uuid}/ask`,
    { q, k },
    { timeout: GENERATION_TIMEOUT_MS },
  );
  return res.data;
}
