import { describe, expect, it, vi } from "vitest";
import { parseSse } from "@/lib/sse";
import type { ChatEvent } from "@/lib/types";

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<ChatEvent[]> {
  const out: ChatEvent[] = [];
  for await (const event of parseSse(stream)) out.push(event);
  return out;
}

const token = (text: string) => `data: ${JSON.stringify({ type: "token", text })}\n\n`;

describe("parseSse", () => {
  it("parses several events from one chunk", async () => {
    const events = await collect(streamOf([token("a") + token("b")]));
    expect(events).toEqual([
      { type: "token", text: "a" },
      { type: "token", text: "b" },
    ]);
  });

  it("joins an event split across chunks", async () => {
    const full = token("halo");
    const events = await collect(streamOf([full.slice(0, 10), full.slice(10, 25), full.slice(25)]));
    expect(events).toEqual([{ type: "token", text: "halo" }]);
  });

  it("handles a multi-byte character split across chunks", async () => {
    const bytes = new TextEncoder().encode(token("café ✓ 日本"));
    const cut = bytes.indexOf(0xc3) + 1; // between the two bytes of "é"
    const events = await collect(streamOf([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events).toEqual([{ type: "token", text: "café ✓ 日本" }]);
  });

  it("does not emit a trailing event without its blank line", async () => {
    const events = await collect(streamOf([token("a"), `data: ${JSON.stringify({ type: "token", text: "b" })}\n`]));
    expect(events).toEqual([{ type: "token", text: "a" }]);
  });

  it("skips malformed JSON with a warning and keeps going", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const events = await collect(streamOf(["data: {not json\n\n", token("ok")]));
    expect(events).toEqual([{ type: "token", text: "ok" }]);
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });

  it("ignores comments and heartbeats and supports CRLF", async () => {
    const events = await collect(
      streamOf([": heartbeat\n\n", token("x").replace(/\n/g, "\r\n"), ":keep-alive\n\n"]),
    );
    expect(events).toEqual([{ type: "token", text: "x" }]);
  });

  it("ends cleanly on an empty stream", async () => {
    expect(await collect(streamOf([]))).toEqual([]);
  });
});
