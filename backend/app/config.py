from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # ── Azure OpenAI ──────────────────────────────────────────────
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"

    # ── Azure Cosmos DB ───────────────────────────────────────────
    AZURE_COSMOS_ENDPOINT: str = ""
    AZURE_COSMOS_KEY: str = ""

    # ── Azure AI Search ───────────────────────────────────────────
    AZURE_SEARCH_ENDPOINT: str = ""
    AZURE_SEARCH_KEY: str = ""

    # ── Azure Service Bus ─────────────────────────────────────────
    AZURE_SERVICEBUS_CONNECTION_STRING: str = ""

    # ── Application ───────────────────────────────────────────────
    MAX_INVESTIGATION_ROUNDS: int = 3
    CONFIDENCE_THRESHOLD: float = 0.7
    CORROBORATION_BOOST: float = 1.3
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Singleton settings loader — cached after first call."""
    return Settings()
