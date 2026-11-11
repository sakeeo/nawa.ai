import type { EChartsOption } from "echarts";
import type { ChartSpec } from "@/lib/types";

/** Categorical palette of docs/design-system.md, used in this fixed order and never cycled. */
export const SERIES_COLORS = [
  "#005a9c",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#6250d6",
  "#e34948",
];
const TEXT_3 = "#56657a";
const GRID = "#dde5ee";
const MISSING = "—";

const numberFormat = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 });

export function formatNumber(value: number): string {
  return numberFormat.format(value);
}

function label(value: unknown): string {
  if (value === null || value === undefined) return MISSING;
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}T/.test(text) ? text.slice(0, 10) : text;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * ECharts option for a bar or line chart, or null when there is nothing to draw (table and KPI
 * results, an empty result, or a spec naming a column that is not in the result).
 */
export function buildEchartsOption(
  spec: ChartSpec,
  columns: string[],
  rows: unknown[][],
): EChartsOption | null {
  if ((spec.kind !== "bar" && spec.kind !== "line") || rows.length === 0 || spec.x === null) {
    return null;
  }
  const xIndex = columns.indexOf(spec.x);
  const yIndexes = spec.y.map((name) => columns.indexOf(name));
  if (xIndex === -1 || spec.y.length === 0 || yIndexes.includes(-1)) return null;

  const series = spec.y.map((name, i) => ({
    name,
    type: spec.kind,
    data: rows.map((row) => numberOrNull(row[yIndexes[i]])),
    ...(spec.kind === "bar"
      ? { itemStyle: { borderRadius: [4, 4, 0, 0] }, barGap: "10%" }
      : { lineStyle: { width: 2 }, showSymbol: false, symbolSize: 8, emphasis: { focus: "series" } }),
  }));
  return {
    color: SERIES_COLORS,
    animation: false,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: spec.kind === "line" ? "cross" : "shadow" },
      valueFormatter: (value) => (typeof value === "number" ? formatNumber(value) : String(value)),
    },
    ...(spec.y.length > 1 ? { legend: { data: spec.y, textStyle: { color: TEXT_3 } } } : {}),
    grid: { left: 8, right: 16, top: spec.y.length > 1 ? 40 : 16, bottom: 8, containLabel: true },
    xAxis: {
      type: "category",
      data: rows.map((row) => label(row[xIndex])),
      axisLabel: { color: TEXT_3, fontSize: 12, hideOverlap: true },
      axisLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "value",
      ...(spec.kind === "bar" ? { min: 0 } : {}),
      axisLabel: { color: TEXT_3, fontSize: 12, formatter: (value: number) => formatNumber(value) },
      splitLine: { lineStyle: { color: GRID } },
    },
    series,
  } as EChartsOption;
}

export function kpiValue(
  spec: ChartSpec,
  columns: string[],
  rows: unknown[][],
): { label: string; text: string } | null {
  if (spec.kind !== "kpi" || rows.length === 0) return null;
  const name = spec.y[0];
  const value = rows[0][columns.indexOf(name)];
  return typeof value === "number" ? { label: name, text: formatNumber(value) } : null;
}

/** A text summary for `aria-label`: every chart is also available as the table below it. */
export function chartSummary(spec: ChartSpec, rowCount: number): string {
  const kind = spec.kind === "line" ? "Grafik garis" : "Grafik batang";
  return `${kind}: ${spec.title}, ${rowCount} baris. Datanya juga tersedia di tabel.`;
}
