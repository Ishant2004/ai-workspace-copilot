import { useEffect, useRef, useState } from "react";
import {
  streamThreadChat,
  listThreads,
  createThread,
  getThreadMessages,
  deleteThread,
  type ChatMode,
  type Message,
  type SearchHit,
  type Thread,
} from "../services/api";

// One agent tool step (Phase 11): a tool call and, once run, its result.
type Step = { name: string; args: Record<string, unknown>; result?: string };

// A chat message plus, for RAG answers, the grounding docs and, for agent
// answers, the tool steps taken to reach it.
type DisplayMessage = Message & { sources?: SearchHit[]; steps?: Step[] };

// Phase 0: streaming chat. Phase 4: RAG grounding. Phase 9: persistent threads.
// Phase 11: an "Agent" mode that lets the model call tools mid-conversation.
export default function Chat() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<ChatMode>("chat");
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

    let threadId = activeId;
    if (threadId == null) {
      const t = await createThread();
      threadId = t.id;
      setActiveId(t.id);
    }

    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "", steps: [] },
    ]);
    setInput("");

    const updateAssistant = (fn: (m: DisplayMessage) => DisplayMessage) => {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = fn(copy[copy.length - 1]);
        return copy;
      });
    };

    await streamThreadChat(threadId, text, mode, {
      onChunk: (extra) =>
        updateAssistant((m) => ({ ...m, content: m.content + extra })),
      onSources: (sources) => updateAssistant((m) => ({ ...m, sources })),
      onToolCall: (name, args) =>
        updateAssistant((m) => ({
          ...m,
          steps: [...(m.steps ?? []), { name, args }],
        })),
      onToolResult: (name, result) =>
        updateAssistant((m) => {
          // Attach the result to the most recent matching, unresolved call.
          const steps = [...(m.steps ?? [])];
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].name === name && steps[i].result === undefined) {
              steps[i] = { ...steps[i], result };
              break;
            }
          }
          return { ...m, steps };
        }),
      onDone: () => {
        setBusy(false);
        refreshThreads();
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

  const placeholder =
    mode === "rag"
      ? "Ask about your stored documents."
      : mode === "agent"
        ? "Ask something — the agent can search docs, do math, tell the time."
        : "Ask me anything to get started.";

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
          {dbError && <p className="px-2 text-xs text-amber-700">{dbError}</p>}
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
            <p className="mt-20 text-center text-neutral-400">{placeholder}</p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={m.role === "user" ? "text-right" : "text-left"}
            >
              {/* Agent tool steps appear above the answer. */}
              {m.steps && m.steps.length > 0 && <Steps steps={m.steps} />}
              {(m.content || m.role === "user" || busy) && (
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
              )}
              {m.sources && m.sources.length > 0 && (
                <Sources hits={m.sources} />
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </main>

        <footer className="border-t border-neutral-200 bg-white p-4">
          <div className="mx-auto w-full max-w-2xl space-y-2">
            {/* Mode selector: plain chat, RAG grounding, or tool-using agent. */}
            <div className="flex gap-1 rounded-lg bg-neutral-100 p-1 text-xs">
              {(["chat", "rag", "agent"] as ChatMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={
                    "rounded-md px-3 py-1 font-medium capitalize transition " +
                    (mode === m
                      ? "bg-white text-neutral-900 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-800")
                  }
                >
                  {m}
                </button>
              ))}
            </div>
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

// Agent tool steps: each call + its result, shown as a compact timeline above
// the final answer (Phase 11).
function Steps({ steps }: { steps: Step[] }) {
  return (
    <div className="mb-1 space-y-1">
      {steps.map((s, i) => (
        <div
          key={i}
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs"
        >
          <span className="font-medium text-amber-800">🔧 {s.name}</span>
          <span className="font-mono text-amber-900">
            ({JSON.stringify(s.args)})
          </span>
          {s.result !== undefined && (
            <div className="mt-0.5 line-clamp-2 font-mono text-neutral-500">
              → {s.result}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// The little "Sources" strip under a RAG answer.
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
