# Architecture & Mental Map

This document is the "big picture" of the AI Workspace Copilot. It grows one
phase at a time. Read it top-to-bottom to understand how the pieces fit.

## What we are building

One application that we keep improving until it behaves like a production AI
assistant (RAG, tools, agents, MCP), built entirely on free-tier services.

## The mental model

Think of the system as a request flowing left-to-right:

```
Browser (React)  ──HTTP/SSE──►  FastAPI backend  ──►  Gemini LLM
```

- The **frontend** is a dumb terminal: it collects user input, shows replies,
  and knows nothing about how answers are produced.
- The **backend** is the brain. Today it only forwards messages to Gemini.
  Over the coming phases it will gain RAG, tools, memory, and agents.
- The **LLM (Gemini)** is stateless. It has no memory of past turns — we resend
  the whole conversation on every request. Everything "smart" we add later is
  really about *what context we choose to feed the LLM*.

## Phases implemented so far

| Phase | Feature | Status |
| ----- | ------- | ------ |
| 0 | ChatGPT-style streaming chat | ✅ Done |

## Current data flow (Phase 0)

```
1. User types a message in the React UI.
2. Frontend sends the FULL message history to POST /api/chat.
3. Backend converts messages to Gemini's format and opens a streaming call.
4. Gemini emits the answer token-by-token.
5. Backend wraps each token as a Server-Sent Event (SSE) and streams it back.
6. Frontend appends each token to the on-screen assistant bubble in real time.
```

## Why streaming (SSE)?

A full LLM answer can take several seconds. Streaming shows the first words
almost immediately, so the UI feels alive instead of frozen. We use SSE (a
one-way server→client stream over plain HTTP) because it is simpler than
WebSockets and perfectly suited to "server pushes text as it's ready".

## Repo layout

```
backend/     FastAPI app (the brain)
  api/       HTTP endpoints
  services/  Integrations with external systems (Gemini today)
  config.py  All environment-driven settings
  models.py  Pydantic request/response schemas
frontend/    React + TypeScript + Tailwind (the UI)
  src/services/  Client-side API calls
docs/        These documents
```

See [backend.md](backend.md) and [frontend.md](frontend.md) for details.
