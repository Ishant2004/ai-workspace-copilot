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
