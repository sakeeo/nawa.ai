"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { describeAskError } from "@/lib/data-sources";
import { roleIn } from "@/lib/documents";
import type { AskResponse, AskStatus, DataSource, QueryLogEntry } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";
import { ResultView } from "./result-view";

const EXAMPLES = [
  "Berapa total penjualan bulan ini?",
  "Menu apa yang paling menguntungkan?",
  "Bandingkan penjualan bulan ini dengan bulan sebelumnya.",
  "Outlet mana yang memiliki performa terendah?",
  "Berapa porsi penjualan delivery dibanding dine-in?",
];
const MAX_CHARS = 2000;
const STATUS_TEXT: Record<AskStatus, string> = {
  ok: "✓ Berhasil",
  blocked: "✕ Diblokir",
  error: "✕ Gagal",
  clarification: "? Perlu penjelasan",
};

export default function DataAnalystPage() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const role = roleIn(me, id);
  const canAsk = role === "admin" || role === "manager" || role === "member";

  const [sources, setSources] = useState<DataSource[] | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<QueryLogEntry[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const ready = sources?.filter((s) => s.status === "ok") ?? [];

  useEffect(() => {
    api.dataSources
      .list(id)
      .then((list) => {
        setSources(list);
        const first = list.find((s) => s.status === "ok");
        setSourceId((current) => current || first?.id || "");
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Tidak dapat memuat sumber data."));
  }, [id]);

  const loadHistory = useCallback(() => {
    api.data
      .history(id, 20)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [id]);

  function toggleHistory() {
    if (!showHistory) loadHistory();
    setShowHistory((open) => !open);
  }

  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || !sourceId || loading) return;
    setError("");
    setLoading(true);
    setResult(null);
    try {
      setResult(await api.data.ask(id, sourceId, text));
      if (showHistory) loadHistory();
    } catch (e) {
      setError(describeAskError(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tanya data</h1>
        <div className="flex gap-4 text-sm">
          <Link href={`/workspaces/${id}/data/sources`} className="text-gray-600 underline">
            Sumber data
          </Link>
          <Link href={`/workspaces/${id}`} className="text-gray-600 underline">
            Kembali ke workspace
          </Link>
        </div>
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Ajukan pertanyaan bisnis. AI menulis query SQL baca-saja, dan Anda bisa memeriksa SQL, tabel,
        grafik, serta ringkasannya.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}

      {sources === null ? (
        !error && <p className="mt-6 text-sm text-gray-500">Memuat…</p>
      ) : ready.length === 0 ? (
        <p className="mt-6 rounded border bg-white p-6 text-center text-sm text-gray-600">
          Belum ada sumber data yang terhubung.{" "}
          <Link href={`/workspaces/${id}/data/sources`} className="underline">
            Hubungkan sumber data
          </Link>
          .
        </p>
      ) : !canAsk ? (
        <p className="mt-6 rounded border bg-white p-6 text-center text-sm text-gray-600">
          Peran viewer hanya dapat melihat. Minta peran member untuk mengajukan pertanyaan.
        </p>
      ) : (
        <form onSubmit={submit} className="mt-4">
          {ready.length > 1 && (
            <label className="block text-sm">
              Sumber data
              <select
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                className={inputClass}
              >
                {ready.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="mt-3 block text-sm">
            Pertanyaan
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit();
                }
              }}
              rows={2}
              placeholder="Contoh: Outlet mana dengan penjualan terendah bulan Agustus?"
              className={inputClass}
            />
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setQuestion(example)}
                className="rounded-full border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50"
              >
                {example}
              </button>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button disabled={loading || !question.trim() || !sourceId} className={buttonClass}>
              {loading ? "Menganalisis…" : "Tanya"}
            </button>
            <button type="button" onClick={toggleHistory} className="text-sm underline">
              {showHistory ? "Sembunyikan riwayat" : "Riwayat"}
            </button>
          </div>
        </form>
      )}

      {showHistory && (
        <section aria-label="Riwayat pertanyaan" className="mt-4 rounded border bg-white p-3 text-sm">
          {history === null ? (
            <p className="text-gray-500">Memuat…</p>
          ) : history.length === 0 ? (
            <p className="text-gray-500">Belum ada pertanyaan.</p>
          ) : (
            <ul className="divide-y">
              {history.map((entry) => (
                <li key={entry.id} className="flex items-center justify-between gap-3 py-1.5">
                  <button
                    type="button"
                    onClick={() => setQuestion(entry.question)}
                    className="text-left underline"
                  >
                    {entry.question}
                  </button>
                  <span className="shrink-0 text-xs text-gray-600">
                    {STATUS_TEXT[entry.status as AskStatus] ?? entry.status} ·{" "}
                    {new Date(entry.created_at).toLocaleString("id-ID")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {loading && (
        <p role="status" aria-busy="true" className="mt-6 text-sm text-gray-600">
          Menyusun dan menjalankan query…
        </p>
      )}
      {result && (
        <div className="mt-6">
          <ResultView key={result.query_id} workspaceId={id} result={result} />
        </div>
      )}
    </div>
  );
}
