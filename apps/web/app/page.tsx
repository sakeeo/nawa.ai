"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    api
      .get<SetupStatus>("/setup/status")
      .then((s) => router.replace(s.setup_required ? "/setup" : "/workspaces"))
      .catch(() => router.replace("/login"));
  }, [router]);
  return <p className="p-8 text-sm text-gray-500">Loading…</p>;
}
