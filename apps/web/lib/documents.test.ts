import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import {
  MAX_UPLOAD_BYTES,
  canManageDocuments,
  describeUploadError,
  formatSize,
  hasInFlight,
  validateFile,
} from "@/lib/documents";
import type { Me } from "@/lib/types";

const me = (role: "viewer" | "member" | "manager" | "admin" | null, isAdmin = false): Me => ({
  user: { id: "u", email: "e@x.id", is_admin: isAdmin },
  memberships: role ? [{ workspace_id: "w1", role }] : [],
});

describe("validateFile", () => {
  it("accepts supported types within the limit", () => {
    expect(validateFile({ name: "SOP.PDF", size: 100 })).toBeNull();
    expect(validateFile({ name: "a.md", size: MAX_UPLOAD_BYTES })).toBeNull();
  });
  it("rejects unsupported, empty and oversized files", () => {
    expect(validateFile({ name: "a.exe", size: 10 })).toMatch(/tidak didukung/);
    expect(validateFile({ name: "a.md", size: 0 })).toMatch(/kosong/);
    expect(validateFile({ name: "a.md", size: MAX_UPLOAD_BYTES + 1 })).toMatch(/20 MB/);
  });
});

describe("describeUploadError", () => {
  it("explains duplicate, too large and unsupported in plain language", () => {
    expect(describeUploadError(new ApiError(409, "Conflict", "x"))).toMatch(/sudah diunggah/);
    expect(describeUploadError(new ApiError(413, "Too Large", "x"))).toMatch(/20 MB/);
    expect(describeUploadError(new ApiError(415, "Unsupported", "x"))).toMatch(/tidak didukung/);
    expect(describeUploadError(new Error("net"))).toMatch(/gagal/);
  });
});

describe("hasInFlight", () => {
  it("is true only while a document is queued or processing", () => {
    expect(hasInFlight([{ status: "ready" }, { status: "failed" }])).toBe(false);
    expect(hasInFlight([{ status: "ready" }, { status: "queued" }])).toBe(true);
    expect(hasInFlight([{ status: "processing" }])).toBe(true);
    expect(hasInFlight([])).toBe(false);
  });
});

describe("canManageDocuments", () => {
  it("shows controls to manager and admin only", () => {
    expect(canManageDocuments(me("manager"), "w1")).toBe(true);
    expect(canManageDocuments(me("admin"), "w1")).toBe(true);
    expect(canManageDocuments(me(null, true), "w1")).toBe(true);
    expect(canManageDocuments(me("member"), "w1")).toBe(false);
    expect(canManageDocuments(me("viewer"), "w1")).toBe(false);
    expect(canManageDocuments(me("manager"), "other")).toBe(false);
  });
});

describe("formatSize", () => {
  it("formats bytes, KB and MB", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2048)).toBe("2.0 KB");
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
