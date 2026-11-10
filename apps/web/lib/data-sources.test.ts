import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import {
  canManageData,
  describeAskError,
  describeDiscovery,
  emptyConnectionForm,
  parseProblems,
  scrubSecret,
  statusLabel,
  toCreateBody,
  validateConnectionForm,
} from "@/lib/data-sources";
import type { Me } from "@/lib/types";

const valid = {
  ...emptyConnectionForm(),
  name: "Demo",
  host: "postgres",
  port: "5432",
  database: "noesantara",
  username: "nawa_demo_ro",
  password: "s3cret-pw",
};

const me = (role: "viewer" | "member" | "manager" | "admin" | null, isAdmin = false): Me => ({
  user: { id: "u", email: "e@x.id", is_admin: isAdmin },
  memberships: role ? [{ workspace_id: "w1", role }] : [],
});

describe("validateConnectionForm", () => {
  it("accepts a complete form", () => {
    expect(validateConnectionForm(valid)).toEqual([]);
  });
  it("reports every missing field", () => {
    const problems = validateConnectionForm({ ...emptyConnectionForm(), port: "" });
    expect(problems.join(" ")).toMatch(/nama/i);
    expect(problems.join(" ")).toMatch(/host/i);
    expect(problems.join(" ")).toMatch(/port/i);
    expect(problems.join(" ")).toMatch(/database/i);
    expect(problems.join(" ")).toMatch(/pengguna/i);
    expect(problems.join(" ")).toMatch(/kata sandi/i);
  });
  it("rejects ports outside 1-65535 and non-integers", () => {
    for (const port of ["0", "65536", "-1", "54.32", "abc", ""]) {
      expect(validateConnectionForm({ ...valid, port }).join(" ")).toMatch(/port/i);
    }
    expect(validateConnectionForm({ ...valid, port: "65535" })).toEqual([]);
  });
  it("rejects a host that looks like a URL or contains spaces", () => {
    for (const host of ["postgres://db", "db host", "db/path"]) {
      expect(validateConnectionForm({ ...valid, host }).join(" ")).toMatch(/host/i);
    }
  });
  it("treats whitespace-only fields as empty", () => {
    expect(validateConnectionForm({ ...valid, name: "   " }).join(" ")).toMatch(/nama/i);
  });
});

describe("toCreateBody", () => {
  it("trims text fields, converts the port and keeps the password untouched", () => {
    const body = toCreateBody({ ...valid, name: " Demo ", host: " postgres ", password: " pw " });
    expect(body).toMatchObject({ name: "Demo", host: "postgres", port: 5432, password: " pw " });
  });
});

describe("statusLabel", () => {
  it("never relies on color alone", () => {
    expect(statusLabel("ok").text).toMatch(/terhubung/i);
    expect(statusLabel("failed").text).toMatch(/gagal/i);
    expect(statusLabel("untested").text).toMatch(/belum/i);
    for (const status of ["ok", "failed", "untested"] as const) {
      expect(statusLabel(status).icon).toBeTruthy();
    }
  });
});

describe("parseProblems", () => {
  it("returns the list sent by the server", () => {
    const error = new ApiError(422, "Unprocessable", "The model is not valid", ["a", "b"]);
    expect(parseProblems(error)).toEqual(["a", "b"]);
  });
  it("falls back to the message", () => {
    expect(parseProblems(new ApiError(409, "Conflict", "Run schema discovery first"))).toEqual([
      "Run schema discovery first",
    ]);
    expect(parseProblems(new Error("boom"))).toEqual(["Terjadi kesalahan. Coba lagi."]);
  });
});

describe("scrubSecret", () => {
  it("removes every occurrence of the secret", () => {
    expect(scrubSecret("bad pw hunter22 and hunter22", "hunter22")).toBe("bad pw *** and ***");
  });
  it("leaves the text alone for an empty secret", () => {
    expect(scrubSecret("nothing", "")).toBe("nothing");
  });
});

describe("canManageData", () => {
  it("is for managers and admins of that workspace only", () => {
    expect(canManageData(me("manager"), "w1")).toBe(true);
    expect(canManageData(me("admin"), "w1")).toBe(true);
    expect(canManageData(me(null, true), "w1")).toBe(true);
    expect(canManageData(me("member"), "w1")).toBe(false);
    expect(canManageData(me("viewer"), "w1")).toBe(false);
    expect(canManageData(me("manager"), "other")).toBe(false);
  });
});

describe("describeDiscovery", () => {
  it("summarises counts and says when samples were skipped", () => {
    const base = { tables: 9, columns: 41, created_at: "2025-01-01T00:00:00Z" };
    expect(
      describeDiscovery({ ...base, sampled_columns: 6, has_semantic_model: true }),
    ).toMatch(/9 tabel.*41 kolom.*6/);
    expect(
      describeDiscovery({ ...base, sampled_columns: 0, has_semantic_model: false }),
    ).toMatch(/simpan model/i);
  });
});

function mockFetch(status: number, body: unknown) {
  // A fresh Response per call: a body can be read only once.
  const fn = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/problem+json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api.dataSources", () => {
  it("creates a source with the CSRF header and the form body", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=tok1" });
    const fetchMock = mockFetch(201, { source: { id: "s1" }, report: { ok: true, problems: [] } });
    await api.dataSources.create("w1", toCreateBody(valid));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/w1/data-sources");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok1");
    expect(JSON.parse(init.body as string)).toMatchObject({ host: "postgres", port: 5432 });
  });

  it("never lets the password leak through an error message", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=tok1" });
    mockFetch(422, {
      title: "Unprocessable",
      detail: "auth failed for password s3cret-pw",
      problems: ["tried s3cret-pw"],
    });
    const error = await api.dataSources.create("w1", toCreateBody(valid)).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.message).not.toContain("s3cret-pw");
    expect(apiError.detail).not.toContain("s3cret-pw");
    expect(apiError.problems.join(" ")).not.toContain("s3cret-pw");
  });

  it("calls test, discover and delete on the source", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=t" });
    const fetchMock = mockFetch(200, {});
    await api.dataSources.test("w1", "s1");
    await api.dataSources.discover("w1", "s1");
    const calls = fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method]);
    expect(calls).toEqual([
      ["/api/v1/workspaces/w1/data-sources/s1/test", "POST"],
      ["/api/v1/workspaces/w1/data-sources/s1/discover", "POST"],
    ]);
    mockFetch(204, undefined);
    await expect(api.dataSources.remove("w1", "s1")).resolves.toBeUndefined();
  });
});

describe("api.semantic", () => {
  it("reads, drafts and saves the model", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=t" });
    const fetchMock = mockFetch(200, { version: 1, yaml: "tables: {}", created_at: "x" });
    await api.semantic.get("w1", "s1");
    await api.semantic.draft("w1", "s1");
    await api.semantic.save("w1", "s1", "tables: {}");
    const calls = fetchMock.mock.calls.map(([url, init]) => [
      url,
      (init as RequestInit).method ?? "GET",
    ]);
    expect(calls).toEqual([
      ["/api/v1/workspaces/w1/data-sources/s1/semantic-model", "GET"],
      ["/api/v1/workspaces/w1/data-sources/s1/semantic-model/draft", "POST"],
      ["/api/v1/workspaces/w1/data-sources/s1/semantic-model", "PUT"],
    ]);
    expect(JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)).toEqual({
      yaml: "tables: {}",
    });
  });

  it("surfaces the problem list of a rejected model", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=t" });
    mockFetch(422, { title: "Unprocessable", detail: "bad", problems: ["Column 'x' is missing"] });
    const error = await api.semantic.save("w1", "s1", "x").catch((e: unknown) => e);
    expect(parseProblems(error)).toEqual(["Column 'x' is missing"]);
  });
});

describe("api.data", () => {
  it("asks a question with the source id and the CSRF header", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=t9" });
    const fetchMock = mockFetch(200, { status: "ok" });
    await api.data.ask("w1", "s1", "omzet per outlet");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/workspaces/w1/data/ask");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("t9");
    expect(JSON.parse(init.body as string)).toEqual({
      data_source_id: "s1",
      question: "omzet per outlet",
    });
  });

  it("requests the insight, the history and sends feedback", async () => {
    vi.stubGlobal("document", { cookie: "csrf_token=t9" });
    const fetchMock = mockFetch(200, {});
    await api.data.insight("w1", "q1");
    await api.data.history("w1", 10);
    await api.data.feedback("w1", "q1", -1);
    const calls = fetchMock.mock.calls.map(([url, init]) => [
      url,
      (init as RequestInit).method ?? "GET",
    ]);
    expect(calls).toEqual([
      ["/api/v1/workspaces/w1/data/queries/q1/insight", "POST"],
      ["/api/v1/workspaces/w1/data/queries?limit=10", "GET"],
      ["/api/v1/workspaces/w1/data/queries/q1/feedback", "POST"],
    ]);
    expect(JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)).toEqual({
      value: -1,
    });
  });
});


describe("describeAskError", () => {
  it("explains rate limits, an unavailable model and a source that is not ready", () => {
    expect(describeAskError(new ApiError(429, "Too Many", "x"))).toMatch(/terlalu banyak/i);
    expect(describeAskError(new ApiError(503, "Unavailable", "x"))).toMatch(/model/i);
    expect(describeAskError(new ApiError(403, "Forbidden", "x"))).toMatch(/izin/i);
    expect(
      describeAskError(new ApiError(409, "Conflict", "Run schema discovery first")),
    ).toContain("Run schema discovery first");
    expect(describeAskError(new Error("net"))).toMatch(/gagal/i);
  });
});
