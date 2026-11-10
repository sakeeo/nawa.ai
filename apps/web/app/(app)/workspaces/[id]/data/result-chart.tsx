"use client";

import { useEffect, useRef } from "react";
import { buildEchartsOption, chartSummary } from "@/lib/chart";
import type { ChartSpec } from "@/lib/types";

/** Draws a bar or line chart with ECharts. The library loads only when a chart is shown. */
export function ResultChart({
  spec,
  columns,
  rows,
}: {
  spec: ChartSpec;
  columns: string[];
  rows: unknown[][];
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = container.current;
    const option = buildEchartsOption(spec, columns, rows);
    if (!element || !option) return;
    let disposed = false;
    let dispose: (() => void) | undefined;
    void (async () => {
      const echarts = await import("echarts/core");
      const { BarChart, LineChart } = await import("echarts/charts");
      const { GridComponent, LegendComponent, TooltipComponent } = await import("echarts/components");
      const { CanvasRenderer } = await import("echarts/renderers");
      if (disposed) return;
      echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
      const chart = echarts.init(element);
      chart.setOption(option);
      const observer = new ResizeObserver(() => chart.resize());
      observer.observe(element);
      dispose = () => {
        observer.disconnect();
        chart.dispose();
      };
    })();
    return () => {
      disposed = true;
      dispose?.();
    };
  }, [spec, columns, rows]);

  return (
    <div
      ref={container}
      role="img"
      aria-label={chartSummary(spec, rows.length)}
      className="h-72 w-full"
    />
  );
}
