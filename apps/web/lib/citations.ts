export type Segment = { kind: "text"; text: string } | { kind: "marker"; marker: number };

const CODE = /(```[\s\S]*?```|`[^`\n]*`)/;
const MARKER = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

function splitPlain(text: string, valid: ReadonlySet<number>, out: Segment[]) {
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0;
    if (index > last) out.push({ kind: "text", text: text.slice(last, index) });
    for (const raw of match[1].split(",")) {
      const marker = Number(raw.trim());
      if (valid.has(marker)) out.push({ kind: "marker", marker });
    }
    last = index + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
}

/**
 * Splits an answer into text and citation markers. Only markers in `valid` become chips;
 * other markers (the server reported them invalid) are dropped. Code spans are left untouched.
 */
export function splitMarkers(text: string, valid: ReadonlySet<number>): Segment[] {
  const out: Segment[] = [];
  text.split(CODE).forEach((part, index) => {
    if (index % 2 === 1) out.push({ kind: "text", text: part });
    else if (part) splitPlain(part, valid, out);
  });
  return out;
}
