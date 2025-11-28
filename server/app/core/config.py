from functools import lru_cache
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    api_title: str = "RAG Chatbot API"
    api_version: str = "0.1.0"

    openai_api_key: str | None = None
    ollama_host: str | None = None

    embeddings_provider: str = "openai"
    vector_store_path: str = "./data/faiss/products"
    product_vector_store_backend: str = "faiss"  # faiss | pinecone
    pinecone_api_key: str | None = None
    pinecone_index_name: str | None = None
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    outlets_db_backend: str = Field("sqlite", alias="OUTLETS_DB_BACKEND")
    outlets_sqlite_url: str = Field(
        default="sqlite:///./data/sqlite/outlets.db",
        validation_alias=AliasChoices("OUTLETS_SQLITE_URL", "SQLITE_URL"),
    )
    outlets_postgres_url: str | None = Field(
        default=None,
        alias="OUTLETS_POSTGRES_URL",
    )
    enable_sse: bool = True
    calc_tool_mode: str = "local"  # http | local
    calc_http_base_url: str | None = None
    calc_http_timeout_sec: float = 5.0
    product_summary_provider: str = "none"  # none | fake | openai
    product_summary_model: str = "gpt-4.1-mini"
    product_summary_temperature: float = 0.2
    product_summary_timeout_sec: int = 8
    text2sql_model: str = "gpt-4.1-mini"
    text2sql_temperature: float = 0.0
    text2sql_timeout_sec: int = 8
    text2sql_provider: str = "openai"  # openai | local | fake
    planner_llm_provider: str = "openai"
    planner_model: str = "gpt-4.1-mini"
    planner_temperature: float = 0.0
    planner_timeout_sec: int = 8
    planner_max_calls_per_turn: int = 4
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    render_frontend_origin: str | None = Field(default=None, alias="RENDER_FRONTEND_ORIGIN")
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_release: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_cors_origins(self) -> List[str]:
        """
        Returns the configured CORS origins plus the optional Render frontend origin, deduped.
        """
        normalized: list[str] = []

        def _append(origin: str | None) -> None:
            if not origin:
                return
            cleaned = origin.rstrip("/")
            if cleaned not in normalized:
                normalized.append(cleaned)

        for origin in self.cors_origins:
            _append(origin)

        _append(self.render_frontend_origin)
        return normalized


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()



