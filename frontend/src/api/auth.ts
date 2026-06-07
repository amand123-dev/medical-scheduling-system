import type { TokenResponse } from "../types";
import client from "./client";

export async function login(username: string, password: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/login", { username, password });
  return data;
}
