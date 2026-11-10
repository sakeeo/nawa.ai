"use client";

import { useState } from "react";

export function SqlBlock({ sql, assumptions }: { sql: string; assumptions: string[] }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false); // clipboard access can be denied; the SQL stays selectable
    }
  }

  return (
    <details className="rounded border bg-gray-50 text-sm">
      <summary className="cursor-pointer px-3 py-2 font-medium">SQL yang dijalankan</summary>
      <div className="border-t p-3">
        <pre className="overflow-x-auto text-xs whitespace-pre-wrap">{sql}</pre>
        <button type="button" onClick={() => void copy()} className="mt-2 text-xs underline">
          {copied ? "Tersalin" : "Salin SQL"}
        </button>
        {assumptions.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-medium text-gray-700">Asumsi</p>
            <ul className="mt-1 list-disc pl-5 text-xs text-gray-700">
              {assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
