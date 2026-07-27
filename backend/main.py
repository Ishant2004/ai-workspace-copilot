"""FastAPI application entry point.

Run locally with:  uvicorn main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat import router as chat_router
from api.embed import router as embed_router
from api.tokens import router as tokens_router
from config import settings

app = FastAPI(title="AI Workspace Copilot")

# The React frontend runs on a different origin (port), so the browser blocks
# requests unless we explicitly allow it here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(tokens_router)
app.include_router(embed_router)


@app.get("/health")
def health() -> dict:
    """Cheap endpoint for uptime pings and quick sanity checks."""
    return {"status": "ok"}
