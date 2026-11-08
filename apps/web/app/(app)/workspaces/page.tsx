"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function WorkspacesPage() {
  const { user } = useMe();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .get<Workspace[]>("/workspaces")
      .then(setWorkspaces)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load workspaces"));
  }, []);
  useEffect(load, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const name = String(new FormData(formElement).get("name") ?? "").trim();
    setError("");
    try {
      await api.post("/workspaces", { name, slug: slugify(name) });
      formElement.reset();
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create workspace");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold">Workspaces</h1>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <ul className="mt-4 divide-y rounded border bg-white">
        {workspaces.map((w) => (
          <li key={w.id} className="flex items-center justify-between px-4 py-3">
            <Link href={`/workspaces/${w.id}`} className="font-medium underline">
              {w.name}
            </Link>
            <span className="text-xs text-gray-500">{w.role}</span>
          </li>
        ))}
        {workspaces.length === 0 && <li className="px-4 py-3 text-sm text-gray-500">No workspaces yet.</li>}
      </ul>
      {user.is_admin && (
        <form onSubmit={create} className="mt-6 flex gap-2">
          <input name="name" required placeholder="New workspace name" className={`${inputClass} mt-0`} />
          <button className={buttonClass}>Create</button>
        </form>
      )}
    </div>
  );
}
