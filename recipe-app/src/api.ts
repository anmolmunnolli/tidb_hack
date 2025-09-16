// recipe-app/src/api.ts
import Config from "./config";
import AsyncStorage from "@react-native-async-storage/async-storage";

/** =========================
 * Common shapes
 * ========================*/
export type User = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
};

export type AuthResponse = { token: string; user: User };
export type ErrorResponse = { detail?: string; error?: string };

/** =========================
 * Low-level fetch helpers
 * ========================*/

/** Tiny fetch helper that returns typed JSON and throws nice Errors */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
    const msg =
      errData.detail || errData.error || res.statusText || "Request failed";
    throw new Error(msg);
  }

  // Return typed payload
  return data as T;
}

/** Same as apiFetch but automatically attaches Authorization header if token exists */
export async function apiFetchAuthed<T>(
  path: string,
  init?: RequestInit,
  explicitToken?: string | null
): Promise<T> {
  const token =
    explicitToken ?? (await AsyncStorage.getItem("token")) ?? undefined;

  return apiFetch<T>(path, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
}

/** Convenience helpers for token storage (optional to use elsewhere) */
export async function saveToken(token: string) {
  await AsyncStorage.setItem("token", token);
}
export async function getToken(): Promise<string | null> {
  return AsyncStorage.getItem("token");
}
export async function clearToken() {
  await AsyncStorage.removeItem("token");
}

/** =========================
 * Auth API
 * ========================*/
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

export async function loginUser(
  email: string,
  password: string,
  { persistToken = true }: { persistToken?: boolean } = {}
): Promise<AuthResponse> {
  const auth = await apiFetch<AuthResponse>("/api/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (persistToken && auth?.token) {
    await saveToken(auth.token);
  }
  return auth;
}

/** =========================
 * Cook endpoint types
 * ========================*/
export type CookLine = {
  ingredient: string;
  matched_pantry?: string;
  used?: string;
  remaining?: string;
  reason?: string;
  match_conf?: number;
};

export type CookResponse = {
  ok: boolean;
  plan_id: number;
  deducted: CookLine[];
  shortages: CookLine[];
  requires_confirmation: boolean;
};

/** Preview/commit cooking for a meal plan.
 * - confirm=false → preview (no DB changes)
 * - confirm=true  → commit (deduct & persist)
 * Token can be passed explicitly, or it will be read from AsyncStorage('token').
 */
export async function cookMealPlan(
  planId: number,
  confirm: boolean,
  token?: string | null
): Promise<CookResponse> {
  const qs = confirm ? "true" : "false";
  return apiFetchAuthed<CookResponse>(
    `/api/mealplan/${planId}/cook?confirm=${qs}`,
    { method: "POST" },
    token ?? undefined
  );
}
