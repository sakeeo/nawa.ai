import { parseSse } from "@/lib/sse";
import type {
  ChatEvent,
  ChunkOut,
  ConnectionReport,
  ConversationDetail,
  ConversationSummary,
  DataSource,
  DataSourceCreate,
  DataSourceCreated,
  DiscoverySummary,
  DocumentOut,
  SemanticDraft,
  SemanticModelRead,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly title: string,
    public readonly detail: string,
    /** Individual problems the server listed (for example a rejected semantic model). */
    public readonly problems: string[] = [],
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

async function toApiError(response: Response): Promise<ApiError> {
  let problem: { title?: string; detail?: unknown; problems?: unknown } = {};
  try {
    problem = (await response.json()) as typeof problem;
  } catch {
    // Body is not JSON; fall back to the status text.
  }
  const problems = Array.isArray(problem.problems)
    ? problem.problems.filter((item): item is string => typeof item === "string")
    : [];
  return new ApiError(
    response.status,
    problem.title ?? response.statusText,
    describeDetail(problem.detail),
    problems,
  );
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!SAFE_METHODS.has(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  const response = await fetch(`/api/v1${path}`, { ...init, credentials: "same-origin", headers });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function withBody(method: string, body?: unknown): RequestInit {
  return { method, body: body === undefined ? undefined : JSON.stringify(body) };
}

/**
 * Streams the answer to a question as chat events. Throws ApiError before the first event on a
 * non-2xx response. Aborting `signal` cancels the request.
 */
export async function* streamChat(
  workspaceId: string,
  question: string,
  conversationId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  const response = await fetch(`/api/v1/workspaces/${workspaceId}/chat`, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal,
  });
  if (!response.ok) throw await toApiError(response);
  if (!response.body) return;
  yield* parseSse(response.body);
}

function dataPath(workspaceId: string, sourceId?: string, suffix = ""): string {
  return `/workspaces/${workspaceId}/data-sources${sourceId ? `/${sourceId}` : ""}${suffix}`;
}

/** Removes the connection password from anything the server echoed back. */
function withoutSecret(error: unknown, secret: string): unknown {
  if (!(error instanceof ApiError) || !secret) return error;
  const clean = (text: string) => text.split(secret).join("***");
  return new ApiError(error.status, error.title, clean(error.detail), error.problems.map(clean));
}

export const api = {
  streamChat,
  dataSources: {
    list: (workspaceId: string) => apiFetch<DataSource[]>(dataPath(workspaceId)),
    create: async (workspaceId: string, body: DataSourceCreate) => {
      try {
        return await apiFetch<DataSourceCreated>(dataPath(workspaceId), withBody("POST", body));
      } catch (error) {
        throw withoutSecret(error, body.password);
      }
    },
    test: (workspaceId: string, sourceId: string) =>
      apiFetch<ConnectionReport>(dataPath(workspaceId, sourceId, "/test"), { method: "POST" }),
    discover: (workspaceId: string, sourceId: string) =>
      apiFetch<DiscoverySummary>(dataPath(workspaceId, sourceId, "/discover"), { method: "POST" }),
    remove: (workspaceId: string, sourceId: string) =>
      apiFetch<void>(dataPath(workspaceId, sourceId), { method: "DELETE" }),
  },
  semantic: {
    get: (workspaceId: string, sourceId: string) =>
      apiFetch<SemanticModelRead>(dataPath(workspaceId, sourceId, "/semantic-model")),
    draft: (workspaceId: string, sourceId: string) =>
      apiFetch<SemanticDraft>(dataPath(workspaceId, sourceId, "/semantic-model/draft"), {
        method: "POST",
      }),
    save: (workspaceId: string, sourceId: string, yaml: string) =>
      apiFetch<SemanticModelRead>(
        dataPath(workspaceId, sourceId, "/semantic-model"),
        withBody("PUT", { yaml }),
      ),
  },
  listConversations: (workspaceId: string) =>
    apiFetch<ConversationSummary[]>(`/workspaces/${workspaceId}/conversations`),
  getConversation: (workspaceId: string, conversationId: string) =>
    apiFetch<ConversationDetail>(`/workspaces/${workspaceId}/conversations/${conversationId}`),
  sendFeedback: (workspaceId: string, messageId: string, value: 1 | -1, comment?: string) =>
    apiFetch<void>(`/workspaces/${workspaceId}/messages/${messageId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ value, comment: comment || null }),
    }),
  listDocuments: (workspaceId: string) => apiFetch<DocumentOut[]>(`/workspaces/${workspaceId}/documents`),
  // The browser sets the multipart Content-Type (with its boundary) for FormData.
  uploadDocument: (workspaceId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<DocumentOut>(`/workspaces/${workspaceId}/documents`, { method: "POST", body: form });
  },
  deleteDocument: (workspaceId: string, documentId: string) =>
    apiFetch<void>(`/workspaces/${workspaceId}/documents/${documentId}`, { method: "DELETE" }),
  retryDocument: (workspaceId: string, documentId: string) =>
    apiFetch<DocumentOut>(`/workspaces/${workspaceId}/documents/${documentId}/retry`, { method: "POST" }),
  getChunk: (workspaceId: string, chunkId: string) =>
    apiFetch<ChunkOut>(`/workspaces/${workspaceId}/chunks/${chunkId}`),
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody("POST", body)),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, withBody("PATCH", body)),
  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
