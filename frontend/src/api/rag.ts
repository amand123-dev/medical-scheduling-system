import client from "./client";
import type { ProtocolSearchResponse } from "../types";

// Protocol docs carry no PHI, so any authenticated staff role may search them.
export async function searchProtocols(q: string, k = 5): Promise<ProtocolSearchResponse> {
  const res = await client.get("/rag/protocols/search", { params: { q, k } });
  return res.data;
}
