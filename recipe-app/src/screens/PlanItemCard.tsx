import React from "react";
import { View, Text, Button } from "react-native";
import { useCookPlan } from "../../hooks/useCookPlan";
// If you use react-query, import your client and invalidate mealplan list onDone

type Props = {
  planId: number;
  title?: string;
  onRefetch?: () => void; // pass from parent to refresh the list
};

export default function PlanItemCard({ planId, title, onRefetch }: Props) {
  const { cook, loading } = useCookPlan(planId, {
    onDone: () => onRefetch?.(),
  });

  return (
    <View style={{ padding: 12, borderWidth: 1, borderRadius: 10, marginBottom: 10 }}>
      <Text style={{ fontWeight: "600", marginBottom: 8 }}>{title || "Meal"}</Text>
      <Button title={loading ? "Cooking..." : "Cook"} onPress={cook} disabled={loading} />
    </View>
  );
}
