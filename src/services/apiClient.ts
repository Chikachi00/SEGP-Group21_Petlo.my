/** Shared HTTP transport. This module does not start requests on import. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(message: string, status: number | null, code: string, details?: unknown, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, "method" | "body"> {
  json?: unknown;
  body?: BodyInit;
  timeoutMs?: number;
}

export interface ApiClient {
  request<T>(method: string, path: string, options?: ApiRequestOptions): Promise<T>;
}

export function createApiClient(config: { baseUrl: string; fetchImpl?: typeof fetch }): ApiClient {
  const baseUrl = config.baseUrl.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(baseUrl) && (!baseUrl.startsWith("/") || baseUrl.startsWith("//"))) {
    throw new Error("API base URL must be an HTTP(S) URL or a same-origin absolute path.");
  }

  return {
    async request<T>(method: string, path: string, options: ApiRequestOptions = {}): Promise<T> {
      if (!path.startsWith("/") || path.startsWith("//") || path.includes("..")) {
        throw new Error("API endpoint must be an absolute path without parent segments.");
      }
      const { json, body, timeoutMs = 30_000, signal, headers: suppliedHeaders, ...init } = options;
      if (json !== undefined && body !== undefined) throw new Error("Specify json or body, not both.");
      if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("timeoutMs must be positive.");
      const headers = new Headers(suppliedHeaders);
      headers.set("Accept", "application/json");
      if (json !== undefined) headers.set("Content-Type", "application/json");
      // Leave multipart Content-Type to the browser, including its boundary.
      if (body instanceof FormData) headers.delete("Content-Type");
      const controller = new AbortController();
      let timedOut = false;
      const abort = () => controller.abort(signal?.reason);
      if (signal?.aborted) abort();
      else signal?.addEventListener("abort", abort, { once: true });
      const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeoutMs);

      try {
        const response = await (config.fetchImpl ?? globalThis.fetch)(`${baseUrl}${path}`, {
          ...init,
          method,
          headers,
          body: json !== undefined ? JSON.stringify(json) : body,
          signal: controller.signal,
        });
        const text = await response.text();
        let payload: unknown;
        try { payload = text ? JSON.parse(text) : undefined; }
        catch {
          throw new ApiError(response.ok ? "Server returned invalid JSON." : `Request failed (${response.status}).`, response.status, "INVALID_RESPONSE");
        }
        if (!response.ok) {
          const error = (payload as { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } | undefined)?.error;
          throw new ApiError(error?.message ?? `Request failed (${response.status}).`, response.status,
            error?.code ?? "HTTP_ERROR", error?.details,
            error?.request_id ?? response.headers.get("X-Request-ID"));
        }
        if (payload === undefined && response.status !== 204) {
          throw new ApiError("Server returned an empty response.", response.status, "INVALID_RESPONSE");
        }
        return payload as T;
      } catch (error) {
        if (signal?.aborted) throw signal.reason ?? new DOMException("Request aborted", "AbortError");
        if (timedOut) throw new ApiError("Request timed out.", null, "TIMEOUT");
        if (error instanceof ApiError) throw error;
        throw new ApiError("Could not reach the API. Check the server address and CORS configuration.", null, "NETWORK_ERROR");
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
      }
    },
  };
}

// VITE_* values are public browser configuration. Never put database credentials here.
export const apiClient = createApiClient({
  baseUrl: import.meta.env?.VITE_API_BASE_URL || "/api/v1",
});
