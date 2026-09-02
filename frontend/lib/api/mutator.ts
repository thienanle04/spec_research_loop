import { API_BASE_URL, ApiError, getStoredToken, setStoredToken } from "./config";
import { loginDestination } from "../auth-return";

/**
 * Orval fetch mutator — attaches JWT Bearer and returns { data, status, headers }.
 */
export async function customFetch<T>(url: string, options: RequestInit): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getStoredToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }

  const target = url.startsWith("http") ? url : `${API_BASE_URL}${url}`;
  const response = await fetch(target, { ...options, headers });

  let data: unknown;
  const contentType = response.headers.get("content-type") ?? "";
  if (response.status !== 204 && contentType.includes("application/json")) {
    data = await response.json();
  } else if (response.status !== 204 && contentType.includes("application/pdf")) {
    data = await response.arrayBuffer();
  } else if (response.status !== 204) {
    data = await response.text();
  }

  if (response.status === 401) {
    setStoredToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.assign(loginDestination(returnTo));
    }
    const detail =
      typeof data === "object" && data && "detail" in data && typeof data.detail === "string"
        ? data.detail
        : "Not authenticated";
    throw new ApiError(401, detail, data);
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data && typeof data.detail === "string"
        ? data.detail
        : response.statusText || `Request failed (${response.status})`;
    throw new ApiError(response.status, detail, data);
  }

  return { data, status: response.status, headers: response.headers } as T;
}

export type ErrorType<ErrorData> = ApiError & { data?: ErrorData };
export type BodyType<BodyData> = BodyData;
