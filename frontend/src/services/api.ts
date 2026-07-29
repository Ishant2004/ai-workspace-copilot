// Talks to the FastAPI backend.
//
// The /chat endpoint streams Server-Sent Events. The browser's built-in
// EventSource only supports GET requests, but we need to POST the message
// history, so we read the response body stream manually and parse the
// "data: {...}" lines ourselves.

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface TokenStats {
  model: string;
  characters: number;
  words: number;
  tokens: number;
  context_window: number;
  context_used_percent: number;
  estimated_cost_usd: number;
  reference_cost_usd: number;
}

// Ask the backend to tokenize a piece of text and return usage metrics.
export async function tokenize(text: string): Promise<TokenStats> {
  const response = await fetch("/api/tokenize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    throw new Error(`Tokenize failed: ${response.status}`);
  }
  return response.json();
}

export interface EmbedResult {
  model: string;
  dimension: number;
  embedding: number[];
}

// Ask the backend to embed a piece of text into a numeric vector.
export async function embed(text: string): Promise<EmbedResult> {
  const response = await fetch("/api/embed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    throw new Error(`Embed failed: ${response.status}`);
  }
  return response.json();
}

// --- Phase 3: vector database ---

export interface AddDocResult {
  id: number;
  title: string;
  total_documents: number;
}

// Provenance stored with each document (Phase 6). All fields optional because
// older/manual documents may not have them.
export interface DocMetadata {
  source?: string; // "pdf" | "manual"
  filename?: string;
  page?: number;
  chunk_index?: number;
  uploaded_at?: string;
  created_at?: string;
}

export type SearchMode = "vector" | "keyword" | "hybrid";

export interface SearchHit {
  id: number;
  title: string;
  text: string;
  similarity: number;
  metadata?: DocMetadata;
  matched_by?: string[]; // "vector" and/or "keyword" (Phase 7)
  rrf_score?: number | null; // fused score, hybrid mode only
  rerank_score?: number | null; // cross-encoder score, when reranking (Phase 8)
}

// Store a document: the backend embeds it and saves it in pgvector.
export async function addDocument(
  text: string,
  title: string
): Promise<AddDocResult> {
  const response = await fetch("/api/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!response.ok) throw new Error(await errorText(response, "Add document"));
  return response.json();
}

// Search the documents. `mode` picks the strategy (Phase 7): vector (meaning),
// keyword (exact terms), or hybrid (both, fused with RRF).
export async function searchDocuments(
  query: string,
  k = 5,
  mode: SearchMode = "hybrid",
  rerank = false
): Promise<SearchHit[]> {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k, mode, rerank }),
  });
  if (!response.ok) throw new Error(await errorText(response, "Search"));
  const data = await response.json();
  return data.results;
}

export async function documentCount(): Promise<number> {
  const response = await fetch("/api/documents/count");
  if (!response.ok) throw new Error(await errorText(response, "Count"));
  return (await response.json()).total_documents;
}

export interface DocumentItem {
  id: number;
  title: string;
  text: string;
  metadata?: DocMetadata;
}

// List every stored document (no raw vectors) for the management view.
export async function listDocuments(): Promise<DocumentItem[]> {
  const response = await fetch("/api/documents");
  if (!response.ok) throw new Error(await errorText(response, "List"));
  return response.json();
}

// Replace a document's title/text. The backend re-embeds the new text.
export async function updateDocument(
  id: number,
  text: string,
  title: string
): Promise<void> {
  const response = await fetch(`/api/documents/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!response.ok) throw new Error(await errorText(response, "Update"));
}

export async function deleteDocument(id: number): Promise<number> {
  const response = await fetch(`/api/documents/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorText(response, "Delete"));
  return (await response.json()).total_documents;
}

export interface UploadResult {
  filename: string;
  pages: number;
  chunks_stored: number;
  total_documents: number;
}

// Upload a PDF. The backend extracts text, chunks it, embeds every chunk, and
// stores them as searchable documents. Sent as multipart/form-data.
export async function uploadPdf(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/upload", { method: "POST", body: form });
  if (!response.ok) throw new Error(await errorText(response, "Upload"));
  return response.json();
}

// Pull a useful message out of a failed response (FastAPI puts it in `detail`).
async function errorText(response: Response, label: string): Promise<string> {
  try {
    const body = await response.json();
    return `${label} failed: ${body.detail ?? response.status}`;
  } catch {
    return `${label} failed: ${response.status}`;
  }
}

interface StreamHandlers {
  onChunk: (text: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
  // Only RAG emits this: the documents the answer is grounded in.
  onSources?: (sources: SearchHit[]) => void;
  // Only tool calling emits these (Phase 10).
  onToolCall?: (name: string, args: Record<string, unknown>) => void;
  onToolResult?: (name: string, result: string) => void;
}

// Shared SSE reader used by both plain chat and RAG chat. It POSTs the body,
// then reads the response stream and dispatches each `data: {...}` event.
async function streamSse(
  url: string,
  body: unknown,
  handlers: StreamHandlers
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok || !response.body) {
    handlers.onError(`Request failed: ${response.status}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Network chunks don't line up with SSE events, so we buffer and split on the
  // blank line that separates events.
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? ""; // keep the trailing partial event

    for (const event of events) {
      const line = event.trim();
      if (!line.startsWith("data:")) continue;

      const payload = JSON.parse(line.slice(5).trim());
      if (payload.type === "chunk") handlers.onChunk(payload.content);
      else if (payload.type === "sources")
        handlers.onSources?.(payload.sources);
      else if (payload.type === "tool_call")
        handlers.onToolCall?.(payload.name, payload.args);
      else if (payload.type === "tool_result")
        handlers.onToolResult?.(payload.name, payload.result);
      else if (payload.type === "done") handlers.onDone();
      else if (payload.type === "error") handlers.onError(payload.content);
    }
  }
}

// Phase 0: plain chat, answered from the model's own knowledge.
export function streamChat(
  messages: Message[],
  handlers: StreamHandlers
): Promise<void> {
  return streamSse("/api/chat", { messages }, handlers);
}

// Phase 4: RAG chat — grounded in the user's stored documents. Emits a
// `sources` event (via handlers.onSources) before the answer text.
export function streamRag(
  messages: Message[],
  handlers: StreamHandlers
): Promise<void> {
  return streamSse("/api/rag/chat", { messages, k: 4 }, handlers);
}

// --- Phase 9: conversation threads (persistent memory) ---

export interface Thread {
  id: number;
  title: string;
  message_count: number;
}

export async function listThreads(): Promise<Thread[]> {
  const r = await fetch("/api/threads");
  if (!r.ok) throw new Error(await errorText(r, "List threads"));
  return r.json();
}

export async function createThread(): Promise<Thread> {
  const r = await fetch("/api/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(await errorText(r, "Create thread"));
  return r.json();
}

export async function getThreadMessages(id: number): Promise<Message[]> {
  const r = await fetch(`/api/threads/${id}/messages`);
  if (!r.ok) throw new Error(await errorText(r, "Load thread"));
  return r.json();
}

export async function deleteThread(id: number): Promise<void> {
  const r = await fetch(`/api/threads/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await errorText(r, "Delete thread"));
}

export type ChatMode = "chat" | "rag" | "agent";

// Send one new message to a thread. The backend loads history itself and
// persists both the question and the streamed answer. `mode` selects plain
// chat, RAG grounding, or the tool-using agent.
export function streamThreadChat(
  threadId: number,
  content: string,
  mode: ChatMode,
  handlers: StreamHandlers
): Promise<void> {
  return streamSse(`/api/threads/${threadId}/chat`, { content, mode }, handlers);
}

