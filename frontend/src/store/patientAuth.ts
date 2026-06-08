import { create } from "zustand";
import { setToken } from "../api/client";

function decodePatientUUID(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.role === "patient" ? (payload.sub as string) : null;
  } catch {
    return null;
  }
}

interface PatientAuthState {
  isAuthenticated: boolean;
  patientUuid: string | null;
  email: string | null;
  login: (token: string, email: string) => void;
  logout: () => void;
}

export const usePatientAuthStore = create<PatientAuthState>((set) => ({
  isAuthenticated: false,
  patientUuid: null,
  email: null,
  login: (token, email) => {
    setToken(token);
    const patientUuid = decodePatientUUID(token);
    set({ isAuthenticated: true, patientUuid, email });
  },
  logout: () => {
    setToken(null);
    set({ isAuthenticated: false, patientUuid: null, email: null });
  },
}));
