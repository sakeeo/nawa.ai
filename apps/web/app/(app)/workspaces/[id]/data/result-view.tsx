"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { describeAnomaly } from "@/lib/anomaly";
import { kpiValue } from "@/lib/chart";
import { formatCell, truncatedNotice } from "@/lib/result-table";
import type { AskResponse } from "@/lib/types";
import { DataTable } from "./data-table";
import { InsightPanel } from "./insight-panel";
import { ResultChart } from "./result-chart";
import { SqlBlock } from "./sql-block";

function Meta({ result }: { result: AskResponse }) {
  const parts = [
    `${formatCell(result.row_count)} baris`,
    `${result.duration_ms} ms`,
    result.attempts > 1 ? `${result.attempts} percobaan` : "1 percobaan",
  ];
  if (result.linked_tables.length > 0) parts.push(`konteks tabel: ${result.linked_tables.join(", ")}`);
  return <p className="text-xs text-gray-600">{parts.join(" · ")}</p>;
}

function Feedback({ workspaceId, queryId }: { workspaceId: string; queryId: string }) {
  const [value, setValue] = useState<1 | -1 | null>(null);
  const [failed, setFailed] = useState(false);

  async function send(next: 1 | -1) {
    setFailed(false);
    try {
      await api.data.feedback(workspaceId, queryId, next);
      setValue(next);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label="Beri penilaian jawaban">
      <span className="text-gray-600">Jawaban ini membantu?</span>
      {([1, -1] as const).map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          aria-label={option === 1 ? "Membantu" : "Kurang tepat"}
          onClick={() => void send(option)}
          className={`rounded border px-2 py-1 ${value === option ? "border-gray-900 bg-gray-100" : "border-gray-300"}`}
        >
          <span aria-hidden="true">{option === 1 ? "👍" : "👎"}</span>
        </button>
      ))}
      {failed && <span className="text-xs text-red-600">Penilaian tidak tersimpan.</span>}
    </div>
  );
}

export function ResultView({ workspaceId, result }: { workspaceId: string; result: AskResponse }) {
  if (result.status === "blocked") {
    return (
      <div role="alert" className="rounded border border-red-300 bg-red-50 p-4 text-sm">
        <p className="font-medium text-red-800">Pertanyaan ini diblokir demi keamanan data.</p>
        <p className="mt-1 text-red-700">{result.blocked_reason}</p>
        <p className="mt-2 text-xs text-gray-700">
          Hanya satu query baca (SELECT) atas tabel yang terdaftar di model semantik yang diizinkan.
        </p>
      </div>
    );
  }
  if (result.status === "clarification") {
    return (
      <div role="status" className="rounded border border-blue-200 bg-blue-50 p-4 text-sm">
        <p className="font-medium">Perlu penjelasan lebih lanjut</p>
        <p className="mt-1">{result.clarification}</p>
      </div>
    );
  }
  if (result.status === "error") {
    return (
      <div className="space-y-3">
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-4 text-sm">
          <p className="font-medium text-red-800">
            Query tidak dapat dijalankan setelah {result.attempts} percobaan.
          </p>
          {result.error && <p className="mt-1 text-red-700">{result.error}</p>}
        </div>
        {result.sql && <SqlBlock sql={result.sql} assumptions={result.assumptions} />}
      </div>
    );
  }

  const chart = result.chart;
  const kpi = chart ? kpiValue(chart, result.columns, result.rows) : null;
  const notice = truncatedNotice(result.row_count, result.truncated);
  return (
    <div className="space-y-4">
      <Meta result={result} />
      {kpi && (
        <div className="rounded border bg-white p-6 text-center">
          <p className="text-4xl font-semibold tabular-nums">{kpi.text}</p>
          <p className="mt-1 text-sm text-gray-600">{kpi.label}</p>
        </div>
      )}
      {chart && (chart.kind === "bar" || chart.kind === "line") && (
        <div className="rounded border bg-white p-3">
          <p className="text-sm font-medium">{chart.title}</p>
          <ResultChart spec={chart} columns={result.columns} rows={result.rows} />
        </div>
      )}
      {result.anomalies.length > 0 && (
        <div role="note" className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-medium">Perlu diperhatikan</p>
          <ul className="mt-1 list-disc pl-5">
            {result.anomalies.map((anomaly) => (
              <li key={anomaly.label}>{describeAnomaly(anomaly)}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-gray-600">
            Dihitung otomatis dari hasil query (z-score), bukan oleh model.
          </p>
        </div>
      )}
      <DataTable columns={result.columns} rows={result.rows} />
      {notice && <p className="text-xs text-amber-800">{notice}</p>}
      {result.sql && <SqlBlock sql={result.sql} assumptions={result.assumptions} />}
      {result.row_count > 0 && <InsightPanel workspaceId={workspaceId} queryId={result.query_id} />}
      <Feedback workspaceId={workspaceId} queryId={result.query_id} />
    </div>
  );
}
