// app/index.tsx
import { Redirect } from "expo-router";

export default function Index() {
  // ✅ Always force login as the first entry point
  return <Redirect href="/(auth)/login" />;
}
