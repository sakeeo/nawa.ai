"use client";

import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { InviteAccepted, InvitePreview } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<InvitePreview>(`/invites/${token}`)
      .then(setPreview)
      .catch(() => setError("This invitation is invalid or has expired."));
  }, [token]);

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("password") ?? "");
    setError("");
    try {
      await api.post<InviteAccepted>("/invites/accept", { token, password: password || null });
      router.replace("/login");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not accept the invitation");
    }
  }

  if (!preview) return <p className="p-8 text-sm text-gray-600">{error || "Loading…"}</p>;

  return (
    <main className="mx-auto max-w-sm p-8">
      <h1 className="text-2xl font-semibold">Join {preview.workspace_name}</h1>
      <p className="mt-1 text-sm text-gray-600">
        {preview.email} will join as <strong>{preview.role}</strong>.
      </p>
      <form onSubmit={accept} className="mt-6 space-y-4">
        <label className="block text-sm">
          Choose a password (at least 12 characters, leave empty if you already have an account)
          <input name="password" type="password" minLength={12} className={inputClass} />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className={`${buttonClass} w-full`}>Accept invitation</button>
      </form>
    </main>
  );
}
