"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";

const PROVIDER_LABELS: Record<string, string> = {
  ollama: "Local model (Ollama) — data stays on this server",
  deepseek: "External API (DeepSeek) — development only, synthetic data",
};

export default function SetupPage() {
  const router = useRouter();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<SetupStatus>("/setup/status")
      .then((s) => (s.setup_required ? setStatus(s) : router.replace("/login")))
      .catch(() => setError("Cannot reach the API."));
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api.post("/setup", {
        setup_token: form.get("setup_token"),
        email: form.get("email"),
        password: form.get("password"),
        provider: form.get("provider"),
        load_demo_data: form.get("load_demo_data") === "on",
      });
      router.replace("/login");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }

  if (!status) {
    return <p className="p-8 text-sm text-gray-500">{error || "Loading…"}</p>;
  }

  return (
    <main className="mx-auto max-w-lg p-8">
      <h1 className="text-2xl font-semibold">Set up NAWA.AI</h1>
      <p className="mt-1 text-sm text-gray-600">Create the first administrator for this installation.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm">
          Setup token
          <input name="setup_token" required autoComplete="off" className={inputClass} />
          <span className="text-xs text-gray-500">
            Printed in the API log at start-up: <code>docker compose logs api</code>
          </span>
        </label>
        <label className="block text-sm">
          Admin email
          <input name="email" type="email" required className={inputClass} />
        </label>
        <label className="block text-sm">
          Password (at least 12 characters)
          <input name="password" type="password" minLength={12} required className={inputClass} />
        </label>
        <fieldset className="text-sm">
          <legend className="font-medium">AI provider</legend>
          {status.providers.map((provider, index) => (
            <label key={provider} className="mt-2 flex items-center gap-2">
              <input type="radio" name="provider" value={provider} defaultChecked={index === 0} />
              {PROVIDER_LABELS[provider] ?? provider}
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="load_demo_data" /> Load the Resto Noesantara demo data
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button disabled={busy} className={buttonClass}>
          {busy ? "Setting up…" : "Complete setup"}
        </button>
      </form>
    </main>
  );
}
