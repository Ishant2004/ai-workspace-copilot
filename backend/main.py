"""FastAPI application entry point.

Run locally with:  uvicorn main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.documents import router as documents_router
from api.embed import router as embed_router
from api.feedback import router as feedback_router
from api.ingest import router as ingest_router
from api.profile import router as profile_router
from api.rag import router as rag_router
from api.threads import router as threads_router
from api.tokens import router as tokens_router
from api.tools import router as tools_router
from api.upload import router as upload_router
from config import settings
from services import auth, cache, db, feedback, profile, threads, tracing

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup, make sure the vector extension + documents table exist. If no
    # database is configured (or it's unreachable) we log a warning instead of
    # crashing, so the chat/token/embed features still work without a DB.
    if settings.database_url:
        try:
            db.init_db()
            threads.init_threads()
            profile.init_profile()
            auth.init_auth()
            tracing.init_traces()
            feedback.init_feedback()
            logger.info(
                "DB tables (vector, threads, profile, users, traces, feedback) "
                "initialised."
            )
        except Exception as exc:
            logger.warning("Could not initialise database: %s", exc)
    else:
        logger.warning("DATABASE_URL not set — DB-backed features disabled.")
    yield


app = FastAPI(title="AI Workspace Copilot", lifespan=lifespan)

# The React frontend runs on a different origin (port), so the browser blocks
# requests unless we explicitly allow it here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(tokens_router)
app.include_router(embed_router)
app.include_router(documents_router)
app.include_router(rag_router)
app.include_router(upload_router)
app.include_router(ingest_router)
app.include_router(threads_router)
app.include_router(tools_router)
app.include_router(profile_router)
app.include_router(feedback_router)


@app.get("/health")
def health() -> dict:
    """Cheap endpoint for uptime pings and quick sanity checks."""
    return {"status": "ok"}


@app.get("/cache/stats")
def cache_stats() -> dict:
    """Cache hit/miss stats (Phase 24) — makes the caching win observable."""
    return cache.stats()
