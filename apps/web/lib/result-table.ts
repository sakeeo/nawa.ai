import { formatNumber } from "@/lib/chart";

const ISO_DATETIME = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/;

/** A cell as text: NULL as a dash, numbers localized, midnight timestamps as plain dates. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "Ya" : "Tidak";
  if (typeof value === "string") {
    const match = ISO_DATETIME.exec(value);
    if (match) {
      const [, date, hour, minute] = match;
      return hour === "00" && minute === "00" ? date : `${date} ${hour}:${minute}`;
    }
    return value;
  }
  return JSON.stringify(value);
}

export function truncatedNotice(rowCount: number, truncated: boolean): string | null {
  return truncated
    ? `Hasil dipotong: hanya ${formatNumber(rowCount)} baris pertama yang ditampilkan.`
    : null;
}

export function columnIsNumeric(rows: unknown[][], index: number): boolean {
  const values = rows.map((row) => row[index]).filter((v) => v !== null && v !== undefined);
  return values.length > 0 && values.every((v) => typeof v === "number");
}
