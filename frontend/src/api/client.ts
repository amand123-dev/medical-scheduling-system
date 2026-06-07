import axios from "axios";

// Token lives in module memory — not localStorage (avoids XSS token theft)
let _accessToken: string | null = null;

export function setToken(token: string | null) {
  _accessToken = token;
}

export function getToken() {
  return _accessToken;
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "/api",
});

client.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  return config;
});

export default client;
