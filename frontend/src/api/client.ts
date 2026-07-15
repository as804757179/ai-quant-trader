import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 120000, // 全市场同步/回测可能较久
  headers: {
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8",
  },
});

// 生产环境可在构建时注入 VITE_API_KEY，对应后端 API_KEY
const apiKey = import.meta.env.VITE_API_KEY as string | undefined;
if (apiKey) {
  client.defaults.headers.common["X-API-Key"] = apiKey;
}

export interface APIResponse<T = unknown> {
  success: boolean;
  data: T;
  message: string;
}

function formatApiError(err: unknown, fallback: string): Error {
  const ax = err as {
    message?: string;
    code?: string;
    response?: {
      status?: number;
      data?: { message?: string; detail?: { message?: string } | string };
    };
  };
  const status = ax.response?.status;
  const detail = ax.response?.data?.detail;
  const detailMsg =
    typeof detail === "string"
      ? detail
      : detail && typeof detail === "object"
        ? detail.message
        : undefined;
  const msg =
    ax.response?.data?.message ||
    detailMsg ||
    (status === 500 || status === 502 || status === 503
      ? "后端服务异常或未启动（请确认 8000 端口）"
      : undefined) ||
    (ax.code === "ECONNABORTED" ? "请求超时，请稍后重试" : undefined) ||
    ax.message ||
    fallback;
  const error = new Error(String(msg)) as Error & { status?: number };
  error.name = "ApiError";
  error.status = status;
  return error;
}

export async function get<T>(url: string, params?: Record<string, unknown>) {
  try {
    const res = await client.get<APIResponse<T>>(url, { params });
    return res.data;
  } catch (err) {
    throw formatApiError(err, "请求失败");
  }
}

export default client;
