"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { UserProvider } from "@/lib/user-context";

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api
      .get<Me>("/auth/me")
      .then(setMe)
      .catch(() => router.replace("/login"));
  }, [router]);

  async function logout() {
    await api.post("/auth/logout");
    router.replace("/login");
  }

  if (!me) return <p className="p-8 text-sm text-gray-500">Loading…</p>;

  return (
    <UserProvider value={me}>
      <header className="flex items-center justify-between border-b bg-white px-6 py-3">
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/workspaces" className="font-semibold">
            NAWA.AI
          </Link>
          {me.user.is_admin && <Link href="/settings/ai">AI settings</Link>}
        </nav>
        <div className="flex items-center gap-3 text-sm text-gray-600">
          {me.user.email}
          <button onClick={logout} className="underline">
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl p-6">{children}</main>
    </UserProvider>
  );
}
