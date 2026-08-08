import { useEffect, useRef, useState } from "react";
import {
  streamThreadChat,
  listThreads,
  createThread,
  getThreadMessages,
  deleteThread,
  getProfile,
  clearProfile,
  submitFeedback,
  getFeedbackStats,
  type ChatMode,
  type Message,
  type SearchHit,
  type Thread,
  type Trace,
  type Rating,
  type FeedbackStats,
} from "../services/api";

// One agent tool step (Phase 11): a tool call and, once run, its result.
type Step = { name: string; args: Record<string, unknown>; result?: string };

// One plan step (Phase 12): a subtask, the tools it used, and its result.
type PlanStep = { task: string; result?: string; tools: Step[] };

// One team agent's contribution (Phase 16): its role and output.
type AgentTurn = { role: string; content?: string };

// A chat message plus, for RAG answers, the grounding docs; for agent answers,
// the tool steps; for plan answers, the plan; for team answers, the agents.
type DisplayMessage = Message & {
  sources?: SearchHit[];
  steps?: Step[];
  plan?: PlanStep[];
  agents?: AgentTurn[];
  trace?: Trace; // Phase 20: per-turn timing + tokens
  rating?: Rating; // Phase 23: the user's 👍/👎 on this answer
};

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
  const [facts, setFacts] = useState<string[]>([]); // Phase 13 profile memory
  const [fbStats, setFbStats] = useState<FeedbackStats | null>(null); // Phase 23
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Lets us cancel an in-flight (possibly hanging) request.
  const abortRef = useRef<AbortController | null>(null);

  // Grow the input to fit its content, up to a max height (then it scrolls).
  // Runs whenever `input` changes — including when we clear it after sending.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Phase 23: load the running satisfaction rate on mount.
  useEffect(() => {
    refreshFeedbackStats();
  }, []);

  async function refreshFeedbackStats() {
    try {
      setFbStats(await getFeedbackStats());
    } catch {
      /* feedback is non-critical; ignore failures */
    }
  }

  // Record a 👍/👎 for one answer, using the preceding user message as the
  // question. Optimistically marks the message, then refreshes the stat.
  async function rateMessage(index: number, rating: Rating, note = "") {
    const answer = messages[index]?.content ?? "";
    // The question is the most recent user message before this answer.
    let question = "";
    for (let j = index - 1; j >= 0; j--) {
      if (messages[j].role === "user") {
        question = messages[j].content;
        break;
      }
    }
    if (!answer) return;
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, rating } : m))
    );
    try {
      await submitFeedback({ threadId: activeId, question, answer, rating, note });
      await refreshFeedbackStats();
    } catch {
      /* ignore; the optimistic mark stays */
    }
  }

  async function refreshThreads() {
    try {
      setThreads(await listThreads());
      setDbError(null);
    } catch (e) {
      setDbError(e instanceof Error ? e.message : "Failed to reach the DB");
    }
  }

  async function refreshProfile() {
    try {
      setFacts(await getProfile());
    } catch {
      /* profile is best-effort; ignore errors */
    }
  }

  async function onForgetProfile() {
    await clearProfile();
    setFacts([]);
  }

  useEffect(() => {
    refreshThreads();
    refreshProfile();
  }, []);

  async function openThread(id: number) {
    setActiveId(id);
    setSidebarOpen(false); // close the drawer on mobile after picking a chat
    setMessages(await getThreadMessages(id));
  }

  function newChat() {
    setActiveId(null);
    setSidebarOpen(false);
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

    // In plan mode, tool calls belong to the current step; track which one.
    let currentStep = -1;

    const attachToolCall = (
      list: Step[],
      name: string,
      args: Record<string, unknown>
    ) => [...list, { name, args }];

    const attachToolResult = (list: Step[], result: string) => {
      const copy = [...list];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].result === undefined) {
          copy[i] = { ...copy[i], result };
          break;
        }
      }
      return copy;
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamThreadChat(
        threadId,
        text,
        mode,
        {
      onChunk: (extra) =>
        updateAssistant((m) => ({ ...m, content: m.content + extra })),
      onSources: (sources) => updateAssistant((m) => ({ ...m, sources })),
      onAgentStart: (role) =>
        updateAssistant((m) => ({
          ...m,
          agents: [...(m.agents ?? []), { role }],
        })),
      onAgentMessage: (role, content) =>
        updateAssistant((m) => {
          const agents = [...(m.agents ?? [])];
          // Fill the most recent turn for this role.
          for (let i = agents.length - 1; i >= 0; i--) {
            if (agents[i].role === role && agents[i].content === undefined) {
              agents[i] = { ...agents[i], content };
              return { ...m, agents };
            }
          }
          return { ...m, agents: [...agents, { role, content }] };
        }),
      onPlan: (steps) =>
        updateAssistant((m) => ({
          ...m,
          plan: steps.map((s) => ({ task: s.task, tools: [] })),
        })),
      onStepStart: (index) => {
        currentStep = index;
      },
      onStepResult: (index, result) =>
        updateAssistant((m) => {
          const plan = [...(m.plan ?? [])];
          if (plan[index]) plan[index] = { ...plan[index], result };
          return { ...m, plan };
        }),
      onToolCall: (name, args) => {
        // Capture the step index NOW; the state updater may run later (React
        // batching), by which time `currentStep` could have advanced.
        const idx = currentStep;
        updateAssistant((m) => {
          if (m.plan && idx >= 0 && m.plan[idx]) {
            const plan = [...m.plan];
            plan[idx] = {
              ...plan[idx],
              tools: attachToolCall(plan[idx].tools, name, args),
            };
            return { ...m, plan };
          }
          return { ...m, steps: attachToolCall(m.steps ?? [], name, args) };
        });
      },
      onToolResult: (_name, result) => {
        const idx = currentStep;
        updateAssistant((m) => {
          if (m.plan && idx >= 0 && m.plan[idx]) {
            const plan = [...m.plan];
            plan[idx] = {
              ...plan[idx],
              tools: attachToolResult(plan[idx].tools, result),
            };
            return { ...m, plan };
          }
          return { ...m, steps: attachToolResult(m.steps ?? [], result) };
        });
      },
      onTrace: (trace) => updateAssistant((m) => ({ ...m, trace })),
      onDone: () => {},
      onError: (msg) =>
        updateAssistant((m) => ({
          ...m,
          content: m.content + `\n\n[error] ${msg}`,
        })),
        },
        controller.signal
      );
    } finally {
      // Runs on normal completion AND on stop/abort: reset state and refresh
      // the sidebar (title/message counts).
      setBusy(false);
      abortRef.current = null;
      refreshThreads();
      // Fact extraction runs in the background on the server, so re-fetch the
      // profile shortly after to pick up anything new it learned this turn.
      setTimeout(refreshProfile, 1500);
    }
  }

  // Stop a running (possibly hanging) generation, keeping the partial reply.
  function stop() {
    abortRef.current?.abort();
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
        : mode === "plan"
          ? "Give a multi-step goal — it'll plan, then execute each step."
          : mode === "team"
            ? "Give a goal — a team (planner, retriever, solver, reviewer) tackles it."
            : "Ask me anything to get started.";

  return (
    <div className="relative flex h-full">
      {/* Dimmed backdrop behind the drawer on mobile. */}
      {sidebarOpen && (
        <div
          className="absolute inset-0 z-10 bg-black/30 sm:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar: conversation list. A slide-over drawer on mobile, a static
          column on sm+ screens. */}
      <aside
        className={
          "absolute inset-y-0 left-0 z-20 w-64 shrink-0 flex-col border-r " +
          "border-neutral-200 bg-white sm:static sm:z-auto " +
          (sidebarOpen ? "flex " : "hidden ") +
          "sm:flex"
        }
      >
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
                className="block shrink-0 text-xs text-neutral-400 hover:text-red-600 sm:hidden sm:group-hover:block"
                title="Delete conversation"
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        {/* Phase 13: what the assistant durably remembers about you, shown
            across all conversations. */}
        {facts.length > 0 && (
          <div className="border-t border-neutral-200 p-2">
            <div className="mb-1 flex items-center justify-between px-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                Memory
              </span>
              <button
                onClick={onForgetProfile}
                className="text-xs text-neutral-400 hover:text-red-600"
                title="Forget everything about me"
              >
                Forget
              </button>
            </div>
            <ul className="space-y-1">
              {facts.map((f, i) => (
                <li
                  key={i}
                  className="rounded bg-neutral-50 px-2 py-1 text-xs text-neutral-600"
                >
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Phase 23: running satisfaction rate from 👍/👎 feedback. */}
        {fbStats && fbStats.satisfaction_rate !== null && (
          <div className="border-t border-neutral-200 px-3 py-2">
            <span className="text-xs text-neutral-500">
              Satisfaction: {Math.round((fbStats.satisfaction_rate ?? 0) * 100)}%
              <span className="text-neutral-400">
                {" "}
                ({fbStats.up}/{fbStats.up + fbStats.down})
              </span>
            </span>
          </div>
        )}
      </aside>

      {/* Conversation */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile-only bar to open the conversations drawer. */}
        <div className="flex items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2 sm:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-md border border-neutral-300 px-2.5 py-1 text-sm font-medium text-neutral-700"
          >
            ☰ Chats
          </button>
        </div>
        <main className="mx-auto w-full max-w-2xl flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="mt-20 text-center text-neutral-400">{placeholder}</p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={m.role === "user" ? "text-right" : "text-left"}
            >
              {/* Plan (Phase 12) and agent tool steps appear above the answer. */}
              {m.agents && m.agents.length > 0 && (
                <Team agents={m.agents} busy={busy} />
              )}
              {m.plan && m.plan.length > 0 && <Plan plan={m.plan} />}
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
              {m.trace && <TraceView trace={m.trace} />}
              {m.role === "assistant" && m.content && !(busy && i === messages.length - 1) && (
                <Feedback
                  rating={m.rating}
                  onRate={(rating, note) => rateMessage(i, rating, note)}
                />
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </main>

        <footer className="border-t border-neutral-200 bg-white p-4">
          <div className="mx-auto w-full max-w-2xl space-y-2">
            {/* Mode selector: plain chat, RAG grounding, or tool-using agent. */}
            <div className="no-scrollbar flex gap-1 overflow-x-auto rounded-lg bg-neutral-100 p-1 text-xs">
              {(["chat", "rag", "agent", "plan", "team"] as ChatMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={
                    "shrink-0 rounded-md px-3 py-1 font-medium capitalize transition " +
                    (mode === m
                      ? "bg-white text-neutral-900 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-800")
                  }
                >
                  {m}
                </button>
              ))}
            </div>
            {/* items-end keeps the Send button its natural height while the
                textarea grows upward. */}
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                className="max-h-36 flex-1 resize-none overflow-y-auto rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                rows={1}
                placeholder="Type a message…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
              />
              {busy ? (
                <button
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white"
                  onClick={stop}
                  title="Stop generating"
                >
                  Stop
                </button>
              ) : (
                <button
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                  onClick={send}
                  disabled={!input.trim()}
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}

// The plan (Phase 12): a numbered checklist. Each step shows the tools it used
// and its result once executed; a spinner dot marks steps still running.
// The team (Phase 16): one card per sub-agent showing its role and output, in
// the order they ran. A role still working shows a pulsing dot.
function Team({ agents, busy }: { agents: AgentTurn[]; busy: boolean }) {
  return (
    <div className="mb-1 max-w-[85%] space-y-2">
      {agents.map((a, i) => (
        <div
          key={i}
          className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm"
        >
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-violet-700">
            {a.role}
            {a.content === undefined && busy && (
              <span className="ml-1 animate-pulse text-violet-400">…</span>
            )}
          </div>
          {a.content !== undefined && (
            <div className="whitespace-pre-wrap text-neutral-700">
              {a.content}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Plan({ plan }: { plan: PlanStep[] }) {
  return (
    <div className="mb-1 max-w-[85%] space-y-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-indigo-700">
        Plan
      </div>
      <ol className="space-y-2">
        {plan.map((step, i) => (
          <li key={i} className="text-sm">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 text-xs text-indigo-500">
                {step.result !== undefined ? "✓" : `${i + 1}.`}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-neutral-800">{step.task}</div>
                {step.tools.map((t, j) => (
                  <div key={j} className="mt-1 font-mono text-xs text-amber-800">
                    🔧 {t.name}({JSON.stringify(t.args)})
                  </div>
                ))}
                {step.result !== undefined && (
                  <div className="mt-1 text-xs text-neutral-500">
                    → {step.result}
                  </div>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
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

// Per-turn trace (Phase 20): a collapsible timeline of the timed spans that made
// up this turn (retrieval, tool calls, generation), plus a token estimate. It
// turns "that felt slow" into "generation was 2.6s of the 3.1s".
function TraceView({ trace }: { trace: Trace }) {
  const total = trace.total_ms || 1;
  const tokens = trace.tokens?.total_est;
  return (
    <details className="mt-1 text-left">
      <summary className="cursor-pointer list-none text-xs text-neutral-400 hover:text-neutral-600">
        ⏱ {(trace.total_ms / 1000).toFixed(2)}s
        {tokens ? ` · ~${tokens} tok` : ""} · {trace.spans.length} steps
      </summary>
      <div className="mt-1 space-y-1 rounded-lg border border-neutral-200 bg-neutral-50 p-2">
        {trace.spans.map((s, i) => (
          <div key={i} className="text-xs">
            <div className="flex justify-between text-neutral-600">
              <span className="font-mono">{s.name}</span>
              <span className="tabular-nums text-neutral-500">
                {s.duration_ms}ms
              </span>
            </div>
            <div className="mt-0.5 h-1.5 w-full rounded-full bg-neutral-200">
              <div
                className="h-1.5 rounded-full bg-blue-400"
                style={{
                  width: `${Math.max(2, (s.duration_ms / total) * 100)}%`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

// Thumbs up/down under an assistant answer (Phase 23). A 👎 reveals an optional
// one-line note; both submit immediately. The choice is remembered on the message
// so the buttons reflect it (and re-clicking updates the stored rating).
function Feedback({
  rating,
  onRate,
}: {
  rating?: Rating;
  onRate: (rating: Rating, note?: string) => void;
}) {
  const [showNote, setShowNote] = useState(false);
  const [note, setNote] = useState("");
  return (
    <div className="mt-1 flex items-center gap-2 text-left">
      <button
        onClick={() => onRate("up")}
        title="Good answer"
        className={
          "rounded px-1.5 py-0.5 text-xs " +
          (rating === "up"
            ? "bg-green-100 text-green-700"
            : "text-neutral-400 hover:text-neutral-600")
        }
      >
        👍
      </button>
      <button
        onClick={() => {
          setShowNote(true);
          onRate("down");
        }}
        title="Bad answer"
        className={
          "rounded px-1.5 py-0.5 text-xs " +
          (rating === "down"
            ? "bg-red-100 text-red-700"
            : "text-neutral-400 hover:text-neutral-600")
        }
      >
        👎
      </button>
      {rating && <span className="text-xs text-neutral-400">thanks!</span>}
      {showNote && rating === "down" && (
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && note.trim()) {
              onRate("down", note.trim());
              setShowNote(false);
            }
          }}
          placeholder="What was wrong? (optional, Enter to send)"
          className="flex-1 rounded border border-neutral-200 px-2 py-0.5 text-xs"
        />
      )}
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
