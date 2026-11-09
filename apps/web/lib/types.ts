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
