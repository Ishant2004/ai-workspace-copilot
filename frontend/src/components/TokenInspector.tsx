import { useEffect, useState } from "react";
import { tokenize, type TokenStats } from "../services/api";

// Phase 1: Token Inspector.
//
// Characters and words are counted instantly in the browser. The exact TOKEN
// count must come from the model's tokenizer (backend), so we debounce: we only
// call the API ~600ms after the user stops typing, to avoid a request per
// keystroke.

export default function TokenInspector() {
  const [text, setText] = useState("");
  const [stats, setStats] = useState<TokenStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Instant local counts (no API needed).
  const characters = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;

  useEffect(() => {
    if (!text.trim()) {
      setStats(null);
      setError(null);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        setStats(await tokenize(text));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to tokenize");
      } finally {
        setLoading(false);
      }
    }, 600);
    // If the user types again before 600ms, cancel the pending call.
    return () => clearTimeout(handle);
  }, [text]);

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4 p-4">
      <p className="text-sm text-neutral-500">
        See how your text breaks down into tokens — the units LLMs actually
        read and bill for. Type below; the token count updates when you pause.
      </p>

      <textarea
        className="h-40 w-full resize-none rounded-lg border border-neutral-300 p-3 text-sm focus:border-blue-500 focus:outline-none"
        placeholder="Paste or type any text to inspect its token usage…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric label="Characters" value={characters.toLocaleString()} />
        <Metric label="Words" value={words.toLocaleString()} />
        <Metric
          label="Tokens"
          value={
            loading
              ? "…"
              : stats
                ? stats.tokens.toLocaleString()
                : "0"
          }
          highlight
        />
        <Metric
          label="Context used"
          value={stats ? `${stats.context_used_percent.toFixed(4)}%` : "0%"}
          sub={
            stats
              ? `of ${stats.context_window.toLocaleString()} tokens`
              : undefined
          }
        />
        <Metric
          label="Cost (free tier)"
          value={stats ? `$${stats.estimated_cost_usd.toFixed(2)}` : "$0.00"}
        />
        <Metric
          label="Paid-tier ref."
          value={stats ? `$${stats.reference_cost_usd.toFixed(6)}` : "$0.000000"}
          sub={stats ? `model: ${stats.model}` : undefined}
        />
      </div>

      {error && <p className="text-sm text-red-600">[error] {error}</p>}
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={
        "rounded-lg border p-3 " +
        (highlight
          ? "border-blue-200 bg-blue-50"
          : "border-neutral-200 bg-white")
      }
    >
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-neutral-400">{sub}</div>}
    </div>
  );
}
