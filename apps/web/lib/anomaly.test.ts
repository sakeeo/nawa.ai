import { describe, expect, it } from "vitest";
import { describeAnomaly } from "@/lib/anomaly";

describe("describeAnomaly", () => {
  it("says a high point is above the average, with the value and the z-score", () => {
    const text = describeAnomaly({ label: "2025-07-01", value: 1234567.5, z: 2.4, direction: "high" });
    expect(text).toContain("2025-07-01");
    expect(text).toContain("1.234.567,5");
    expect(text).toMatch(/di atas rata-rata/);
    expect(text).toContain("2,4");
  });

  it("says a low point is below the average", () => {
    const text = describeAnomaly({ label: "2025-08-01", value: 40, z: -2.37, direction: "low" });
    expect(text).toMatch(/di bawah rata-rata/);
    expect(text).toContain("-2,37");
  });
});
