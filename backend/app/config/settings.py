"""Centralised application configuration for X FACTOR.

Runtime configuration is loaded from environment variables, optionally seeded
from a local ``.env`` file. Secrets are never hard-coded here: only variable
names and safe, non-secret defaults are declared.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------
    APP_NAME: str = "X FACTOR"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    API_PREFIX: str = "/api"

    # Comma separated list of origins allowed to call the API (CORS).
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- PostgreSQL ----------------------------------------------------
    # A full connection URI (what managed providers hand out) takes
    # precedence over the discrete parts below when it is set.
    DATABASE_URL: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "xfactor"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "xfactor"
    DB_CONNECT_TIMEOUT: int = 3

    # --- Google Gemini (LLM reasoning) — Step 1 onwards -----------------
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_TIMEOUT_SECONDS: int = 90
    GEMINI_MAX_OUTPUT_TOKENS: int = 2048
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"

    # --- LangGraph orchestration — Step 4 onwards -----------------------
    LANGGRAPH_MAX_ITERATIONS: int = 6
    LANGGRAPH_CHECKPOINT_BACKEND: str = "postgres"

    # --- SAP integration — Step 7 onwards -------------------------------
    SAP_BASE_URL: str = ""
    SAP_CLIENT_ID: str = ""
    SAP_CLIENT_SECRET: str = ""
    SAP_USE_MOCK: bool = True

    # --- External data APIs — Step 2 onwards ----------------------------
    # Every connector falls back to a clearly labelled *simulated* adapter when
    # its base URL and key are not configured. The mock flag travels with each
    # response so simulated data is never presented as live information.
    INTEGRATION_TIMEOUT_SECONDS: int = 10
    INTEGRATION_MAX_ATTEMPTS: int = 3

    WEATHER_API_BASE_URL: str = ""
    WEATHER_API_KEY: str = ""
    NEWS_API_BASE_URL: str = ""
    NEWS_API_KEY: str = ""
    MARITIME_ALERTS_API_BASE_URL: str = ""
    MARITIME_ALERTS_API_KEY: str = ""
    PORT_CONGESTION_API_BASE_URL: str = ""
    PORT_CONGESTION_API_KEY: str = ""
    TARIFF_API_BASE_URL: str = ""
    TARIFF_API_KEY: str = ""
    SUPPLIER_API_BASE_URL: str = ""
    SUPPLIER_API_KEY: str = ""
    CARRIER_API_BASE_URL: str = ""
    CARRIER_API_KEY: str = ""
    SHIPMENT_TRACKING_API_BASE_URL: str = ""
    SHIPMENT_TRACKING_API_KEY: str = ""
    MAPPING_API_BASE_URL: str = ""
    MAPPING_API_KEY: str = ""

    # --- Derived helpers ------------------------------------------------
    @property
    def cors_origins(self) -> List[str]:
        """Return the configured CORS origins as a clean list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        """SQLAlchemy connection URL for PostgreSQL.

        A full ``DATABASE_URL`` URI wins over the discrete ``POSTGRES_*``
        parts, so managed/pasted connection strings need no code change.
        """
        uri = self.DATABASE_URL.strip()
        if uri:
            return self._normalise_database_uri(uri)
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @staticmethod
    def _normalise_database_uri(uri: str) -> str:
        """Point a pasted URI at the psycopg2 driver that is installed."""
        for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
            if uri.startswith(prefix):
                return f"postgresql+psycopg2://{uri[len(prefix) :]}"
        return uri

    @property
    def gemini_configured(self) -> bool:
        """True when a Gemini API key is present."""
        return bool(self.GEMINI_API_KEY)

    @property
    def sap_configured(self) -> bool:
        """True when SAP credentials are present and mocks are disabled."""
        return bool(self.SAP_BASE_URL and self.SAP_CLIENT_ID and self.SAP_CLIENT_SECRET)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
