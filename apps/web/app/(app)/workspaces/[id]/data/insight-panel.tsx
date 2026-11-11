"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type State = { kind: "loading" } | { kind: "error" } | { kind: "ok"; text: string; grounded: boolean };

/** Fetches the narrative for one query. The server only keeps numbers that are in the result. */
export function InsightPanel({ workspaceId, queryId }: { workspaceId: string; queryId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    api.data
      .insight(workspaceId, queryId)
      .then((read) => active && setState({ kind: "ok", text: read.text, grounded: read.grounded }))
      .catch(() => active && setState({ kind: "error" }));
    return () => {
      active = false;
    };
  }, [workspaceId, queryId]);

  return (
    <section aria-label="Ringkasan" className="rounded border bg-white p-4 text-sm">
      <h3 className="font-medium">Ringkasan</h3>
      {state.kind === "loading" && (
        <div aria-busy="true" className="mt-2 space-y-2">
          <div className="h-3 w-3/4 animate-pulse rounded bg-gray-200" />
          <div className="h-3 w-1/2 animate-pulse rounded bg-gray-200" />
        </div>
      )}
      {state.kind === "error" && (
        <p className="mt-2 text-gray-500">Ringkasan tidak tersedia. Tabel dan grafik di atas tetap berlaku.</p>
      )}
      {state.kind === "ok" && (
        <>
          <p className="mt-2">{state.text}</p>
          {!state.grounded && (
            <p className="mt-2 text-xs text-gray-600">
              Narasi dari model tidak lolos verifikasi angka, jadi yang ditampilkan adalah ringkasan baku
              dari hasil query.
            </p>
          )}
        </>
      )}
    </section>
  );
}
