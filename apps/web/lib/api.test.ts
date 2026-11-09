import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, streamChat } from "@/lib/api";

function mockFetch(status: number, body: unknown, contentType = "application/json") {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": contentType },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function stubCookie(value: string) {
  vi.stubGlobal("document", { cookie: value });
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("prefixes /api/v1 and parses JSON", async () => {
    const fetchMock = mockFetch(200, { status: "ok" });
    await expect(api.get<{ status: string }>("/healthz")).resolves.toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/healthz",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("sends JSON bodies and the CSRF header on POST", async () => {
    stubCookie("other=1; csrf_token=abc123");
    const fetchMock = mockFetch(201, { id: "1" });
    await api.post("/workspaces", { name: "Finance" });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "Finance" }));
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
  });

  it("does not send a CSRF header on GET", async () => {
    stubCookie("csrf_token=abc123");
    const fetchMock = mockFetch(200, {});
    await api.get("/auth/me");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("supports PATCH and DELETE", async () => {
    stubCookie("csrf_token=t");
    const fetchMock = mockFetch(204, undefined);
    await api.patch("/x", { role: "member" });
    await api.delete("/x");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("PATCH");
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe("DELETE");
  });

  it("throws ApiError with problem details", async () => {
    mockFetch(404, { title: "Not Found", status: 404, detail: "Workspace not found" }, "application/problem+json");
    await expect(api.get("/workspaces/x/members")).rejects.toMatchObject({
      status: 404,
      title: "Not Found",
      detail: "Workspace not found",
    });
  });

  it("turns FastAPI validation errors into a readable detail", async () => {
    mockFetch(422, { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address" }] });
    await expect(api.post("/auth/login", {})).rejects.toMatchObject({
      status: 422,
      detail: "email: value is not a valid email address",
    });
  });

  it("returns undefined for 204", async () => {
    mockFetch(204, undefined);
    await expect(api.post("/auth/logout")).resolves.toBeUndefined();
  });

  it("ApiError message falls back to title", () => {
    expect(new ApiError(500, "Server Error", "").message).toBe("Server Error");
  });

  it("uploads a document as FormData without a manual content type, with CSRF", async () => {
    stubCookie("csrf_token=abc123");
    const fetchMock = mockFetch(202, { id: "d1", filename: "a.md", status: "queued" });
    const file = new File(["# hi"], "a.md", { type: "text/markdown" });
    const result = await api.uploadDocument("ws1", file);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(url).toBe("/api/v1/workspaces/ws1/documents");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("content-type");
    expect(headers["X-CSRF-Token"]).toBe("abc123");
    expect(result.status).toBe("queued");
  });

  it("maps upload errors to ApiError with status and detail", async () => {
    stubCookie("csrf_token=t");
    mockFetch(409, { title: "Conflict", detail: "This file is already uploaded." }, "application/problem+json");
    await expect(api.uploadDocument("ws1", new File(["x"], "a.md"))).rejects.toMatchObject({
      status: 409,
      detail: "This file is already uploaded.",
    });
  });

  it("lists documents, deletes and retries with the right verbs and paths", async () => {
    stubCookie("csrf_token=t");
    const docs = [{ id: "d1", filename: "a.md", status: "ready", page_count: null }];
    const fetchMock = mockFetch(200, docs);
    await expect(api.listDocuments("ws1")).resolves.toEqual(docs);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await api.deleteDocument("ws1", "d1");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(docs[0]), { status: 202 }));
    await api.retryDocument("ws1", "d1");
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls.map(([u, i]) => `${i.method ?? "GET"} ${u}`)).toEqual([
      "GET /api/v1/workspaces/ws1/documents",
      "DELETE /api/v1/workspaces/ws1/documents/d1",
      "POST /api/v1/workspaces/ws1/documents/d1/retry",
    ]);
  });

  it("still sends JSON content type for normal bodies", async () => {
    stubCookie("csrf_token=t");
    const fetchMock = mockFetch(200, {});
    await api.post("/x", { a: 1 });
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("streams chat events with CSRF, JSON body and the abort signal", async () => {
    stubCookie("csrf_token=abc123");
    const sse = `data: ${JSON.stringify({ type: "token", text: "hi" })}\n\n`;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const events = [];
    for await (const event of streamChat("ws1", "Apa?", "c1", controller.signal)) events.push(event);
    expect(events).toEqual([{ type: "token", text: "hi" }]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/ws1/chat");
    expect(JSON.parse(init.body as string)).toEqual({ question: "Apa?", conversation_id: "c1" });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
    expect(init.signal).toBe(controller.signal);
  });

  it("turns a non-2xx chat response into ApiError before any event", async () => {
    stubCookie("csrf_token=t");
    mockFetch(429, { title: "Too Many Requests", detail: "Too many questions." }, "application/problem+json");
    const iterate = async () => {
      for await (const _ of streamChat("ws1", "x", null)) void _;
    };
    await expect(iterate()).rejects.toMatchObject({ status: 429, detail: "Too many questions." });
  });

  it("aborts the chat request when the signal fires", async () => {
    stubCookie("csrf_token=t");
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
        ),
      ),
    );
    const controller = new AbortController();
    const pending = (async () => {
      for await (const _ of streamChat("ws1", "x", null, controller.signal)) void _;
    })();
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("posts feedback with value and comment", async () => {
    stubCookie("csrf_token=t");
    const fetchMock = mockFetch(204, undefined);
    await api.sendFeedback("ws1", "m1", -1, "kurang jelas");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/ws1/messages/m1/feedback");
    expect(JSON.parse(init.body as string)).toEqual({ value: -1, comment: "kurang jelas" });
  });
});
