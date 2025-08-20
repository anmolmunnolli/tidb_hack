// import React, { useState } from "react";
// import { View, TextInput, Button, Alert, StyleSheet } from "react-native";
// import { useRouter } from "expo-router";
// import Config from "../config";

// export default function RegisterScreen() {
//   const router = useRouter();

//   // ✅ State variables
//   const [firstName, setFirstName] = useState("");
//   const [lastName, setLastName] = useState("");
//   const [email, setEmail] = useState("");
//   const [password, setPassword] = useState("");

//   const handleRegister = async () => {
//     try {
//       const res = await fetch(`${Config.API_BASE}/api/register`, {
//         method: "POST",
//         headers: { "Content-Type": "application/json" },
//         body: JSON.stringify({ firstName, lastName, email, password }),
//       });

//       if (res.ok) {
//         Alert.alert("Success", "Account created!");
//         router.replace("/(auth)/login"); // ✅ redirect back to login
//       } else {
//         const error = await res.json();
//         Alert.alert("Error", error.detail || "Registration failed");
//       }
//     } catch (err) {
//       console.error(err);
//       Alert.alert("Error", "Something went wrong");
//     }
//   };

//   return (
//     <View style={styles.container}>
//       <TextInput
//         placeholder="First Name"
//         value={firstName}
//         onChangeText={setFirstName}
//         style={styles.input}
//       />
//       <TextInput
//         placeholder="Last Name"
//         value={lastName}
//         onChangeText={setLastName}
//         style={styles.input}
//       />
//       <TextInput
//         placeholder="Email"
//         value={email}
//         onChangeText={setEmail}
//         keyboardType="email-address"
//         style={styles.input}
//       />
//       <TextInput
//         placeholder="Password"
//         value={password}
//         onChangeText={setPassword}
//         secureTextEntry
//         style={styles.input}
//       />
//       <Button title="Register" onPress={handleRegister} />
//     </View>
//   );
// }

// const styles = StyleSheet.create({
//   container: { flex: 1, justifyContent: "center", padding: 20 },
//   input: {
//     borderWidth: 1,
//     borderColor: "#ccc",
//     padding: 10,
//     marginBottom: 10,
//     borderRadius: 5,
//   },
// });
