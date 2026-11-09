export type Role = "admin" | "manager" | "member" | "viewer";
export type InviteRole = Exclude<Role, "admin">;

export type User = { id: string; email: string; is_admin: boolean };
export type Membership = { workspace_id: string; role: Role };
export type Me = { user: User; memberships: Membership[] };

export type SetupStatus = { setup_required: boolean; providers: string[] };

export type Workspace = { id: string; name: string; slug: string; role: Role };
export type Member = { user_id: string; email: string; role: Role };

export type InviteCreated = {
  id: string;
  email: string;
  role: InviteRole;
  expires_at: string;
  token: string;
  accept_path: string;
};
export type InvitePreview = { email: string; workspace_name: string; role: Role };
export type InviteAccepted = { email: string; workspace_id: string; role: Role };

export type ChatResponse = {
  content: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
};

export type DocumentStatus = "queued" | "processing" | "ready" | "failed";
export type DocumentOut = {
  id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  page_count: number | null;
  created_at: string;
};
export type ChunkOut = {
  id: string;
  document_id: string;
  filename: string;
  page: number | null;
  section_path: string | null;
  heading: string | null;
  text: string;
};

export type Citation = {
  marker: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number | null;
  section_path: string | null;
};

export type ChatEvent =
  | {
      type: "meta";
      conversation_id: string;
      message_id: string;
      retrieved: number;
      reranked: boolean;
      best_similarity: number | null;
      gate: string;
    }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[]; invalid_markers: number[] }
  | { type: "refusal"; text: string }
  | {
      type: "done";
      model: string | null;
      prompt_name: string;
      prompt_version: number;
      tokens_in: number;
      tokens_out: number;
      ttft_ms: number;
      total_ms: number;
      refused: boolean;
    }
  | { type: "error"; code: string; message: string };

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  last_message_at: string;
};

export type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  refused: boolean;
  created_at: string;
  citations: Citation[];
  feedback: 1 | -1 | null;
};
export type ConversationDetail = { id: string; title: string; messages: StoredMessage[] };
