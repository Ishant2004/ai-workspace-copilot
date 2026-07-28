import { useEffect, useRef, useState } from "react";
import {
  streamThreadChat,
  listThreads,
  createThread,
  getThreadMessages,
  deleteThread,
  type Message,
  type SearchHit,
  type Thread,
} from "../services/api";

// A chat message plus, for RAG answers, the documents it was grounded in.
type DisplayMessage = Message & { sources?: SearchHit[] };

// Phase 0: streaming chat. Phase 4: optional RAG grounding.
// Phase 9: conversations are now persistent "threads" stored in Postgres. The
// backend remembers history, so we only send each new message; a sidebar lists
// past conversations and lets you switch between them.
export default function Chat() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [useRag, setUseRag] = useState(false);
  const [dbError, setDbError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function refreshThreads() {
    try {
      setThreads(await listThreads());
      setDbError(null);
    } catch (e) {
      setDbError(e instanceof Error ? e.message : "Failed to reach the DB");
    }
  }

  useEffect(() => {
    refreshThreads();
  }, []);

  async function openThread(id: number) {
    setActiveId(id);
    setMessages(await getThreadMessages(id));
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setInput("");
  }

  async function onDeleteThread(id: number) {
    await deleteThread(id);
    if (activeId === id) newChat();
    await refreshThreads();
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);

    // Ensure we have a thread to write to (create one lazily on first send).
    let threadId = activeId;
    if (threadId == null) {
      const t = await createThread();
      threadId = t.id;
      setActiveId(t.id);
    }

    // Optimistically show the user message + an empty assistant bubble.
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setInput("");

    const updateAssistant = (fn: (m: DisplayMessage) => DisplayMessage) => {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = fn(copy[copy.length - 1]);
        return copy;
      });
    };

    await streamThreadChat(threadId, text, useRag, {
      onChunk: (extra) =>
        updateAssistant((m) => ({ ...m, content: m.content + extra })),
      onSources: (sources) => updateAssistant((m) => ({ ...m, sources })),
      onDone: () => {
        setBusy(false);
        refreshThreads(); // pick up the auto-title / message count
      },
      onError: (msg) => {
        updateAssistant((m) => ({
          ...m,
          content: m.content + `\n\n[error] ${msg}`,
        }));
        setBusy(false);
      },
    });
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex h-full">
      {/* Sidebar: conversation list */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-neutral-200 bg-white">
        <div className="p-2">
          <button
            onClick={newChat}
            className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white"
          >
            + New chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {dbError && (
            <p className="px-2 text-xs text-amber-700">{dbError}</p>
          )}
          {threads.map((t) => (
            <div
              key={t.id}
              className={
                "group flex items-center justify-between gap-1 rounded-md px-2 py-1.5 text-sm " +
                (activeId === t.id
                  ? "bg-neutral-100 text-neutral-900"
                  : "text-neutral-600 hover:bg-neutral-50")
              }
            >
              <button
                onClick={() => openThread(t.id)}
                className="min-w-0 flex-1 truncate text-left"
                title={t.title}
              >
                {t.title}
              </button>
              <button
                onClick={() => onDeleteThread(t.id)}
                className="hidden text-xs text-neutral-400 hover:text-red-600 group-hover:block"
                title="Delete conversation"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Conversation */}
      <div className="flex min-w-0 flex-1 flex-col">
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
              {m.sources && m.sources.length > 0 && (
                <Sources hits={m.sources} />
              )}
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
    </div>
  );
}

// The little "Sources" strip under a RAG answer, so the user can see exactly
// which documents grounded it.
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
