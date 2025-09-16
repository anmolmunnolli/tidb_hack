// src/pantryApi.ts
import Config from "./config";
import { getToken } from "./auth";

export type PantryItem = {
  id: number;
  name: string;
  qty?: number | null;
  unit?: string | null;
  expires_on?: string | null;
  added_at: string;
  norm_qty?: number | null;
  norm_unit?: string | null;
};

async function authFetch(path: string, init: RequestInit = {}) {
  const token = await getToken();
    console.log("[authFetch] token len:", token?.length, "path:", path); // <-- add

  if (!token) throw new Error("Not authenticated");

  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`, // <- required by FastAPI
    ...(init.headers || {}),
  };


const res = await fetch(`${Config.API_BASE}${path}`, {
  ...init,
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(init.headers||{}) }
});

  const txt = await res.text();
  let data: any = {};
  if (txt) { try { data = JSON.parse(txt); } catch {} }

  if (!res.ok) {
    const msg = data?.detail || data?.error || `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return data;
}

export async function fetchPantry(): Promise<PantryItem[]> {
  return authFetch("/api/pantry");
}

export async function addPantry(d: {
  name: string;
  qty?: number;
  unit?: string;
  expires_on?: string;
}): Promise<PantryItem> {
  return authFetch("/api/pantry", { method: "POST", body: JSON.stringify(d) });
}

export async function deletePantry(id: number) {
  return authFetch(`/api/pantry/${id}`, { method: "DELETE" });
}

export async function updatePantry(
  id: number,
  d: { name: string; qty?: number; unit?: string; expires_on?: string }
): Promise<PantryItem> {
  return authFetch(`/api/pantry/${id}`, { method: "PUT", body: JSON.stringify(d) });
}
