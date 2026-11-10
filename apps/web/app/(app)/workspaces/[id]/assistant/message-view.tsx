"use client";

import { useState } from "react";
import { splitMarkers } from "@/lib/citations";
import type { Citation } from "@/lib/types";
import type { ChatMessage } from "./chat-types";

function AnswerText({
  message,
  onOpen,
}: {
  message: ChatMessage;
  onOpen: (citation: Citation, trigger: HTMLElement) => void;
}) {
  if (message.status === "streaming") return <>{message.content}</>;
  const byMarker = new Map(message.citations.map((c) => [c.marker, c]));
  const segments = splitMarkers(message.content, new Set(byMarker.keys()));
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") return <span key={index}>{segment.text}</span>;
        const citation = byMarker.get(segment.marker)!;
        return (
          <button
            key={index}
            type="button"
            onClick={(e) => onOpen(citation, e.currentTarget)}
            aria-label={`Buka sumber ${segment.marker}: ${citation.filename}`}
            className="mx-0.5 rounded bg-gray-200 px-1.5 text-xs font-medium text-gray-900 hover:bg-gray-300 focus:ring-2 focus:ring-gray-500 focus:outline-none"
          >
            {segment.marker}
          </button>
        );
      })}
    </>
  );
}

function FeedbackButtons({
  message,
  onFeedback,
}: {
  message: ChatMessage;
  onFeedback: (value: 1 | -1, comment?: string) => void;
}) {
  const [commenting, setCommenting] = useState(false);
  const [comment, setComment] = useState("");
  const button = (value: 1 | -1, label: string, icon: string) => (
    <button
      type="button"
      aria-pressed={message.feedback === value}
      aria-label={label}
      onClick={() => {
        if (message.feedback !== value) onFeedback(value);
        setCommenting(value === -1);
      }}
      className={`rounded px-2 py-0.5 ${message.feedback === value ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-800 hover:bg-gray-200"}`}
    >
      {icon}
    </button>
  );
  return (
    <div className="mt-2 text-sm">
      <div className="flex gap-2">
        {button(1, "Jawaban membantu", "👍")}
        {button(-1, "Jawaban kurang membantu", "👎")}
      </div>
      {commenting && message.feedback === -1 && (
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onFeedback(-1, comment.trim());
            setCommenting(false);
          }}
        >
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            placeholder="Apa yang kurang? (opsional)"
            aria-label="Komentar feedback"
            className="w-full rounded border border-gray-300 px-2 py-1"
          />
          <button className="rounded bg-gray-900 px-3 py-1 text-white">Kirim</button>
        </form>
      )}
    </div>
  );
}

export function MessageView({
  message,
  onOpenCitation,
  onFeedback,
  onRetry,
}: {
  message: ChatMessage;
  onOpenCitation: (citation: Citation, trigger: HTMLElement) => void;
  onFeedback: (value: 1 | -1, comment?: string) => void;
  onRetry: () => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-lg bg-gray-900 px-4 py-2 text-sm whitespace-pre-wrap text-white">
          {message.content}
        </p>
      </div>
    );
  }
  if (message.status === "error") {
    return (
      <div role="alert" className="max-w-[85%] rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
        <p>{message.error ?? "Terjadi kesalahan saat menjawab."}</p>
        <button onClick={onRetry} className="mt-2 underline">
          Coba lagi
        </button>
      </div>
    );
  }
  if (message.refused) {
    return (
      <div className="max-w-[85%] rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <p className="font-medium">Informasi tidak ditemukan di dokumen</p>
        <p className="mt-1 whitespace-pre-wrap">{message.content}</p>
      </div>
    );
  }
  const waiting = message.status === "streaming" && message.content === "";
  return (
    <div className="max-w-[85%]">
      <div className="rounded-lg border bg-white px-4 py-3 text-sm whitespace-pre-wrap">
        {waiting ? (
          <span role="status" aria-label="AI sedang menjawab" className="text-gray-500">
            Menjawab…
          </span>
        ) : (
          <AnswerText message={message} onOpen={onOpenCitation} />
        )}
        {message.status === "stopped" && <p className="mt-2 text-xs text-gray-500">Dihentikan.</p>}
      </div>
      {message.status === "done" && message.serverId && (
        <FeedbackButtons message={message} onFeedback={onFeedback} />
      )}
    </div>
  );
}
