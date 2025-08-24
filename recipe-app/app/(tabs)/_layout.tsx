import { Tabs } from "expo-router";

export default function TabsLayout() {
  return (
    <Tabs>
      <Tabs.Screen name="pantry"  options={{ title: "Pantry" }} />
      <Tabs.Screen name="index"   options={{ title: "Home" }} />
      <Tabs.Screen name="plan"   options={{ title: "Plan" }} /> 

      {/* add more like <Tabs.Screen name="explore" /> as needed */}
    </Tabs>
  );
}
