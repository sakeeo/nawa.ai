import { describe, expect, it } from "vitest";
import { splitMarkers } from "@/lib/citations";

const markers = (text: string, valid: number[]) =>
  splitMarkers(text, new Set(valid)).map((s) => (s.kind === "marker" ? `#${s.marker}` : s.text));

describe("splitMarkers", () => {
  it("turns valid markers into chips and keeps surrounding text", () => {
    expect(markers("Refund penuh [1] sesuai SOP.", [1])).toEqual(["Refund penuh ", "#1", " sesuai SOP."]);
  });

  it("hides markers that are not in the citation list", () => {
    expect(markers("A [1] B [9].", [1])).toEqual(["A ", "#1", " B ", "."]);
  });

  it("supports adjacent markers and comma lists", () => {
    expect(markers("X [1][2] Y [1, 2].", [1, 2])).toEqual(["X ", "#1", "#2", " Y ", "#1", "#2", "."]);
    expect(markers("Z [2, 7]", [2])).toEqual(["Z ", "#2"]);
  });

  it("leaves markers inside code spans and fences alone", () => {
    expect(markers("use `a[1]` then [1]", [1])).toEqual(["use ", "`a[1]`", " then ", "#1"]);
    expect(markers("```\nx[1]\n```\n[1]", [1])).toEqual(["```\nx[1]\n```", "\n", "#1"]);
  });

  it("returns plain text unchanged and handles empty input", () => {
    expect(markers("tanpa rujukan", [1])).toEqual(["tanpa rujukan"]);
    expect(markers("", [1])).toEqual([]);
  });
});
