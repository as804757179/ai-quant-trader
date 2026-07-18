import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  timeout: 120000, // 全市场同步/回测可能较久
  withCredentials: true,
  headers: {
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8",
  },
});

let csrfToken: string | undefined;

export function setCsrfToken(token: string | undefined): void {
  csrfToken = token;
}

client.interceptors.request.use((config) => {
  const method = config.method?.toUpperCase();
  if (csrfToken && method && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    config.headers["X-CSRF-Token"] = csrfToken;
  }
  return config;
});

export interface APIResponse<T = unknown> {
  success: boolean;
  data: T;
  message: string;
  timestamp?: string;
  requestId?: string;
  error_code?: string;
  retryable?: boolean;
  field_errors?: Array<{ field: string; message: string; type?: string }>;
}

function formatApiError(err: unknown, fallback: string): Error {
  if (err instanceof Error && err.name === "ApiError") {
    return err;
  }
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

function normalizeApiResponse<T>(
  payload: unknown,
  requestId: string | undefined,
): APIResponse<T> {
  if (!payload || typeof payload !== "object" || !("success" in payload) || !("data" in payload)) {
    const error = new Error("后端返回未登记的响应格式") as Error & { errorCode?: string };
    error.name = "ApiError";
    error.errorCode = "API_CONTRACT_INVALID";
    throw error;
  }
  const response = payload as APIResponse<T>;
  if (!response.success) {
    const error = new Error(response.message || "请求被拒绝") as Error & {
      status?: number;
      errorCode?: string;
      retryable?: boolean;
      fieldErrors?: APIResponse<T>["field_errors"];
      requestId?: string;
    };
    error.name = "ApiError";
    error.errorCode = response.error_code;
    error.retryable = response.retryable;
    error.fieldErrors = response.field_errors;
    error.requestId = requestId;
    throw error;
  }
  return { ...response, requestId };
}

export async function get<T>(url: string, params?: Record<string, unknown>) {
  try {
    const res = await client.get<APIResponse<T> | T>(url, { params });
    return normalizeApiResponse<T>(
      res.data,
      res.headers["x-request-id"] as string | undefined,
    );
  } catch (err) {
    throw formatApiError(err, "请求失败");
  }
}

export async function post<T>(
  url: string,
  data?: unknown,
  options?: { headers?: Record<string, string> },
) {
  try {
    const res = await client.post<APIResponse<T> | T>(url, data, options);
    return normalizeApiResponse<T>(
      res.data,
      res.headers["x-request-id"] as string | undefined,
    );
  } catch (err) {
    throw formatApiError(err, "提交失败");
  }
}

export default client;
