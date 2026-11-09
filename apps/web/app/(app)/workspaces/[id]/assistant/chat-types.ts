import type { Citation } from "@/lib/types";

export type ChatMessage = {
  key: string;
  /** Server message id; set once the server announced it (needed for feedback). */
  serverId: string | null;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "done" | "error" | "stopped";
  refused: boolean;
  citations: Citation[];
  invalidMarkers: number[];
  feedback: 1 | -1 | null;
  error?: string;
};
