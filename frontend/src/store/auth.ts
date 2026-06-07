import { create } from "zustand";
import { setToken } from "../api/client";
import type { StaffRole } from "../types";

function decodePayload(token: string): { role: StaffRole | null; providerId: string | null } {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return {
      role: (payload.role as StaffRole) ?? null,
      providerId: (payload.provider_id as string) ?? null,
    };
  } catch {
    return { role: null, providerId: null };
  }
}

interface AuthState {
  isAuthenticated: boolean;
  username: string | null;
  role: StaffRole | null;
  providerId: string | null;
  login: (token: string, username: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  username: null,
  role: null,
  providerId: null,
  login: (token, username) => {
    setToken(token);
    const { role, providerId } = decodePayload(token);
    set({ isAuthenticated: true, username, role, providerId });
  },
  logout: () => {
    setToken(null);
    set({ isAuthenticated: false, username: null, role: null, providerId: null });
  },
}));
