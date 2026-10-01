import { create } from "zustand";

import { api, configureApi } from "../lib/api";
import type { User } from "../types/api";

const KEY = "wt.session";

interface Session {
  token: string;
  expiresAt: number;
  user: User;
}

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

interface AuthState {
  session: Session | null;
  setSession: (token: string, expiresIn: number, user: User) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  session: load(),
  setSession: (token, expiresIn, user) => {
    const s = { token, expiresAt: Date.now() + expiresIn * 1000, user };
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      /* storage unavailable: session lives in memory only */
    }
    set({ session: s });
  },
  logout: () => {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    set({ session: null });
  },
}));

configureApi(
  () => useAuth.getState().session?.token ?? null,
  () => useAuth.getState().logout(),
);

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  user: User;
  message?: string | null;
}

export async function loginWithPassword(email: string, password: string) {
  const r = await api<TokenResponse>("/api/auth/login", { method: "POST", json: { email, password } });
  useAuth.getState().setSession(r.access_token, r.expires_in, r.user);
  return r;
}
