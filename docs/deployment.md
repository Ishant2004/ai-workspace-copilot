# Deployment ($0 budget) — Phase 17

The whole stack runs on free tiers:

| Piece | Host | Notes |
| ----- | ---- | ----- |
| Frontend | **Vercel** | Static React build, global CDN, auto-deploy on push. |
| Backend | **Render** (or Koyeb) | FastAPI in a Docker container, free web service. |
| Vector DB | **Neon Postgres** | already used in dev (`DATABASE_URL`). |
| LLM + embeddings | **Google Gemini** | `GEMINI_API_KEY`. |

## Architecture in production

```
Browser ──► Vercel (React static)
              │  /api/* rewrite (vercel.json)
              ▼
        Render (FastAPI container)  ──► Neon Postgres
              │
              ▼
          Google Gemini
```

The frontend keeps calling **relative `/api/...`** paths. In dev, Vite proxies
those to `localhost:8000`; in production, `frontend/vercel.json` rewrites
`/api/*` to the Render backend. Same code, no CORS, both environments.

## 1. Backend → Render

The repo ships a `render.yaml` blueprint and `backend/Dockerfile`.

1. Push the repo to GitHub.
2. Render → **New → Blueprint** → select the repo. It reads `render.yaml` and
   creates a Dockerized web service (`healthCheckPath: /health`).
3. Set the secret env vars in the dashboard (they're `sync: false`):
   - `GEMINI_API_KEY`
   - `DATABASE_URL` (your Neon connection string)
   - `CORS_ORIGINS` (your Vercel URL, e.g. `https://your-app.vercel.app`)
   - `JWT_SECRET` — a long random string for signing login tokens (the
     blueprint asks Render to generate one; or run `openssl rand -hex 32`).
     Changing it later logs everyone out.
4. Deploy. Note the service URL, e.g. `https://ai-workspace-copilot-backend.onrender.com`.

The Dockerfile listens on `$PORT` (Render injects it). Verified locally: the
image builds and `GET /health` returns `{"status":"ok"}`.

## 2. Frontend → Vercel

1. Vercel → **New Project** → import the repo, set **Root Directory** to
   `frontend`.
2. Edit `frontend/vercel.json` and replace `YOUR-BACKEND.onrender.com` with your
   Render host.
3. Deploy. Build command `npm run build`, output `dist` (Vercel autodetects Vite).

## 3. Keep-alive (avoid cold starts)

Render's free tier sleeps after inactivity. Create a free **UptimeRobot**
monitor that HTTP-pings `https://<backend>/health` every 10 minutes to keep it
warm.

## 4. CI/CD

- `.github/workflows/ci.yml` build-checks both apps on every push/PR to `main`.
- Actual deploys are automatic: Vercel and Render each redeploy on push to
  `main` via their GitHub integration — no extra pipeline needed.

## Notes

- **MCP**: the external-MCP feature (Phase 15) needs `mcp_servers.json` and
  local tools like `npx`; it's meant for local/dev and is dormant in the
  container unless you add the config and runtimes.
- **First rerank** downloads the FlashRank model (~34MB) into the container at
  runtime; the free instance has enough disk for it.
- Keep `GEMINI_EMBED_DIM` identical to what your stored documents were embedded
  with, or existing vectors become incomparable.
