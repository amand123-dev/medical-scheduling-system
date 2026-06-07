import client from "./client";
import type { OutreachEvent } from "../types";

export async function fetchOutreachLog(limit = 100): Promise<OutreachEvent[]> {
  const res = await client.get("/outreach-log", { params: { limit } });
  return res.data;
}
