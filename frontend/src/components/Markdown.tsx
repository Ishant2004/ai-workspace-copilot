import { useState } from "react";

// Minimal, dependency-free Markdown renderer for assistant answers (Phase 28).
// It handles the constructs LLMs actually emit — fenced code, inline code, bold,
// italic, links, headings, and lists — rather than pulling in a full parser. Not
// spec-complete on purpose: small, readable, and good enough for chat output.
export default function Markdown({ text }: { text: string }) {
  return <div className="space-y-2 text-sm leading-relaxed">{renderBlocks(text)}</div>;
}

// Split off fenced code blocks first (they can contain anything), then render the
// prose between them.
function renderBlocks(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const fence = /```([\w-]*)\n([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = fence.exec(text)) !== null) {
    if (m.index > last)
      out.push(...renderProse(text.slice(last, m.index), key++));
    out.push(
      <CodeBlock key={`code-${key++}`} lang={m[1]} code={m[2].replace(/\n$/, "")} />
    );
    last = fence.lastIndex;
  }
  if (last < text.length) out.push(...renderProse(text.slice(last), key++));
  return out;
}

const SPECIAL = /^(#{1,3})\s|^\s*[-*]\s|^\s*\d+\.\s/;

// Block-level prose: headings, bullet/numbered lists, and paragraphs.
function renderProse(segment: string, base: number): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const lines = segment.split("\n");
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = h[1].length;
      const cls =
        lvl === 1 ? "text-base font-bold" : lvl === 2 ? "font-bold" : "font-semibold";
      nodes.push(
        <p key={`${base}-${k++}`} className={cls}>
          {renderInline(h[2])}
        </p>
      );
      i++;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      nodes.push(
        <ul key={`${base}-${k++}`} className="list-disc space-y-0.5 pl-5">
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>
      );
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
      nodes.push(
        <ol key={`${base}-${k++}`} className="list-decimal space-y-0.5 pl-5">
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ol>
      );
      continue;
    }
    // Paragraph: gather consecutive plain lines.
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !SPECIAL.test(lines[i]))
      para.push(lines[i++]);
    nodes.push(<p key={`${base}-${k++}`}>{renderInline(para.join(" "))}</p>);
  }
  return nodes;
}

// Inline formatting: `code`, **bold**, *italic*, [text](url).
function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      nodes.push(
        <code
          key={k++}
          className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-xs text-neutral-800"
        >
          {tok.slice(1, -1)}
        </code>
      );
    } else if (tok.startsWith("**")) {
      nodes.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*")) {
      nodes.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    } else {
      const lm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      nodes.push(
        <a
          key={k++}
          href={lm[2]}
          target="_blank"
          rel="noreferrer"
          className="text-blue-600 underline"
        >
          {lm[1]}
        </a>
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

// A fenced code block: dark, horizontally scrollable, with a language label and
// a copy button.
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="overflow-hidden rounded-lg border border-neutral-700 bg-neutral-900">
      <div className="flex items-center justify-between px-3 py-1 text-xs text-neutral-400">
        <span>{lang || "code"}</span>
        <button
          onClick={() => {
            navigator.clipboard?.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
          className="hover:text-white"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 pb-3">
        <code className="font-mono text-xs text-neutral-100">{code}</code>
      </pre>
    </div>
  );
}
