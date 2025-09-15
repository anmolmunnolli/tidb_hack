// src/config.ts
import { Platform } from "react-native";

const API_BASE =
  Platform.select({
    ios: "http://localhost:8080",      
    android: "http://10.31.18.150:8080",   //replace the ip
    default: "http://10.31.18.150:8080",  //replace the ip
  })!;

export default { API_BASE };
