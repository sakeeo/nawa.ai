"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      await api.post<Me>("/auth/login", { email: form.get("email"), password: form.get("password") });
      router.replace("/workspaces");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Login failed");
    }
  }

  return (
    <main className="mx-auto max-w-sm p-8">
      <h1 className="text-2xl font-semibold">Sign in to NAWA.AI</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm">
          Email
          <input name="email" type="email" required className={inputClass} />
        </label>
        <label className="block text-sm">
          Password
          <input name="password" type="password" required className={inputClass} />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className={`${buttonClass} w-full`}>Sign in</button>
      </form>
      <p className="mt-4 text-xs text-gray-500">No account? Ask your administrator for an invitation.</p>
    </main>
  );
}
