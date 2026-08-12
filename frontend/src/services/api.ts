// Talks to the FastAPI backend.
//
// The /chat endpoint streams Server-Sent Events. The browser's built-in
// EventSource only supports GET requests, but we need to POST the message
// history, so we read the response body stream manually and parse the
// "data: {...}" lines ourselves.

// --- Auth token (per-user segregation) ---
// The JWT lives in localStorage and is attached to every request. A 401 means
// the token is missing/expired, so we clear it and notify the app to show login.

const TOKEN_KEY = "auth_token";

export const authToken = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

let onAuthError: () => void = () => {};
export function setAuthErrorHandler(fn: () => void) {
  onAuthError = fn;
}

function withAuth(headers: Record<string, string> = {}): Record<string, string> {
  const t = authToken.get();
  return t ? { ...headers, Authorization: `Bearer ${t}` } : headers;
}

// fetch wrapper that injects the auth header and reacts to 401 globally.
async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, {
    ...options,
    headers: withAuth(options.headers as Record<string, string> | undefined),
  });
  if (res.status === 401) {
    authToken.clear();
    onAuthError();
  }
  return res;
}

// --- Auth endpoints (use plain fetch: a 401 here is "bad credentials", not a
// session expiry, so it must NOT trigger the global logout handler). ---

export async function signup(email: string, password: string): Promise<string> {
  return authRequest("/api/auth/signup", email, password);
}

export async function login(email: string, password: string): Promise<string> {
  return authRequest("/api/auth/login", email, password);
}

async function authRequest(
  url: string,
  email: string,
  password: string
): Promise<string> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await errorText(res, "Auth"));
  const data = await res.json();
  authToken.set(data.token);
  return data.token;
}

export function logout() {
  authToken.clear();
}

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
  const response = await apiFetch("/api/tokenize", {
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
  const response = await apiFetch("/api/embed", {
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
  const response = await apiFetch("/api/documents", {
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
  const response = await apiFetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k, mode, rerank }),
  });
  if (!response.ok) throw new Error(await errorText(response, "Search"));
  const data = await response.json();
  return data.results;
}

export async function documentCount(): Promise<number> {
  const response = await apiFetch("/api/documents/count");
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
  const response = await apiFetch("/api/documents");
  if (!response.ok) throw new Error(await errorText(response, "List"));
  return response.json();
}

// Replace a document's title/text. The backend re-embeds the new text.
export async function updateDocument(
  id: number,
  text: string,
  title: string
): Promise<void> {
  const response = await apiFetch(`/api/documents/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!response.ok) throw new Error(await errorText(response, "Update"));
}

export async function deleteDocument(id: number): Promise<number> {
  const response = await apiFetch(`/api/documents/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await errorText(response, "Delete"));
  return (await response.json()).total_documents;
}

export interface UploadResult {
  filename: string;
  pages: number;
  chunks_stored: number;
  total_documents: number;
}

// Upload a document (PDF, DOCX, Markdown, text, or HTML). The backend extracts
// text, chunks it, embeds every chunk, and stores them as searchable documents.
export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch("/api/upload", { method: "POST", body: form });
  if (!response.ok) throw new Error(await errorText(response, "Upload"));
  return response.json();
}

// Ingest a web page by URL (Phase 26): fetch, extract text, chunk, embed, store.
export async function ingestUrl(url: string): Promise<UploadResult> {
  const response = await apiFetch("/api/ingest/url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!response.ok) throw new Error(await errorText(response, "URL ingest"));
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
  // Only the plan-and-execute agent emits these (Phase 12).
  onPlan?: (steps: { task: string }[]) => void;
  onStepStart?: (index: number, task: string) => void;
  onStepResult?: (index: number, result: string) => void;
  // Only the multi-agent team emits these (Phase 16).
  onAgentStart?: (role: string) => void;
  onAgentMessage?: (role: string, content: string) => void;
  // Per-turn trace: timed spans + token estimate (Phase 20).
  onTrace?: (trace: Trace) => void;
}

// One timed sub-step of a turn (retrieval, a tool call, generation).
export interface TraceSpan {
  name: string;
  duration_ms: number;
  meta?: Record<string, unknown>;
}

export interface Trace {
  mode: string;
  total_ms: number;
  tokens?: { prompt_est?: number; response_est?: number; total_est?: number };
  spans: TraceSpan[];
}

// Shared SSE reader used by all streaming endpoints. It POSTs the body, then
// reads the response stream and dispatches each `data: {...}` event.
//
// Pass a `signal` (from an AbortController) to make the request cancellable: if
// the model hangs, the caller can abort. We treat an abort as a graceful stop —
// whatever was streamed so far is kept, no error is raised.
async function streamSse(
  url: string,
  body: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: withAuth({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") return; // stopped before response
    throw e;
  }

  if (response.status === 401) {
    authToken.clear();
    onAuthError();
    handlers.onError("Session expired — please sign in again.");
    return;
  }
  if (!response.ok || !response.body) {
    handlers.onError(`Request failed: ${response.status}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Network chunks don't line up with SSE events, so we buffer and split on the
  // blank line that separates events.
  try {
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
        else if (payload.type === "plan") handlers.onPlan?.(payload.steps);
        else if (payload.type === "step_start")
          handlers.onStepStart?.(payload.index, payload.task);
        else if (payload.type === "step_result")
          handlers.onStepResult?.(payload.index, payload.result);
        else if (payload.type === "agent_start")
          handlers.onAgentStart?.(payload.role);
        else if (payload.type === "agent_message")
          handlers.onAgentMessage?.(payload.role, payload.content);
        else if (payload.type === "trace") handlers.onTrace?.(payload.trace);
        else if (payload.type === "done") handlers.onDone();
        else if (payload.type === "error") handlers.onError(payload.content);
      }
    }
  } catch (e) {
    // Aborting mid-stream throws here; that's an intentional stop, not an error.
    if ((e as Error)?.name !== "AbortError") throw e;
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
  const r = await apiFetch("/api/threads");
  if (!r.ok) throw new Error(await errorText(r, "List threads"));
  return r.json();
}

export async function createThread(): Promise<Thread> {
  const r = await apiFetch("/api/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(await errorText(r, "Create thread"));
  return r.json();
}

export async function getThreadMessages(id: number): Promise<Message[]> {
  const r = await apiFetch(`/api/threads/${id}/messages`);
  if (!r.ok) throw new Error(await errorText(r, "Load thread"));
  return r.json();
}

export async function deleteThread(id: number): Promise<void> {
  const r = await apiFetch(`/api/threads/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await errorText(r, "Delete thread"));
}

// --- Phase 13: long-term user profile memory ---

// Durable facts the assistant has learned about the user, shown across all
// conversations. Each carries an id so it can be deleted individually (Phase 25).
export interface Fact {
  id: number;
  fact: string;
}

export async function getProfile(): Promise<Fact[]> {
  const r = await apiFetch("/api/profile");
  if (!r.ok) throw new Error(await errorText(r, "Profile"));
  return (await r.json()).facts;
}

export async function clearProfile(): Promise<void> {
  const r = await apiFetch("/api/profile", { method: "DELETE" });
  if (!r.ok) throw new Error(await errorText(r, "Clear profile"));
}

export async function deleteFact(id: number): Promise<void> {
  const r = await apiFetch(`/api/profile/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await errorText(r, "Delete fact"));
}

// --- Feedback (Phase 23) ---
export type Rating = "up" | "down";

export async function submitFeedback(input: {
  threadId: number | null;
  question: string;
  answer: string;
  rating: Rating;
  note?: string;
}): Promise<void> {
  const r = await apiFetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      thread_id: input.threadId,
      question: input.question,
      answer: input.answer,
      rating: input.rating,
      note: input.note ?? "",
    }),
  });
  if (!r.ok) throw new Error(await errorText(r, "Feedback"));
}

export interface FeedbackStats {
  up: number;
  down: number;
  total: number;
  satisfaction_rate: number | null;
}

export async function getFeedbackStats(): Promise<FeedbackStats> {
  const r = await apiFetch("/api/feedback/stats");
  if (!r.ok) throw new Error(await errorText(r, "Feedback stats"));
  return r.json();
}

// Phase 29: exchange a still-valid token for a fresh one (sliding session), so
// an active user isn't logged out mid-use. Best-effort — ignored on failure.
export async function refreshSession(): Promise<void> {
  try {
    const r = await apiFetch("/api/auth/refresh", { method: "POST" });
    if (r.ok) {
      const body = await r.json();
      if (body.token) authToken.set(body.token);
    }
  } catch {
    /* non-critical */
  }
}

// --- Chat-scoped attachments (Phase 30/31) ---
export interface Attachment {
  filename: string;
  chunks: number;
  id: number;
}

export async function attachFile(
  threadId: number,
  file: File
): Promise<{ filename: string; chunks_stored: number }> {
  const form = new FormData();
  form.append("file", file);
  const r = await apiFetch(`/api/threads/${threadId}/attach`, {
    method: "POST",
    body: form,
  });
  if (!r.ok) throw new Error(await errorText(r, "Attach"));
  return r.json();
}

export async function listAttachments(threadId: number): Promise<Attachment[]> {
  const r = await apiFetch(`/api/threads/${threadId}/attachments`);
  if (!r.ok) throw new Error(await errorText(r, "Attachments"));
  return r.json();
}

export async function deleteAttachment(
  threadId: number,
  filename: string
): Promise<void> {
  const r = await apiFetch(
    `/api/threads/${threadId}/attachments/${encodeURIComponent(filename)}`,
    { method: "DELETE" }
  );
  if (!r.ok) throw new Error(await errorText(r, "Delete attachment"));
}

export type ChatMode = "chat" | "rag" | "agent" | "plan" | "team";

// Send one new message to a thread. The backend loads history itself and
// persists both the question and the streamed answer. `mode` selects plain
// chat, RAG grounding, or the tool-using agent.
export function streamThreadChat(
  threadId: number,
  content: string,
  mode: ChatMode,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  regenerate = false // Phase 28: re-answer the last question in place
): Promise<void> {
  return streamSse(
    `/api/threads/${threadId}/chat`,
    { content, mode, regenerate },
    handlers,
    signal
  );
}

