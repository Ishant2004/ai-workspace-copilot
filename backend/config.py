"""Central configuration.

We read every setting from environment variables (loaded from a .env file in
local development). Keeping this in one place means the rest of the code never
touches os.environ directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    cors_origins: str = "http://localhost:5173"

    # --- Token inspector settings (Phase 1) ---
    # How many tokens the model can hold in one request. Gemini Flash models
    # have a ~1M token context window. Used to show "% of context used".
    gemini_context_window: int = 1_048_576
    # Reference paid-tier price per 1 million input tokens (USD). We are on the
    # free tier (actual cost $0), but showing what it *would* cost teaches the
    # economics of token usage.
    gemini_input_price_per_1m: float = 0.30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
