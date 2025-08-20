import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY_TOKEN = "token";
const KEY_USER  = "user";

async function secureAvailable() {
  try { return await SecureStore.isAvailableAsync(); } catch { return false; }
}

export async function setSession(token: string, user: any) {
  const useSecure = Platform.OS !== "web" && (await secureAvailable());
  if (useSecure) {
    await SecureStore.setItemAsync(KEY_TOKEN, token);
    await SecureStore.setItemAsync(KEY_USER, JSON.stringify(user));
  } else {
    await AsyncStorage.setItem(KEY_TOKEN, token);
    await AsyncStorage.setItem(KEY_USER, JSON.stringify(user));
  }
}

export async function getToken(): Promise<string | null> {
  const useSecure = Platform.OS !== "web" && (await secureAvailable());
  return useSecure ? SecureStore.getItemAsync(KEY_TOKEN) : AsyncStorage.getItem(KEY_TOKEN);
}

export async function clearSession() {
  const useSecure = Platform.OS !== "web" && (await secureAvailable());
  if (useSecure) {
    await SecureStore.deleteItemAsync(KEY_TOKEN);
    await SecureStore.deleteItemAsync(KEY_USER);
  } else {
    await AsyncStorage.multiRemove([KEY_TOKEN, KEY_USER]);
  }
}
