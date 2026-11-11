import { formatNumber } from "@/lib/chart";
import type { Anomaly } from "@/lib/types";

/** One sentence for a point that stands out in a time series. The numbers come from the server. */
export function describeAnomaly(anomaly: Anomaly): string {
  const where = anomaly.direction === "high" ? "di atas rata-rata" : "di bawah rata-rata";
  return `${anomaly.label}: ${formatNumber(anomaly.value)}, jauh ${where} (z = ${formatNumber(anomaly.z)})`;
}
