"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ChunkOut } from "@/lib/types";

export function CitationPanel({
  workspaceId,
  chunkId,
  marker,
  onClose,
}: {
  workspaceId: string;
  chunkId: string;
  marker: number;
  onClose: () => void;
}) {
  const [loaded, setLoaded] = useState<{ id: string; chunk?: ChunkOut; error?: string } | null>(null);
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getChunk(workspaceId, chunkId)
      .then((chunk) => !cancelled && setLoaded({ id: chunkId, chunk }))
      .catch(
        (e) =>
          !cancelled &&
          setLoaded({ id: chunkId, error: e instanceof ApiError ? e.message : "Potongan dokumen tidak dapat dimuat." }),
      );
    return () => {
      cancelled = true;
    };
  }, [workspaceId, chunkId]);

  useEffect(() => {
    panel.current?.focus();
  }, [chunkId]);

  const current = loaded?.id === chunkId ? loaded : null;
  const chunk = current?.chunk;
  return (
    <aside
      ref={panel}
      tabIndex={-1}
      role="dialog"
      aria-label={`Sumber [${marker}]`}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
      className="w-80 shrink-0 rounded border bg-white p-4 text-sm outline-none focus:ring-2 focus:ring-gray-400"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-medium break-all">
          [{marker}] {chunk?.filename ?? "Sumber"}
        </h2>
        <button onClick={onClose} aria-label="Tutup panel sumber" className="text-gray-600 underline">
          Tutup
        </button>
      </div>
      {!current && <p className="mt-3 text-gray-500">Memuat…</p>}
      {current?.error && (
        <p role="alert" className="mt-3 text-red-700">
          {current.error}
        </p>
      )}
      {chunk && (
        <>
          <p className="mt-1 text-xs text-gray-600">
            {chunk.page !== null && `Halaman ${chunk.page}`}
            {chunk.page !== null && chunk.section_path && " · "}
            {chunk.section_path}
          </p>
          <mark className="mt-3 block max-h-96 overflow-auto rounded bg-yellow-100 p-3 whitespace-pre-wrap text-gray-900">
            {chunk.text}
          </mark>
        </>
      )}
    </aside>
  );
}
