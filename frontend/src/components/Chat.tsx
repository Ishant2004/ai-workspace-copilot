import { useEffect, useRef, useState } from "react";
import {
  streamChat,
  streamRag,
  type Message,
  type SearchHit,
} from "../services/api";

// A chat message plus, for RAG answers, the documents it was grounded in.
type DisplayMessage = Message & { sources?: SearchHit[] };

// Phase 0: streaming chat with Gemini.
// Phase 4: an optional "RAG" toggle grounds answers in the stored documents.
export default function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Keep the newest message in view as tokens stream in.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;

    // Optimistically add the user's message plus an empty assistant message
    // that we'll fill in as the stream arrives.
    const history: DisplayMessage[] = [
      ...messages,
      { role: "user", content: text },
    ];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setBusy(true);

    const updateAssistant = (fn: (m: DisplayMessage) => DisplayMessage) => {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = fn(copy[copy.length - 1]);
        return copy;
      });
    };

    // The backend only wants {role, content}; strip any UI-only fields.
    const apiMessages: Message[] = history.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const handlers = {
      onChunk: (extra: string) =>
        updateAssistant((m) => ({ ...m, content: m.content + extra })),
      onSources: (sources: SearchHit[]) =>
        updateAssistant((m) => ({ ...m, sources })),
      onDone: () => setBusy(false),
      onError: (msg: string) => {
        updateAssistant((m) => ({
          ...m,
          content: m.content + `\n\n[error] ${msg}`,
        }));
        setBusy(false);
      },
    };

    await (useRag ? streamRag : streamChat)(apiMessages, handlers);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex h-full flex-col">
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="mt-20 text-center text-neutral-400">
            {useRag
              ? "Ask about your stored documents."
              : "Ask me anything to get started."}
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={m.role === "user" ? "text-right" : "text-left"}
          >
            <div
              className={
                "inline-block max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm " +
                (m.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-white text-neutral-900 shadow-sm ring-1 ring-neutral-200")
              }
            >
              {m.content || (busy ? "…" : "")}
            </div>
            {m.sources && m.sources.length > 0 && <Sources hits={m.sources} />}
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      <footer className="border-t border-neutral-200 bg-white p-4">
        <div className="mx-auto w-full max-w-2xl space-y-2">
          <label className="flex items-center gap-2 text-xs text-neutral-500">
            <input
              type="checkbox"
              checked={useRag}
              onChange={(e) => setUseRag(e.target.checked)}
            />
            Ground answers in my documents (RAG)
          </label>
          <div className="flex gap-2">
            <textarea
              className="flex-1 resize-none rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              rows={1}
              placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              onClick={send}
              disabled={busy || !input.trim()}
            >
              Send
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}

// The little "Sources" strip under a RAG answer, so the user can see exactly
// which documents grounded it and how relevant each was.
function Sources({ hits }: { hits: SearchHit[] }) {
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      <span className="text-xs text-neutral-400">Sources:</span>
      {hits.map((h) => (
        <span
          key={h.id}
          className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600"
          title={`${(h.similarity * 100).toFixed(1)}% match`}
        >
          [#{h.id}] {h.title || `Document ${h.id}`}
        </span>
      ))}
    </div>
  );
}
