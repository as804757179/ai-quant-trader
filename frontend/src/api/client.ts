import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

export interface APIResponse<T = unknown> {
  success: boolean;
  data: T;
  message: string;
}

export async function get<T>(url: string, params?: Record<string, unknown>) {
  const res = await client.get<APIResponse<T>>(url, { params });
  return res.data;
}

export async function post<T>(url: string, body?: Record<string, unknown>) {
  const res = await client.post<APIResponse<T>>(url, body);
  return res.data;
}

export default client;