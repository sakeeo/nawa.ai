import type { ChatEvent } from "@/lib/types";

function parseBlock(block: string): ChatEvent | null {
  const data: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "" || line.startsWith(":")) continue; // blank, comment or heartbeat
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  try {
    return JSON.parse(data.join("\n")) as ChatEvent;
  } catch {
    console.warn("Skipping malformed SSE event");
    return null;
  }
}

/**
 * Server-Sent Events from a byte stream. An event is emitted only once its blank-line
 * terminator has arrived, so chunk boundaries (even inside a multi-byte character) are safe.
 * A final event without the terminating blank line is dropped.
 */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
        end = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
