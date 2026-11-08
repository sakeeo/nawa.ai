import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";

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
});
