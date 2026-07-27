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

export interface SearchHit {
  id: number;
  title: string;
  text: string;
  similarity: number;
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

// Semantic search: the backend embeds the query and returns nearest documents.
export async function searchDocuments(
  query: string,
  k = 5
): Promise<SearchHit[]> {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k }),
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
}

export async function streamChat(
  messages: Message[],
  handlers: StreamHandlers
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });

  if (!response.ok || !response.body) {
    handlers.onError(`Request failed: ${response.status}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Read the stream chunk by chunk. Network chunks don't line up with SSE
  // events, so we buffer and split on the blank line that separates events.
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
      else if (payload.type === "done") handlers.onDone();
      else if (payload.type === "error") handlers.onError(payload.content);
    }
  }
}
