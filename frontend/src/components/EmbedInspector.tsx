import { useEffect, useState } from "react";
import { embed, type EmbedResult } from "../services/api";

// Phase 2: Embedding viewer.
//
// Turns text into a vector and visualises it. The point to internalise: this
// long list of numbers *is* the meaning of the text as the model sees it.
// Similar texts produce similar vectors — which is what powers semantic search
// in later phases. Debounced like the token inspector to avoid a call per key.

// How many of the vector's values to show. The user toggles between these.
const COUNT_OPTIONS = [12, 28, 52, 104];

export default function EmbedInspector() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<EmbedResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(25); // how many dimensions to display

  useEffect(() => {
    if (!text.trim()) {
      setResult(null);
      setError(null);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        setResult(await embed(text));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to embed");
      } finally {
        setLoading(false);
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [text]);

  // Slice of the vector we currently display, plus the largest magnitude in
  // that slice (used to scale the bars so they fill the available height).
  const preview = result?.embedding.slice(0, count) ?? [];
  const maxAbs = Math.max(0.0001, ...preview.map((v) => Math.abs(v)));

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4 p-4">
      <p className="text-sm text-neutral-500">
        An embedding turns text into a fixed-length vector of numbers. Texts
        with similar meaning produce similar vectors — the foundation for
        semantic search and RAG. Type below to see the vector.
      </p>

      <textarea
        className="h-32 w-full resize-none rounded-lg border border-neutral-300 p-3 text-sm focus:border-blue-500 focus:outline-none"
        placeholder="Type any text to embed…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <div className="text-xs uppercase tracking-wide text-neutral-500">
            Dimensions
          </div>
          <div className="mt-1 text-xl font-semibold">
            {loading ? "…" : result ? result.dimension.toLocaleString() : "0"}
          </div>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white p-3">
          <div className="text-xs uppercase tracking-wide text-neutral-500">
            Model
          </div>
          <div className="mt-1 truncate text-sm font-medium">
            {result ? result.model : "—"}
          </div>
        </div>
      </div>

      {result && (
        <div className="space-y-3">
          {/* Toggle: how many values to visualise (10 → 100). */}
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-wide text-neutral-500">
              First {Math.min(count, result.dimension)} of {result.dimension}{" "}
              values
            </div>
            <div className="flex gap-1 rounded-lg bg-neutral-100 p-1 text-xs">
              {COUNT_OPTIONS.map((n) => (
                <button
                  key={n}
                  onClick={() => setCount(n)}
                  className={
                    "rounded-md px-2.5 py-1 font-medium transition " +
                    (count === n
                      ? "bg-white text-neutral-900 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-800")
                  }
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          {/* Bar strip: blue = positive, red = negative, height = magnitude. */}
          <div className="flex h-24 items-center gap-[2px] rounded-lg border border-neutral-200 bg-white p-2">
            {preview.map((v, i) => (
              <div
                key={i}
                className="flex-1"
                title={`[${i}] ${v.toFixed(5)}`}
                style={{
                  height: `${(Math.abs(v) / maxAbs) * 100}%`,
                  backgroundColor: v >= 0 ? "#3b82f6" : "#ef4444",
                  borderRadius: 1,
                }}
              />
            ))}
          </div>

          {/* Readable number grid: one chip per value with index, sign colour,
              and a magnitude bar so you can scan the vector at a glance. */}
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            {preview.map((v, i) => (
              <ValueChip key={i} index={i} value={v} maxAbs={maxAbs} />
            ))}
          </div>
        </div>
      )}

      {error && <p className="text-sm text-red-600">[error] {error}</p>}
    </div>
  );
}

function ValueChip({
  index,
  value,
  maxAbs,
}: {
  index: number;
  value: number;
  maxAbs: number;
}) {
  const positive = value >= 0;
  const widthPct = (Math.abs(value) / maxAbs) * 100;
  return (
    <div className="relative overflow-hidden rounded-md border border-neutral-200 bg-white px-2 py-1.5">
      {/* Magnitude bar as a subtle background fill. */}
      <div
        className="absolute inset-y-0 left-0"
        style={{
          width: `${widthPct}%`,
          backgroundColor: positive ? "#eff6ff" : "#fef2f2",
        }}
      />
      <div className="relative flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] text-neutral-400">
          #{index}
        </span>
        <span
          className={
            "font-mono text-xs font-medium tabular-nums " +
            (positive ? "text-blue-700" : "text-red-600")
          }
        >
          {positive ? "+" : ""}
          {value.toFixed(4)}
        </span>
      </div>
    </div>
  );
}
