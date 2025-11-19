from __future__ import annotations

import json
import threading
from collections import deque
import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Optional, Protocol, Sequence, Tuple, Type, TypeVar

from pydantic import BaseModel

from app.core.config import AppSettings

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - optional dependency
    ChatOpenAI = None  # type: ignore[assignment]

try:
    from langchain_community.chat_models import ChatOllama
except ImportError:  # pragma: no cover - optional dependency
    ChatOllama = None  # type: ignore[assignment]


T_BaseModel = TypeVar("T_BaseModel", bound=BaseModel)


class PlannerLlmError(RuntimeError):
    """Raised when the planner LLM cannot complete a request."""


class PlannerLlm(Protocol):
    def invoke_structured(
        self,
        schema: Type[T_BaseModel],
        *,
        prompt: str,
        variables: dict[str, Any],
        prompt_id: str,
    ) -> T_BaseModel:
        ...

    async def invoke_structured_async(
        self,
        schema: Type[T_BaseModel],
        *,
        prompt: str,
        variables: dict[str, Any],
        prompt_id: str,
    ) -> T_BaseModel:
        ...


def _hash_variables(variables: dict[str, Any]) -> str:
    try:
        payload = json.dumps(variables, sort_keys=True, default=str)
    except TypeError as exc:  # pragma: no cover - defensive
        raise PlannerLlmError(f"Variables not JSON serializable: {variables}") from exc
    return payload


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass
class _CacheEntry:
    schema: Type[BaseModel]
    payload: dict[str, Any]


class _BasePlannerLlm:
    def __init__(self, *, cache_size: int = 64, callbacks: Sequence[Any] | None = None) -> None:
        self._cache_size = cache_size
        self._cache_lock = threading.RLock()
        self._cache: Dict[Tuple[str, str, str], _CacheEntry] = {}
        self._cache_order: Deque[Tuple[str, str, str]] = deque(maxlen=cache_size)
        self._callbacks = list(callbacks or [])

    def invoke_structured(
        self,
        schema: Type[T_BaseModel],
        *,
        prompt: str,
        variables: dict[str, Any],
        prompt_id: str,
    ) -> T_BaseModel:
        cache_key = (
            schema.__name__,
            prompt_id,
            f"{_hash_prompt(prompt)}:{_hash_variables(variables)}",
        )

        cached = self._lookup_cache(cache_key, schema)
        if cached is not None:
            return cached

        result_model = self._invoke_model(schema, prompt, variables)
        self._store_cache(cache_key, result_model)
        return result_model

    async def invoke_structured_async(
        self,
        schema: Type[T_BaseModel],
        *,
        prompt: str,
        variables: dict[str, Any],
        prompt_id: str,
    ) -> T_BaseModel:
        cache_key = (
            schema.__name__,
            prompt_id,
            f"{_hash_prompt(prompt)}:{_hash_variables(variables)}",
        )

        cached = self._lookup_cache(cache_key, schema)
        if cached is not None:
            return cached

        result_model = await self._invoke_model_async(schema, prompt, variables)
        self._store_cache(cache_key, result_model)
        return result_model

    def _lookup_cache(
        self,
        cache_key: Tuple[str, str, str],
        schema: Type[T_BaseModel],
    ) -> Optional[T_BaseModel]:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            self._touch(cache_key)
            return schema.model_validate(entry.payload)

    def _store_cache(self, cache_key: Tuple[str, str, str], result: BaseModel) -> None:
        payload = result.model_dump()
        with self._cache_lock:
            if cache_key not in self._cache and len(self._cache_order) >= self._cache_size:
                oldest = self._cache_order.popleft()
                self._cache.pop(oldest, None)
            self._cache[cache_key] = _CacheEntry(schema=type(result), payload=payload)
            self._touch(cache_key)

    def _touch(self, cache_key: Tuple[str, str, str]) -> None:
        try:
            self._cache_order.remove(cache_key)
        except ValueError:
            pass
        self._cache_order.append(cache_key)

    def _invoke_model(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        raise NotImplementedError  # pragma: no cover - implemented by subclasses

    async def _invoke_model_async(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        raise NotImplementedError  # pragma: no cover - implemented by subclasses


_fake_responses: Deque[dict[str, Any]] = deque()
_fake_lock = threading.RLock()


def queue_fake_response(payload: dict[str, Any]) -> None:
    with _fake_lock:
        _fake_responses.append(payload)


def clear_fake_responses() -> None:
    with _fake_lock:
        _fake_responses.clear()


class _FakePlannerLlm(_BasePlannerLlm):
    def _invoke_model(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        with _fake_lock:
            if not _fake_responses:
                raise PlannerLlmError("No fake responses queued for planner LLM")
            payload = _fake_responses.popleft()
        return schema.model_validate(payload)

    async def _invoke_model_async(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        return self._invoke_model(schema, formatted_prompt, variables)


class _OpenAiPlannerLlm(_BasePlannerLlm):
    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        timeout: int,
        api_key: str | None,
        cache_size: int = 64,
        callbacks: Sequence[Any] | None = None,
    ) -> None:
        super().__init__(cache_size=cache_size, callbacks=callbacks)
        if ChatOpenAI is None:  # pragma: no cover - optional dependency
            raise PlannerLlmError("langchain-openai is not installed.")
        client_kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "timeout": timeout,
        }
        if api_key:
            client_kwargs["api_key"] = api_key
        if self._callbacks:
            client_kwargs["callbacks"] = self._callbacks
        self._client = ChatOpenAI(**client_kwargs)
        self._timeout = timeout

    def _invoke_model(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        structured = self._client.with_structured_output(schema)
        return structured.invoke(formatted_prompt, config=self._config())

    async def _invoke_model_async(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        structured = self._client.with_structured_output(schema)
        return await structured.ainvoke(formatted_prompt, config=self._config())

    def _config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"timeout": self._timeout}
        if self._callbacks:
            config["callbacks"] = self._callbacks
        return config


class _LocalPlannerLlm(_BasePlannerLlm):
    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        timeout: int,
        host: str | None,
        cache_size: int = 64,
        callbacks: Sequence[Any] | None = None,
    ) -> None:
        super().__init__(cache_size=cache_size, callbacks=callbacks)
        if ChatOllama is None:  # pragma: no cover - optional dependency
            raise PlannerLlmError("langchain-community is not installed.")
        client_kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
        }
        if host:
            client_kwargs["base_url"] = host
        if self._callbacks:
            client_kwargs["callbacks"] = self._callbacks
        self._client = ChatOllama(**client_kwargs)
        self._timeout = timeout

    def _invoke_model(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        structured = self._client.with_structured_output(schema)
        return structured.invoke(formatted_prompt, config=self._config())

    async def _invoke_model_async(
        self,
        schema: Type[T_BaseModel],
        formatted_prompt: str,
        variables: dict[str, Any],
    ) -> T_BaseModel:
        structured = self._client.with_structured_output(schema)
        return await structured.ainvoke(formatted_prompt, config=self._config())

    def _config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"timeout": self._timeout}
        if self._callbacks:
            config["callbacks"] = self._callbacks
        return config


PlannerLlmFactory = Callable[[], PlannerLlm]


def get_planner_llm(
    settings: AppSettings, callbacks: Sequence[Any] | None = None
) -> PlannerLlmFactory:
    provider = settings.planner_llm_provider.lower()
    cache_size = 64
    callback_tuple: Tuple[Any, ...] = tuple(callbacks or ())

    if provider == "fake":
        return lambda: _FakePlannerLlm(cache_size=cache_size)

    if provider == "openai":
        return lambda: _OpenAiPlannerLlm(
            model=settings.planner_model,
            temperature=settings.planner_temperature,
            timeout=settings.planner_timeout_sec,
            api_key=settings.openai_api_key,
            cache_size=cache_size,
            callbacks=callback_tuple,
        )

    if provider == "local":
        return lambda: _LocalPlannerLlm(
            model=settings.planner_model,
            temperature=settings.planner_temperature,
            timeout=settings.planner_timeout_sec,
            host=settings.ollama_host,
            cache_size=cache_size,
            callbacks=callback_tuple,
        )

    raise PlannerLlmError(f"Unsupported planner LLM provider '{settings.planner_llm_provider}'")


__all__ = [
    "PlannerLlm",
    "PlannerLlmError",
    "PlannerLlmFactory",
    "clear_fake_responses",
    "get_planner_llm",
    "queue_fake_response",
]

