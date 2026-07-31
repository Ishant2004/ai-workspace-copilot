"""Central configuration.

We read every setting from environment variables (loaded from a .env file in
local development). Keeping this in one place means the rest of the code never
touches os.environ directly.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (the backend dir) rather than the current
# working directory, so the app works no matter where it's launched from — e.g.
# the MCP server started by Claude Desktop/Cursor with an arbitrary cwd.
_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    cors_origins: str = "http://localhost:5173"
    # Hard timeout (seconds) for any Gemini request, so a hung call fails fast.
    gemini_request_timeout: int = 60

    # --- Token inspector settings (Phase 1) ---
    # How many tokens the model can hold in one request. Gemini Flash models
    # have a ~1M token context window. Used to show "% of context used".
    gemini_context_window: int = 1_048_576
    # Reference paid-tier price per 1 million input tokens (USD). We are on the
    # free tier (actual cost $0), but showing what it *would* cost teaches the
    # economics of token usage.
    gemini_input_price_per_1m: float = 0.30

    # --- Vector database settings (Phase 3) ---
    # Neon Postgres connection string, e.g.
    #   postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
    database_url: str = ""

    # --- Embedding settings (Phase 2) ---
    gemini_embed_model: str = "gemini-embedding-001"
    # Output vector size. gemini-embedding-001 natively produces 3072 dims but
    # supports Matryoshka truncation to smaller sizes. 768 is a good balance of
    # quality vs. storage; whatever we pick here becomes the column size of the
    # pgvector table in Phase 3, so keep it consistent once documents exist.
    gemini_embed_dim: int = 768

    # --- PDF ingestion / chunking settings (Phase 5) ---
    # A long document can't be embedded as one vector meaningfully, so we split
    # it into overlapping chunks. Overlap keeps sentences that straddle a
    # boundary retrievable from both sides.
    chunk_size: int = 800  # characters per chunk
    chunk_overlap: int = 100  # characters shared between adjacent chunks

    # --- Reranker settings (Phase 8) ---
    # FlashRank cross-encoder model, downloaded once on first use. MiniLM-L-12
    # (~34MB, CPU) is noticeably more accurate than the tiny TinyBERT default
    # while still running in-memory with no GPU or API calls.
    rerank_model: str = "ms-marco-MiniLM-L-12-v2"
    # How many candidates to retrieve before reranking down to k.
    rerank_candidates: int = 20

    # --- Conversation memory (Phase 9) ---
    # The LLM is stateless, so we resend history each turn. To bound the prompt
    # (and cost), we only send the most recent N messages — a "sliding window".
    history_window: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
