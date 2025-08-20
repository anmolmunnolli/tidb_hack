import AsyncStorage from "@react-native-async-storage/async-storage";

export type PantryItem = {
  id: string;          // uuid
  name: string;
  qty?: number;
  unit?: string;       // e.g., pcs, g, ml
  category?: string;   // e.g., Produce, Dairy
  expiresOn?: string;  // ISO date
  addedAt: string;     // ISO date
};

export type ShoppingEntry = {
  id: string;
  name: string;
  qty?: number;
  unit?: string;
  checked?: boolean;
};

const K_PANTRY = "PANTRY_ITEMS";
const K_SHOPPING = "SHOPPING_LIST";

async function readJSON<T>(key: string, fallback: T): Promise<T> {
  const raw = await AsyncStorage.getItem(key);
  if (!raw) return fallback;
  try { return JSON.parse(raw) as T; } catch { return fallback; }
}

async function writeJSON<T>(key: string, value: T) {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

export async function getPantry(): Promise<PantryItem[]> {
  return readJSON<PantryItem[]>(K_PANTRY, []);
}

export async function setPantry(items: PantryItem[]) {
  await writeJSON(K_PANTRY, items);
}

export async function addPantryItem(item: PantryItem) {
  const cur = await getPantry();
  cur.unshift(item);
  await setPantry(cur);
}

export async function removePantryItem(id: string) {
  const cur = await getPantry();
  await setPantry(cur.filter(x => x.id !== id));
}

export async function getShopping(): Promise<ShoppingEntry[]> {
  return readJSON<ShoppingEntry[]>(K_SHOPPING, []);
}

export async function setShopping(items: ShoppingEntry[]) {
  await writeJSON(K_SHOPPING, items);
}

export async function addToShopping(item: ShoppingEntry) {
  const cur = await getShopping();
  cur.unshift(item);
  await setShopping(cur);
}

export async function clearAll() {
  await AsyncStorage.multiRemove([K_PANTRY, K_SHOPPING]);
}
