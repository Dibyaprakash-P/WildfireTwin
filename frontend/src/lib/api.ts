/** Typed fetch wrapper. Backend errors arrive as {error: {code, message, details}}. */

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

let tokenGetter: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

export function configureApi(getToken: () => string | null, unauthorized: () => void) {
  tokenGetter = getToken;
  onUnauthorized = unauthorized;
}

export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${BASE}${path}`;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenGetter();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { ...init, headers, body });
  } catch {
    throw new ApiError(0, "network_error", "Backend unreachable. Check that the API server is running.");
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: unknown } } | null)?.error;
    if (res.status === 401 && token) onUnauthorized();
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`, err?.details);
  }
  return data as T;
}

function safeJson(t: string): unknown {
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
