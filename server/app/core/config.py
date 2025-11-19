from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    api_title: str = "RAG Chatbot API"
    api_version: str = "0.1.0"

    openai_api_key: str | None = None
    ollama_host: str | None = None

    embeddings_provider: str = "openai"
    vector_store_path: str = "./data/faiss/products"
    sqlite_url: str = "sqlite:///./data/sqlite/outlets.db"
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
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_release: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()



