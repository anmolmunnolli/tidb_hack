// src/config.ts
import { Platform } from "react-native";

const API_BASE =
  Platform.select({
    ios: "http://127.0.0.1:8000",      
    android: "http://10.31.18.150:8000",   
    default: "http://10.31.18.150:8000",  
  })!;

export default { API_BASE };
