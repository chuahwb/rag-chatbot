from __future__ import annotations

import os

from app.core.config import AppSettings


def clear_env(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("RENDER_FRONTEND_ORIGIN", raising=False)


def test_resolved_cors_origins_appends_render_origin(monkeypatch) -> None:
    clear_env(monkeypatch)
    render_origin = "https://rag-chatbot-web.onrender.com"
    monkeypatch.setenv("RENDER_FRONTEND_ORIGIN", render_origin)

    settings = AppSettings(_env_file=None)

    origins = settings.resolved_cors_origins
    assert "http://localhost:5173" in origins
    assert render_origin in origins


def test_resolved_cors_origins_deduplicates(monkeypatch) -> None:
    clear_env(monkeypatch)
    render_origin = "https://rag-chatbot-web.onrender.com"
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:5173", "https://rag-chatbot-web.onrender.com"]',
    )
    monkeypatch.setenv("RENDER_FRONTEND_ORIGIN", f"{render_origin}/")

    settings = AppSettings(_env_file=None)

    origins = settings.resolved_cors_origins
    assert origins.count(render_origin) == 1

