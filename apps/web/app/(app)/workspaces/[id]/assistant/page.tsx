"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Citation, ConversationSummary } from "@/lib/types";
import { buttonClass } from "@/lib/ui";
import { CitationPanel } from "./citation-panel";
import type { ChatMessage } from "./chat-types";
import { MessageView } from "./message-view";

const MAX_CHARS = 2000;
let counter = 0;
const newKey = () => `m${++counter}`;

export default function AssistantPage() {
  const { id } = useParams<{ id: string }>();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [notice, setNotice] = useState("");
  const [opened, setOpened] = useState<Citation | null>(null);
  const abort = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(() => {
    api
      .listConversations(id)
      .then(setConversations)
      .catch(() => setNotice("Daftar percakapan tidak dapat dimuat."));
  }, [id]);
  useEffect(loadConversations, [loadConversations]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  const patchLast = (patch: (m: ChatMessage) => ChatMessage) =>
    setMessages((all) => all.map((m, i) => (i === all.length - 1 ? patch(m) : m)));

  async function ask(question: string, conversation: string | null) {
    setNotice("");
    setOpened(null);
    setStreaming(true);
    setMessages((all) => [
      ...all,
      { key: newKey(), serverId: null, role: "user", content: question, status: "done", refused: false, citations: [], invalidMarkers: [], feedback: null },
      { key: newKey(), serverId: null, role: "assistant", content: "", status: "streaming", refused: false, citations: [], invalidMarkers: [], feedback: null },
    ]);
    const controller = new AbortController();
    abort.current = controller;
    let failed = false;
    try {
      for await (const event of api.streamChat(id, question, conversation, controller.signal)) {
        switch (event.type) {
          case "meta":
            setConversationId(event.conversation_id);
            patchLast((m) => ({ ...m, serverId: event.message_id }));
            break;
          case "token":
            patchLast((m) => ({ ...m, content: m.content + event.text }));
            break;
          case "refusal":
            patchLast((m) => ({ ...m, content: event.text, refused: true }));
            break;
          case "citations":
            patchLast((m) => ({ ...m, citations: event.citations, invalidMarkers: event.invalid_markers }));
            break;
          case "done":
            patchLast((m) => ({ ...m, status: "done" }));
            break;
          case "error":
            failed = true;
            patchLast((m) => ({ ...m, status: "error", content: "", citations: [], error: event.message }));
            break;
        }
      }
      patchLast((m) => (m.status === "streaming" ? { ...m, status: "stopped" } : m));
    } catch (e) {
      if (controller.signal.aborted) {
        patchLast((m) => (m.status === "streaming" ? { ...m, status: "stopped" } : m));
      } else {
        failed = true;
        patchLast((m) => ({
          ...m,
          status: "error",
          content: "",
          citations: [],
          error: e instanceof ApiError ? e.message : "Koneksi terputus. Coba lagi.",
        }));
      }
    } finally {
      setStreaming(false);
      abort.current = null;
      if (!failed) loadConversations();
    }
  }

  function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    void ask(question, conversationId);
  }

  function retry() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || streaming) return;
    // Drop the failed exchange locally; the server kept the question, a retry asks again.
    setMessages((all) => all.slice(0, -2));
    void ask(lastUser.content, conversationId);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  async function open(conversation: string) {
    if (streaming) return;
    setNotice("");
    setOpened(null);
    try {
      const detail = await api.getConversation(id, conversation);
      setConversationId(detail.id);
      setMessages(
        detail.messages.map((m) => ({
          key: newKey(),
          serverId: m.id,
          role: m.role,
          content: m.content,
          status: "done",
          refused: m.refused,
          citations: m.citations,
          invalidMarkers: [],
          feedback: m.feedback,
        })),
      );
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Percakapan tidak dapat dimuat.");
    }
  }

  function newConversation() {
    if (streaming) return;
    setConversationId(null);
    setMessages([]);
    setOpened(null);
    setNotice("");
  }

  async function feedback(index: number, value: 1 | -1, comment?: string) {
    const target = messages[index];
    if (!target.serverId) return;
    const previous = target.feedback;
    const set = (v: 1 | -1 | null) =>
      setMessages((all) => all.map((m, i) => (i === index ? { ...m, feedback: v } : m)));
    set(value);
    try {
      await api.sendFeedback(id, target.serverId, value, comment);
    } catch (e) {
      set(previous);
      setNotice(e instanceof ApiError ? e.message : "Feedback tidak dapat disimpan.");
    }
  }

  function closePanel() {
    setOpened(null);
    trigger.current?.focus();
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">AI Assistant</h1>
        <Link href={`/workspaces/${id}`} className="text-sm text-gray-600 underline">
          Kembali ke workspace
        </Link>
      </div>
      {notice && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {notice}
        </p>
      )}
      <div className="mt-4 flex gap-4">
        <nav aria-label="Percakapan" className="hidden w-48 shrink-0 md:block">
          <button onClick={newConversation} disabled={streaming} className={`${buttonClass} w-full`}>
            Percakapan baru
          </button>
          <ul className="mt-3 space-y-1 text-sm">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => void open(c.id)}
                  aria-current={c.id === conversationId ? "true" : undefined}
                  className={`w-full rounded px-2 py-1 text-left break-words ${c.id === conversationId ? "bg-gray-200 font-medium" : "hover:bg-gray-100"}`}
                >
                  {c.title}
                </button>
              </li>
            ))}
            {conversations.length === 0 && <li className="px-2 text-gray-500">Belum ada percakapan</li>}
          </ul>
        </nav>

        <section className="min-w-0 flex-1">
          <div
            role="log"
            aria-live="polite"
            aria-busy={streaming}
            aria-label="Percakapan"
            className="h-[28rem] space-y-3 overflow-y-auto rounded border bg-gray-50 p-4"
          >
            {messages.length === 0 && (
              <p className="text-sm text-gray-500">
                Tanyakan sesuatu tentang dokumen perusahaan, misalnya prosedur komplain atau kebijakan cuti.
              </p>
            )}
            {messages.map((m, index) => (
              <MessageView
                key={m.key}
                message={m}
                onOpenCitation={(citation, el) => {
                  trigger.current = el;
                  setOpened(citation);
                }}
                onFeedback={(value, comment) => void feedback(index, value, comment)}
                onRetry={retry}
              />
            ))}
            <div ref={bottom} />
          </div>
          <div className="mt-3 flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={onKeyDown}
              disabled={streaming}
              rows={2}
              maxLength={MAX_CHARS}
              aria-label="Pertanyaan"
              placeholder="Tulis pertanyaan… (Enter kirim, Shift+Enter baris baru)"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
            {streaming ? (
              <button onClick={() => abort.current?.abort()} className={`${buttonClass} bg-red-700`}>
                Berhenti
              </button>
            ) : (
              <button onClick={send} disabled={!input.trim()} className={buttonClass}>
                Kirim
              </button>
            )}
          </div>
          <p className="mt-1 text-right text-xs text-gray-500">
            {input.length}/{MAX_CHARS}
          </p>
        </section>

        {opened && (
          <CitationPanel
            workspaceId={id}
            chunkId={opened.chunk_id}
            marker={opened.marker}
            onClose={closePanel}
          />
        )}
      </div>
    </div>
  );
}
