import { ApiError } from "@/lib/api";
import { canManageDocuments } from "@/lib/documents";
import type { DataSourceCreate, DataSourceStatus, DiscoverySummary, Me } from "@/lib/types";

export const SSL_MODES = ["prefer", "require", "disable"] as const;

export type ConnectionForm = {
  name: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  ssl_mode: string;
};

export function emptyConnectionForm(): ConnectionForm {
  return { name: "", host: "", port: "5432", database: "", username: "", password: "", ssl_mode: "prefer" };
}

/** Messages (Indonesian, like the other pages) for everything wrong with the form. */
export function validateConnectionForm(form: ConnectionForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Nama sumber data wajib diisi.");
  const host = form.host.trim();
  if (!host) problems.push("Host wajib diisi.");
  else if (/[\s/]/.test(host) || host.includes("://")) {
    problems.push("Host hanya berisi nama atau alamat server, tanpa spasi, garis miring, atau skema.");
  }
  const port = form.port.trim();
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    problems.push("Port harus bilangan bulat 1 sampai 65535.");
  }
  if (!form.database.trim()) problems.push("Nama database wajib diisi.");
  if (!form.username.trim()) problems.push("Nama pengguna wajib diisi.");
  if (!form.password) problems.push("Kata sandi wajib diisi.");
  return problems;
}

export function toCreateBody(form: ConnectionForm): DataSourceCreate {
  return {
    name: form.name.trim(),
    host: form.host.trim(),
    port: Number(form.port.trim()),
    database: form.database.trim(),
    username: form.username.trim(),
    password: form.password,
    ssl_mode: form.ssl_mode,
  };
}

export function statusLabel(status: DataSourceStatus): { text: string; icon: string; className: string } {
  switch (status) {
    case "ok":
      return { text: "Terhubung", icon: "✓", className: "bg-green-100 text-green-800" };
    case "failed":
      return { text: "Gagal", icon: "✕", className: "bg-red-100 text-red-800" };
    default:
      return { text: "Belum diuji", icon: "•", className: "bg-gray-100 text-gray-700" };
  }
}

/** The list a user should read after a failed call: server problems, else the message. */
export function parseProblems(error: unknown): string[] {
  if (error instanceof ApiError) {
    return error.problems.length > 0 ? error.problems : [error.message];
  }
  return ["Terjadi kesalahan. Coba lagi."];
}

export function scrubSecret(text: string, secret: string): string {
  return secret ? text.split(secret).join("***") : text;
}

export function canManageData(me: Me, workspaceId: string): boolean {
  return canManageDocuments(me, workspaceId);
}

export function describeDiscovery(summary: DiscoverySummary): string {
  const base = `${summary.tables} tabel, ${summary.columns} kolom, ${summary.sampled_columns} kolom dengan contoh nilai.`;
  return summary.has_semantic_model
    ? base
    : `${base} Contoh nilai baru diambil setelah Anda menyimpan model semantik: simpan model, lalu jalankan Discover lagi.`;
}

export function describeAskError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Pertanyaan gagal diproses. Coba lagi.";
  switch (error.status) {
    case 429:
      return "Terlalu banyak pertanyaan. Coba lagi sebentar lagi.";
    case 503:
      return "Model AI sedang tidak tersedia. Coba lagi nanti.";
    case 403:
      return "Anda tidak memiliki izin untuk bertanya pada data ini.";
    default:
      return error.detail || "Pertanyaan gagal diproses. Coba lagi.";
  }
}
