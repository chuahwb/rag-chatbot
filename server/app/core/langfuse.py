from __future__ import annotations

from functools import lru_cache
import os
from typing import Any, Sequence, Tuple

from app.core.config import AppSettings

try:  # pragma: no cover - optional dependency
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
except ImportError:  # pragma: no cover - optional dependency
    Langfuse = None  # type: ignore[assignment]
    LangfuseCallbackHandler = None  # type: ignore[assignment]

LangchainCallbacks = Tuple[Any, ...]


class LangfuseNotInstalled(RuntimeError):
    """Raised when Langfuse is requested but the dependency is missing."""


def _build_langfuse_handler(
    public_key: str | None,
    secret_key: str | None,
    host: str | None,
    release: str | None,
) -> Any | None:
    if not public_key or not secret_key:
        return None
    if Langfuse is None or LangfuseCallbackHandler is None:  # pragma: no cover
        raise LangfuseNotInstalled(
            "Langfuse is not installed. Add `langfuse` to your requirements to enable tracing."
        )

    # Ensure process env contains the same values so Langfuse can reuse defaults.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    if host:
        os.environ.setdefault("LANGFUSE_HOST", host)
    if release:
        os.environ.setdefault("LANGFUSE_RELEASE", release)

    # Create/return a dedicated Langfuse client so the LangChain handler can reuse it.
    Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
        release=release,
    )

    return LangfuseCallbackHandler(public_key=public_key)


@lru_cache(maxsize=4)
def _cached_handler(
    public_key: str | None,
    secret_key: str | None,
    host: str | None,
    release: str | None,
) -> Any | None:
    return _build_langfuse_handler(public_key, secret_key, host, release)


def get_langchain_callbacks(settings: AppSettings) -> LangchainCallbacks:
    """Return LangChain callback handlers configured for Langfuse, if enabled."""

    handler = _cached_handler(
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
        settings.langfuse_release,
    )
    if handler is None:
        return tuple()
    return (handler,)


def as_list(callbacks: Sequence[Any] | None) -> list[Any]:
    """Utility to coerce callback tuples into mutable lists for LangChain APIs."""

    if not callbacks:
        return []
    if isinstance(callbacks, list):
        return callbacks
    return list(callbacks)

