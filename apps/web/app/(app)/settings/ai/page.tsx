"use client";

import { type FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";

export default function AiSettingsPage() {
  const { user } = useMe();
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.post<ChatResponse>("/llm/chat", { message: form.get("message") }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "LLM test failed");
    } finally {
      setBusy(false);
    }
  }

  if (!user.is_admin) {
    return <p className="text-sm text-gray-600">Only instance admins can use this page.</p>;
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold">AI provider test</h1>
      <p className="mt-1 text-sm text-gray-600">
        Sends one message through the LLM gateway. The call is traced in Langfuse when it is
        enabled.
      </p>
      <form onSubmit={test} className="mt-4 flex gap-2">
        <input name="message" required defaultValue="Hello NAWA.AI" className={`${inputClass} mt-0`} />
        <button disabled={busy} className={buttonClass}>
          {busy ? "Calling…" : "Send"}
        </button>
      </form>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {result && (
        <dl className="mt-4 space-y-1 rounded border bg-white p-4 text-sm">
          <dt className="font-medium">Reply</dt>
          <dd>{result.content}</dd>
          <dt className="mt-2 font-medium">Model</dt>
          <dd>{result.model}</dd>
          <dt className="mt-2 font-medium">Tokens</dt>
          <dd>
            {result.prompt_tokens} in / {result.completion_tokens} out, cost $
            {result.cost_usd.toFixed(6)}
          </dd>
        </dl>
      )}
    </div>
  );
}
