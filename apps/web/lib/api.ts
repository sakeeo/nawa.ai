export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly title: string,
    public readonly detail: string,
  ) {
    super(detail || title);
    this.name = "ApiError";
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie.split("; ").find((part) => part.startsWith("csrf_token="));
  return match?.slice("csrf_token=".length);
}

// RFC 7807 problems carry a string `detail`; FastAPI validation errors carry a list.
function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = item.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field}: ${item.msg}` : (item.msg ?? "");
      })
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!SAFE_METHODS.has(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  const response = await fetch(`/api/v1${path}`, { ...init, credentials: "same-origin", headers });
  if (!response.ok) {
    let problem: { title?: string; detail?: unknown } = {};
    try {
      problem = (await response.json()) as typeof problem;
    } catch {
      // Body is not JSON; fall back to the status text.
    }
    throw new ApiError(response.status, problem.title ?? response.statusText, describeDetail(problem.detail));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return { method, body: body === undefined ? undefined : JSON.stringify(body) };
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody("POST", body)),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody("PATCH", body)),
  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
