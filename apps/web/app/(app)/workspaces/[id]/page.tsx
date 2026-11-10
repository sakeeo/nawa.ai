"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { InviteCreated, Member, Role, Workspace } from "@/lib/types";
import { buttonClass, inputClass } from "@/lib/ui";
import { useMe } from "@/lib/user-context";

const ROLES = ["manager", "member", "viewer"] as const;

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useMe();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [invite, setInvite] = useState<InviteCreated | null>(null);
  const [error, setError] = useState("");

  const canAdmin = user.is_admin || workspace?.role === "admin";
  const fail = (e: unknown, fallback: string) => setError(e instanceof ApiError ? e.message : fallback);

  const load = useCallback(() => {
    const failLoad = (e: unknown, fallback: string) =>
      setError(e instanceof ApiError ? e.message : fallback);
    api
      .get<Workspace>(`/workspaces/${id}`)
      .then(setWorkspace)
      .catch((e) => failLoad(e, "Workspace not found"));
    api
      .get<Member[]>(`/workspaces/${id}/members`)
      .then(setMembers)
      .catch((e) => failLoad(e, "Could not load members"));
  }, [id]);
  useEffect(load, [load]);

  async function changeRole(userId: string, role: Role) {
    setError("");
    try {
      await api.patch(`/workspaces/${id}/members/${userId}`, { role });
      load();
    } catch (e) {
      fail(e, "Could not change role");
    }
  }

  async function remove(userId: string) {
    setError("");
    try {
      await api.delete(`/workspaces/${id}/members/${userId}`);
      load();
    } catch (e) {
      fail(e, "Could not remove member");
    }
  }

  async function sendInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setError("");
    try {
      const created = await api.post<InviteCreated>(`/workspaces/${id}/invites`, {
        email: form.get("email"),
        role: form.get("role"),
      });
      setInvite(created);
      formElement.reset();
    } catch (e) {
      fail(e, "Could not create invitation");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold">{workspace?.name ?? "Workspace"}</h1>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <nav className="mt-3 flex gap-4 text-sm">
        <Link href={`/workspaces/${id}/knowledge`} className="underline">
          Knowledge
        </Link>
        <Link href={`/workspaces/${id}/assistant`} className="underline">
          AI Assistant
        </Link>
        <Link href={`/workspaces/${id}/data`} className="underline">
          Tanya data
        </Link>
        <Link href={`/workspaces/${id}/data/sources`} className="underline">
          Sumber data
        </Link>
      </nav>

      <h2 className="mt-6 text-lg font-medium">Members</h2>
      <table className="mt-2 w-full rounded border bg-white text-sm">
        <thead className="text-left text-gray-500">
          <tr>
            <th className="px-4 py-2">Email</th>
            <th className="px-4 py-2">Role</th>
            {canAdmin && <th className="px-4 py-2" />}
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id} className="border-t">
              <td className="px-4 py-2">{m.email}</td>
              <td className="px-4 py-2">
                {canAdmin && m.role !== "admin" ? (
                  <select value={m.role} onChange={(e) => changeRole(m.user_id, e.target.value as Role)}>
                    {ROLES.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                ) : (
                  m.role
                )}
              </td>
              {canAdmin && (
                <td className="px-4 py-2 text-right">
                  {m.user_id !== user.id && (
                    <button onClick={() => remove(m.user_id)} className="text-red-600 underline">
                      Remove
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {canAdmin && (
        <>
          <h2 className="mt-8 text-lg font-medium">Invite a user</h2>
          <form onSubmit={sendInvite} className="mt-2 flex gap-2">
            <input
              name="email"
              type="email"
              required
              placeholder="email@company.com"
              className={`${inputClass} mt-0`}
            />
            <select name="role" defaultValue="member" className="rounded border px-3 py-2">
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <button className={buttonClass}>Create invitation</button>
          </form>
          {invite && (
            <div className="mt-3 rounded border border-green-300 bg-green-50 p-3 text-sm">
              <p>
                Invitation for <strong>{invite.email}</strong>. Share this link once; it is not shown
                again:
              </p>
              <code className="mt-1 block break-all">{`${window.location.origin}${invite.accept_path}`}</code>
            </div>
          )}
        </>
      )}
    </div>
  );
}
