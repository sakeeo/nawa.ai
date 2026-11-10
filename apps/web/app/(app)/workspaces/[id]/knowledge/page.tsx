"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  ACCEPTED_EXTENSIONS,
  canManageDocuments,
  describeUploadError,
  formatSize,
  hasInFlight,
  validateFile,
} from "@/lib/documents";
import { createPoller } from "@/lib/polling";
import type { DocumentOut, DocumentStatus } from "@/lib/types";
import { buttonClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";

const POLL_MS = 3000;
const STATUS_LABEL: Record<DocumentStatus, { text: string; className: string }> = {
  queued: { text: "Antre", className: "bg-gray-100 text-gray-700" },
  processing: { text: "Diproses", className: "bg-blue-100 text-blue-800" },
  ready: { text: "Siap", className: "bg-green-100 text-green-800" },
  failed: { text: "Gagal", className: "bg-red-100 text-red-800" },
};

export default function KnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const canManage = canManageDocuments(me, id);
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setDocuments(await api.listDocuments(id));
  }, [id]);

  useEffect(() => {
    api
      .listDocuments(id)
      .then(setDocuments)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Tidak dapat memuat dokumen."));
  }, [id]);

  const inFlight = documents !== null && hasInFlight(documents);
  useEffect(() => {
    if (!inFlight) return;
    const poller = createPoller({
      run: refresh,
      intervalMs: POLL_MS,
      isHidden: () => document.visibilityState === "hidden",
    });
    poller.start();
    return () => poller.stop();
  }, [inFlight, refresh]);

  async function upload(files: FileList | File[]) {
    setError("");
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const problem = validateFile(file);
        if (problem) {
          setError(`${file.name}: ${problem}`);
          continue;
        }
        try {
          await api.uploadDocument(id, file);
        } catch (e) {
          setError(`${file.name}: ${describeUploadError(e)}`);
        }
      }
      await refresh();
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (canManage && !uploading) void upload(event.dataTransfer.files);
  }

  async function act(action: () => Promise<unknown>, fallback: string) {
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
    }
  }

  function remove(doc: DocumentOut) {
    if (!window.confirm(`Hapus "${doc.filename}"? Potongan teksnya juga akan dihapus.`)) return;
    void act(() => api.deleteDocument(id, doc.id), "Dokumen tidak dapat dihapus.");
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Knowledge</h1>
        <Link href={`/workspaces/${id}`} className="text-sm text-gray-600 underline">
          Kembali ke workspace
        </Link>
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Dokumen yang diunggah menjadi sumber jawaban AI Assistant untuk workspace ini.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}

      {canManage && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`mt-4 rounded border-2 border-dashed p-6 text-center text-sm ${
            dragging ? "border-gray-900 bg-gray-50" : "border-gray-300"
          }`}
        >
          <p>Tarik berkas ke sini, atau</p>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS.join(",")}
            disabled={uploading}
            onChange={(e) => e.target.files && void upload(e.target.files)}
            className="sr-only"
            id="file-input"
          />
          <label
            htmlFor="file-input"
            className={`${buttonClass} mt-2 inline-block cursor-pointer ${uploading ? "opacity-50" : ""}`}
          >
            {uploading ? "Mengunggah…" : "Pilih berkas"}
          </label>
          <p className="mt-2 text-xs text-gray-500">PDF, DOCX, TXT, MD. Maksimal 20 MB per berkas.</p>
        </div>
      )}

      {documents === null ? (
        !error && <p className="mt-6 text-sm text-gray-500">Memuat…</p>
      ) : documents.length === 0 ? (
        <p className="mt-6 rounded border bg-white p-6 text-center text-sm text-gray-500">
          Belum ada dokumen
        </p>
      ) : (
        <table className="mt-6 w-full rounded border bg-white text-sm">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="px-3 py-2">Nama</th>
              <th className="px-3 py-2">Ukuran</th>
              <th className="px-3 py-2">Hal.</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Diunggah</th>
              {canManage && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => {
              const status = STATUS_LABEL[doc.status];
              return (
                <tr key={doc.id} className="border-t align-top">
                  <td className="px-3 py-2 break-all">{doc.filename}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatSize(doc.size_bytes)}</td>
                  <td className="px-3 py-2">{doc.page_count ?? "–"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${status.className}`}>{status.text}</span>
                    {doc.status === "failed" && doc.error && (
                      <p className="mt-1 text-xs text-red-700">{doc.error}</p>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {new Date(doc.created_at).toLocaleString("id-ID")}
                  </td>
                  {canManage && (
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {doc.status === "failed" && (
                        <button
                          onClick={() =>
                            void act(() => api.retryDocument(id, doc.id), "Tidak dapat mencoba ulang.")
                          }
                          className="mr-3 underline"
                        >
                          Coba lagi
                        </button>
                      )}
                      <button onClick={() => remove(doc)} className="text-red-600 underline">
                        Hapus
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
