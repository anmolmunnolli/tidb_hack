// app/(tabs)/_layout.tsx
import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

export default function TabsLayout() {
  return (
    <Tabs>
      <Tabs.Screen
        name="index"
        options={{ title: "Home", tabBarIcon: ({ color, size }) => <Ionicons name="home" color={color} size={size} /> }}
      />
      <Tabs.Screen
        name="explore"
        options={{ title: "Explore", tabBarIcon: ({ color, size }) => <Ionicons name="compass" color={color} size={size} /> }}
      />
      <Tabs.Screen
        name="pantry"
        options={{ title: "Pantry", tabBarIcon: ({ color, size }) => <Ionicons name="basket" color={color} size={size} /> }}
      />
      <Tabs.Screen
        name="plan"
        options={{ title: "Plan", tabBarIcon: ({ color, size }) => <Ionicons name="bulb" color={color} size={size} /> }}
      />
      {/* ⬇️ NEW TAB */}
      <Tabs.Screen
        name="meal-plan"
        options={{ title: "Meal Plan", tabBarIcon: ({ color, size }) => <Ionicons name="list" color={color} size={size} /> }}
      />
    </Tabs>
  );
}
