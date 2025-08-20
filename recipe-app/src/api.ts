// src/api.ts
import Config from "./config";

/** Shapes */
export type User = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
};

export type AuthResponse = { token: string; user: User };
export type ErrorResponse = { detail?: string; error?: string };

/** Tiny fetch helper that returns typed JSON and throws nice Errors */
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${Config.API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });

  // Read body as text first, then parse safely
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // leave data as {} if server returned non-JSON
      data = {};
    }
  }

  if (!res.ok) {
    const errData = data as ErrorResponse;
    const msg = errData.detail || errData.error || res.statusText || "Request failed";
    throw new Error(msg);
  }

  // Return typed payload
  return data as T;
}

/** Public API calls */
export type RegisterRequest = {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
};

export async function registerUser(d: RegisterRequest): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/api/register", {
    method: "POST",
    body: JSON.stringify(d),
  });
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/api/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}
