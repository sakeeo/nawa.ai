"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  type ConnectionForm,
  SSL_MODES,
  canManageData,
  describeDiscovery,
  emptyConnectionForm,
  parseProblems,
  statusLabel,
  toCreateBody,
  validateConnectionForm,
} from "@/lib/data-sources";
import type { ConnectionReport, DataSource, SemanticModelRead } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";

const FIELD_LABELS: { key: keyof ConnectionForm; label: string; type?: string }[] = [
  { key: "name", label: "Nama" },
  { key: "host", label: "Host" },
  { key: "port", label: "Port", type: "number" },
  { key: "database", label: "Database" },
  { key: "username", label: "Pengguna (read-only)" },
  { key: "password", label: "Kata sandi", type: "password" },
];

export default function DataSourcesPage() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const canManage = canManageData(me, id);

  const [sources, setSources] = useState<DataSource[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<ConnectionForm>(emptyConnectionForm());
  const [formProblems, setFormProblems] = useState<string[]>([]);
  const [report, setReport] = useState<ConnectionReport | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // The semantic model is tied to the source it was loaded for, so switching sources never
  // shows (or saves) the YAML of another one.
  const [semantic, setSemantic] = useState<{
    sourceId: string;
    model: SemanticModelRead | null;
    yaml: string;
  } | null>(null);
  const [yamlProblems, setYamlProblems] = useState<string[]>([]);

  const selected = sources?.find((s) => s.id === selectedId) ?? null;
  const loaded = semantic !== null && semantic.sourceId === selectedId ? semantic : null;
  const model = loaded?.model ?? null;
  const yaml = loaded?.yaml ?? "";

  const applyList = useCallback((list: DataSource[]) => {
    setSources(list);
    setSelectedId((current) => (list.some((s) => s.id === current) ? current : (list[0]?.id ?? null)));
  }, []);
  const loadSources = useCallback(async () => applyList(await api.dataSources.list(id)), [applyList, id]);

  useEffect(() => {
    api.dataSources
      .list(id)
      .then(applyList)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Tidak dapat memuat sumber data."));
  }, [applyList, id]);

  useEffect(() => {
    if (!selectedId) return;
    api.semantic
      .get(id, selectedId)
      .then((read) => setSemantic({ sourceId: selectedId, model: read, yaml: read.yaml }))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) {
          setSemantic({ sourceId: selectedId, model: null, yaml: "" });
        } else {
          setError(e instanceof ApiError ? e.message : "Tidak dapat memuat model semantik.");
        }
      });
  }, [id, selectedId]);

  function selectSource(sourceId: string) {
    setSelectedId(sourceId);
    setYamlProblems([]);
  }

  function editYaml(text: string) {
    if (selectedId) setSemantic({ sourceId: selectedId, model, yaml: text });
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problems = validateConnectionForm(form);
    setFormProblems(problems);
    if (problems.length > 0) return;
    setReport(null);
    await run(async () => {
      const created = await api.dataSources.create(id, toCreateBody(form));
      setForm((current) => ({ ...emptyConnectionForm(), ssl_mode: current.ssl_mode }));
      setReport(created.report);
      setSelectedId(created.source.id);
      await loadSources();
    }, "Sumber data tidak dapat dibuat.");
  }

  async function retest(source: DataSource) {
    await run(async () => {
      const result = await api.dataSources.test(id, source.id);
      setReport(result);
      setNotice(result.ok ? `Koneksi ke "${source.name}" berhasil.` : "");
      await loadSources();
    }, "Koneksi tidak dapat diuji.");
  }

  async function discover(source: DataSource) {
    await run(async () => {
      const summary = await api.dataSources.discover(id, source.id);
      setNotice(`Discover "${source.name}": ${describeDiscovery(summary)}`);
    }, "Skema tidak dapat dibaca.");
  }

  async function remove(source: DataSource) {
    if (
      !window.confirm(
        `Hapus sumber data "${source.name}"? Skema dan model semantiknya ikut terhapus; riwayat pertanyaan tetap ada.`,
      )
    ) {
      return;
    }
    await run(async () => {
      await api.dataSources.remove(id, source.id);
      await loadSources();
    }, "Sumber data tidak dapat dihapus.");
  }

  async function draft(source: DataSource) {
    setYamlProblems([]);
    await run(async () => {
      try {
        const result = await api.semantic.draft(id, source.id);
        editYaml(result.yaml);
        setNotice("Draf dibuat dari skema. Tambahkan metrik, dimensi, dan sinonim, lalu simpan.");
      } catch (e) {
        setYamlProblems(parseProblems(e));
      }
    }, "Draf tidak dapat dibuat.");
  }

  async function save(source: DataSource) {
    setYamlProblems([]);
    await run(async () => {
      try {
        const saved = await api.semantic.save(id, source.id, yaml);
        setSemantic({ sourceId: source.id, model: saved, yaml: saved.yaml });
        setNotice(
          `Model semantik versi ${saved.version} aktif. Jalankan Discover lagi agar contoh nilai ikut diambil.`,
        );
      } catch (e) {
        setYamlProblems(parseProblems(e));
      }
    }, "Model tidak dapat disimpan.");
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Sumber data</h1>
        <Link href={`/workspaces/${id}`} className="text-sm text-gray-600 underline">
          Kembali ke workspace
        </Link>
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Hubungkan database PostgreSQL dengan pengguna read-only. AI Data Analyst hanya membaca tabel dan
        kolom yang tercantum di model semantik.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-3 text-sm text-green-800">
          {notice}
        </p>
      )}

      {sources === null ? (
        !error && <p className="mt-6 text-sm text-gray-500">Memuat…</p>
      ) : sources.length === 0 ? (
        <p className="mt-6 rounded border bg-white p-6 text-center text-sm text-gray-500">
          Belum ada sumber data
        </p>
      ) : (
        <table className="mt-6 w-full rounded border bg-white text-sm">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="px-3 py-2">Nama</th>
              <th className="px-3 py-2">Server</th>
              <th className="px-3 py-2">Pengguna</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => {
              const status = statusLabel(source.status);
              return (
                <tr
                  key={source.id}
                  className={`border-t align-top ${source.id === selectedId ? "bg-blue-50" : ""}`}
                >
                  <td className="px-3 py-2">
                    <button
                      onClick={() => selectSource(source.id)}
                      aria-pressed={source.id === selectedId}
                      className="underline"
                    >
                      {source.name}
                    </button>
                  </td>
                  <td className="px-3 py-2 break-all">
                    {source.host}:{source.port}/{source.database}
                  </td>
                  <td className="px-3 py-2">{source.username}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${status.className}`}>
                      <span aria-hidden="true">{status.icon} </span>
                      {status.text}
                    </span>
                    {source.status === "failed" && source.last_error && (
                      <p className="mt-1 text-xs text-red-700">{source.last_error}</p>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {canManage && (
                      <>
                        <button disabled={busy} onClick={() => void retest(source)} className="mr-3 underline">
                          Uji
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => void discover(source)}
                          className="mr-3 underline"
                        >
                          Discover
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => void remove(source)}
                          className="text-red-600 underline"
                        >
                          Hapus
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {report && report.problems.length > 0 && (
        <div role="alert" className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-sm">
          <p className="font-medium">Koneksi belum aman atau gagal:</p>
          <ul className="mt-1 list-disc pl-5">
            {report.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      {report?.ok && (
        <p role="status" className="mt-3 text-sm text-green-800">
          Koneksi berhasil{report.server_version ? ` (${report.server_version.split(" on ")[0]})` : ""}.
          Pengguna ini read-only.
        </p>
      )}

      {canManage && (
        <form onSubmit={create} className="mt-8 rounded border bg-white p-4" noValidate>
          <h2 className="text-lg font-medium">Tambah sumber data</h2>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {FIELD_LABELS.map(({ key, label, type }) => (
              <label key={key} className="text-sm">
                {label}
                <input
                  type={type ?? "text"}
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  autoComplete={key === "password" ? "new-password" : "off"}
                  className={inputClass}
                />
              </label>
            ))}
            <label className="text-sm">
              SSL
              <select
                value={form.ssl_mode}
                onChange={(e) => setForm({ ...form, ssl_mode: e.target.value })}
                className={inputClass}
              >
                {SSL_MODES.map((mode) => (
                  <option key={mode}>{mode}</option>
                ))}
              </select>
            </label>
          </div>
          {formProblems.length > 0 && (
            <ul role="alert" className="mt-3 list-disc pl-5 text-sm text-red-600">
              {formProblems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
          <button disabled={busy} className={`${buttonClass} mt-4`}>
            {busy ? "Memproses…" : "Simpan dan uji koneksi"}
          </button>
        </form>
      )}

      {selected && (
        <section className="mt-8">
          <h2 className="text-lg font-medium">Model semantik: {selected.name}</h2>
          <p className="mt-1 text-sm text-gray-600">
            {model ? `Versi aktif: ${model.version}.` : "Belum ada model aktif."}{" "}
            {canManage && !model && "Jalankan Discover, lalu buat draf dari skema."}
          </p>
          <textarea
            value={yaml}
            onChange={(e) => editYaml(e.target.value)}
            readOnly={!canManage || loaded === null}
            spellCheck={false}
            rows={24}
            aria-label="YAML model semantik"
            className="mt-2 w-full rounded border border-gray-300 p-3 font-mono text-xs"
          />
          {yamlProblems.length > 0 && (
            <div role="alert" className="mt-2 rounded border border-red-300 bg-red-50 p-3 text-sm">
              <p className="font-medium">Model belum bisa disimpan:</p>
              <ul className="mt-1 list-disc pl-5">
                {yamlProblems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </div>
          )}
          {canManage && (
            <div className="mt-3 flex gap-2">
              <button
                disabled={busy}
                onClick={() => void draft(selected)}
                className="rounded border border-gray-300 px-4 py-2 text-sm disabled:opacity-50"
              >
                Buat draf dari skema
              </button>
              <button disabled={busy || !yaml.trim()} onClick={() => void save(selected)} className={buttonClass}>
                Simpan
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
