import { useEffect, useRef, useState } from "react";
import { streamChat, type Message } from "../services/api";

// Phase 0: streaming chat with Gemini.
export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
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
    const history: Message[] = [...messages, { role: "user", content: text }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setBusy(true);

    const appendToAssistant = (extra: string) => {
      setMessages((prev) => {
        const copy = [...prev];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = { ...last, content: last.content + extra };
        return copy;
      });
    };

    await streamChat(history, {
      onChunk: appendToAssistant,
      onDone: () => setBusy(false),
      onError: (msg) => {
        appendToAssistant(`\n\n[error] ${msg}`);
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
    <div className="flex h-full flex-col">
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="mt-20 text-center text-neutral-400">
            Ask me anything to get started.
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
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      <footer className="border-t border-neutral-200 bg-white p-4">
        <div className="mx-auto flex w-full max-w-2xl gap-2">
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
      </footer>
    </div>
  );
}
