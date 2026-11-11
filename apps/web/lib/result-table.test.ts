import { describe, expect, it } from "vitest";
import { columnIsNumeric, formatCell, truncatedNotice } from "@/lib/result-table";

describe("formatCell", () => {
  it("shows NULL as an em dash", () => {
    expect(formatCell(null)).toBe("—");
    expect(formatCell(undefined)).toBe("—");
  });
  it("localizes numbers", () => {
    expect(formatCell(1234567.891)).toBe("1.234.567,89");
    expect(formatCell(0)).toBe("0");
    expect(formatCell(-3.5)).toBe("-3,5");
  });
  it("shortens ISO timestamps to the date and leaves other text alone", () => {
    expect(formatCell("2025-08-01T00:00:00")).toBe("2025-08-01");
    expect(formatCell("2025-08-01T10:30:00")).toBe("2025-08-01 10:30");
    expect(formatCell("2025-08-01")).toBe("2025-08-01");
    expect(formatCell("Bandung")).toBe("Bandung");
    expect(formatCell("12345678901234567890.5")).toBe("12345678901234567890.5");
  });
  it("shows booleans in Indonesian and stringifies lists and objects", () => {
    expect(formatCell(true)).toBe("Ya");
    expect(formatCell(false)).toBe("Tidak");
    expect(formatCell([1, 2])).toBe("[1,2]");
    expect(formatCell({ a: 1 })).toBe('{"a":1}');
  });
});

describe("truncatedNotice", () => {
  it("only speaks when the result was cut", () => {
    expect(truncatedNotice(1000, false)).toBeNull();
    expect(truncatedNotice(1000, true)).toMatch(/1\.000 baris pertama/);
    expect(truncatedNotice(50, true)).toMatch(/50 baris pertama/);
  });
});

describe("columnIsNumeric", () => {
  it("is true when every non-null value is a number", () => {
    expect(columnIsNumeric([[1, "a"], [null, "b"], [2.5, "c"]], 0)).toBe(true);
    expect(columnIsNumeric([[1, "a"], ["x", "b"]], 0)).toBe(false);
    expect(columnIsNumeric([[null], [null]], 0)).toBe(false);
    expect(columnIsNumeric([], 0)).toBe(false);
  });
});
