// app/+not-found.tsx
import { View, Text, Pressable } from "react-native";
import { Link, type Href } from "expo-router";

export default function NotFound() {
  return (
    <View style={{ flex:1, justifyContent:"center", alignItems:"center", gap:12, padding:16 }}>
      <Text style={{ fontSize:18, fontWeight:"700" }}>Screen not found</Text>

      <Link href={"/(auth)/login" as Href} asChild>
        <Pressable style={{ padding:12, backgroundColor:"#111827", borderRadius:8 }}>
          <Text style={{ color:"#fff" }}>Go to Login</Text>
        </Pressable>
      </Link>

      <Link href={"/(tabs)/index" as Href} asChild>
        <Pressable style={{ padding:12, backgroundColor:"#2563eb", borderRadius:8 }}>
          <Text style={{ color:"#fff" }}>Go to Home</Text>
        </Pressable>
      </Link>
    </View>
  );
}
