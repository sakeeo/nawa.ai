import { ApiError } from "@/lib/api";
import type { DocumentOut, Me, Role } from "@/lib/types";

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A message when the file should not be sent at all, otherwise null. */
export function validateFile(file: { name: string; size: number }): string | null {
  const lower = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    return "Tipe berkas tidak didukung. Gunakan PDF, DOCX, TXT, atau MD.";
  }
  if (file.size === 0) return "Berkas kosong.";
  if (file.size > MAX_UPLOAD_BYTES) return "Berkas melebihi batas 20 MB.";
  return null;
}

export function describeUploadError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Unggahan gagal. Coba lagi.";
  switch (error.status) {
    case 409:
      return "Berkas ini sudah diunggah sebelumnya.";
    case 413:
      return "Berkas melebihi batas 20 MB.";
    case 415:
      return "Tipe berkas tidak didukung. Gunakan PDF, DOCX, TXT, atau MD.";
    case 403:
      return "Anda tidak memiliki izin untuk mengunggah dokumen.";
    case 422:
      return error.detail || "Berkas tidak valid.";
    default:
      return error.detail || "Unggahan gagal. Coba lagi.";
  }
}

export function hasInFlight(documents: Pick<DocumentOut, "status">[]): boolean {
  return documents.some((d) => d.status === "queued" || d.status === "processing");
}

export function roleIn(me: Me, workspaceId: string): Role | null {
  if (me.user.is_admin) return "admin";
  return me.memberships.find((m) => m.workspace_id === workspaceId)?.role ?? null;
}

export function canManageDocuments(me: Me, workspaceId: string): boolean {
  const role = roleIn(me, workspaceId);
  return role === "admin" || role === "manager";
}
