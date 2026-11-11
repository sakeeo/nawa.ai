import { describe, expect, it } from "vitest";
import {
  SERIES_COLORS,
  buildEchartsOption,
  chartSummary,
  formatNumber,
  kpiValue,
} from "@/lib/chart";
import type { ChartSpec } from "@/lib/types";

const bar: ChartSpec = { kind: "bar", x: "outlet", y: ["revenue"], title: "revenue per outlet" };
const columns = ["outlet", "revenue"];
const rows: unknown[][] = [
  ["Bandung", 287],
  ["Jakarta", 273],
  ["Medan", 260],
];

type Series = { name: string; type: string; data: (number | null)[]; itemStyle?: unknown };

function seriesOf(option: ReturnType<typeof buildEchartsOption>): Series[] {
  return (option as unknown as { series: Series[] }).series;
}

describe("formatNumber", () => {
  it("uses Indonesian separators and at most two decimals", () => {
    expect(formatNumber(1234567.5)).toBe("1.234.567,5");
    expect(formatNumber(0.126)).toBe("0,13");
    expect(formatNumber(42)).toBe("42");
    expect(formatNumber(-1500)).toBe("-1.500");
  });
});

describe("buildEchartsOption", () => {
  it("builds a bar chart with the categories and one series", () => {
    const option = buildEchartsOption(bar, columns, rows) as unknown as {
      xAxis: { type: string; data: string[] };
      legend?: unknown;
    };
    expect(option.xAxis).toMatchObject({ type: "category", data: ["Bandung", "Jakarta", "Medan"] });
    const [series] = seriesOf(option as never);
    expect(series).toMatchObject({ name: "revenue", type: "bar", data: [287, 273, 260] });
    expect(option.legend).toBeUndefined();
  });

  it("adds a legend and uses the palette in fixed order for several series", () => {
    const spec: ChartSpec = { ...bar, y: ["revenue", "profit"] };
    const option = buildEchartsOption(spec, ["outlet", "revenue", "profit"], [
      ["A", 10, 4],
      ["B", 12, 5],
    ]) as unknown as { legend: { data: string[] }; color: string[] };
    expect(option.legend.data).toEqual(["revenue", "profit"]);
    expect(option.color.slice(0, 2)).toEqual([SERIES_COLORS[0], SERIES_COLORS[1]]);
  });

  it("builds a line chart over dates, shortening ISO timestamps", () => {
    const spec: ChartSpec = { kind: "line", x: "month", y: ["revenue"], title: "revenue per month" };
    const option = buildEchartsOption(spec, ["month", "revenue"], [
      ["2025-06-01T00:00:00", 100],
      ["2025-07-01T00:00:00", 120],
    ]) as unknown as { xAxis: { data: string[] } };
    expect(option.xAxis.data).toEqual(["2025-06-01", "2025-07-01"]);
    expect(seriesOf(option as never)[0]).toMatchObject({ type: "line", data: [100, 120] });
  });

  it("keeps gaps instead of inventing numbers", () => {
    const option = buildEchartsOption(bar, columns, [
      ["A", 5],
      ["B", null],
      ["C", "n/a"],
    ]);
    expect(seriesOf(option)[0].data).toEqual([5, null, null]);
  });

  it("labels a missing category", () => {
    const option = buildEchartsOption(bar, columns, [[null, 1]]) as unknown as {
      xAxis: { data: string[] };
    };
    expect(option.xAxis.data).toEqual(["—"]);
  });

  it("returns null when there is nothing to draw", () => {
    expect(buildEchartsOption({ kind: "table", x: null, y: [], title: "" }, columns, rows)).toBeNull();
    expect(buildEchartsOption({ kind: "kpi", x: null, y: ["revenue"], title: "" }, columns, rows)).toBeNull();
    expect(buildEchartsOption(bar, columns, [])).toBeNull();
    expect(buildEchartsOption({ ...bar, x: "missing" }, columns, rows)).toBeNull();
    expect(buildEchartsOption({ ...bar, y: ["missing"] }, columns, rows)).toBeNull();
  });

  it("rounds the data end of bars and keeps the baseline at zero", () => {
    const option = buildEchartsOption(bar, columns, rows) as unknown as { yAxis: { min?: number } };
    expect(seriesOf(option as never)[0].itemStyle).toMatchObject({ borderRadius: [4, 4, 0, 0] });
    expect(option.yAxis.min).toBe(0);
  });
});

describe("kpiValue", () => {
  const kpi: ChartSpec = { kind: "kpi", x: null, y: ["total"], title: "total" };
  it("formats the single number with its label", () => {
    expect(kpiValue(kpi, ["total"], [[1234567.5]])).toEqual({ label: "total", text: "1.234.567,5" });
  });
  it("finds the column by name even when a label column comes first", () => {
    expect(kpiValue(kpi, ["outlet", "total"], [["Bandung", 9]])).toEqual({ label: "total", text: "9" });
  });
  it("is null for a missing value or a non-kpi chart", () => {
    expect(kpiValue(kpi, ["total"], [[null]])).toBeNull();
    expect(kpiValue(bar, columns, rows)).toBeNull();
    expect(kpiValue(kpi, ["total"], [])).toBeNull();
  });
});

describe("chartSummary", () => {
  it("describes the chart for screen readers", () => {
    expect(chartSummary(bar, rows.length)).toMatch(/batang.*revenue per outlet.*3 baris/i);
    expect(chartSummary({ ...bar, kind: "line" }, 5)).toMatch(/garis.*5 baris/i);
  });
});
