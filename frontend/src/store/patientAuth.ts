import { create } from "zustand";
import { setToken } from "../api/client";

const STORAGE_KEY = "patient_auth";

function decodePatientUUID(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.role === "patient" ? (payload.sub as string) : null;
  } catch {
    return null;
  }
}

function loadFromStorage(): { token: string; email: string; patientUuid: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// Restore session on module load so Axios has the token before any request fires
const saved = loadFromStorage();
if (saved?.token) setToken(saved.token);

interface PatientAuthState {
  isAuthenticated: boolean;
  patientUuid: string | null;
  email: string | null;
  login: (token: string, email: string) => void;
  logout: () => void;
}

export const usePatientAuthStore = create<PatientAuthState>((set) => ({
  isAuthenticated: !!saved?.token,
  patientUuid: saved?.patientUuid ?? null,
  email: saved?.email ?? null,
  login: (token, email) => {
    const patientUuid = decodePatientUUID(token);
    setToken(token);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, email, patientUuid }));
    set({ isAuthenticated: true, patientUuid, email });
  },
  logout: () => {
    setToken(null);
    localStorage.removeItem(STORAGE_KEY);
    set({ isAuthenticated: false, patientUuid: null, email: null });
  },
}));
