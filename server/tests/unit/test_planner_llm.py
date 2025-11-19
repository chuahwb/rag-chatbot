from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.llm import clear_fake_responses, get_planner_llm, queue_fake_response
from app.core.config import AppSettings


class ExampleSchema(BaseModel):
    value: str


def setup_function() -> None:
    clear_fake_responses()


def test_app_settings_defaults_include_planner_fields() -> None:
    settings = AppSettings()

    assert settings.planner_llm_provider
    assert settings.planner_model
    assert settings.planner_timeout_sec > 0
    assert settings.planner_max_calls_per_turn > 0
    assert settings.product_summary_model
    assert settings.product_summary_timeout_sec > 0
    assert settings.text2sql_model
    assert settings.text2sql_timeout_sec > 0


def test_fake_llm_returns_enqueued_response() -> None:
    settings = AppSettings(planner_llm_provider="fake")
    factory = get_planner_llm(settings)
    queue_fake_response({"value": "first"})

    llm = factory()
    result = llm.invoke_structured(
        ExampleSchema,
        prompt="fake prompt",
        variables={"foo": "bar"},
        prompt_id="intent",
    )

    assert result.value == "first"


def test_fake_llm_caches_results_by_prompt_id_and_vars() -> None:
    settings = AppSettings(planner_llm_provider="fake")
    factory = get_planner_llm(settings)
    queue_fake_response({"value": "cached"})

    llm = factory()
    first = llm.invoke_structured(
        ExampleSchema,
        prompt="cache me",
        variables={"foo": "bar"},
        prompt_id="intent",
    )
    second = llm.invoke_structured(
        ExampleSchema,
        prompt="cache me",
        variables={"foo": "bar"},
        prompt_id="intent",
    )

    assert first.value == "cached"
    assert second.value == "cached"


def test_fake_llm_cache_scoped_by_prompt_id() -> None:
    settings = AppSettings(planner_llm_provider="fake")
    factory = get_planner_llm(settings)
    queue_fake_response({"value": "intent"})
    queue_fake_response({"value": "slots"})

    llm = factory()
    first = llm.invoke_structured(
        ExampleSchema,
        prompt="prompt one",
        variables={"foo": "bar"},
        prompt_id="intent",
    )
    second = llm.invoke_structured(
        ExampleSchema,
        prompt="prompt two",
        variables={"foo": "bar"},
        prompt_id="slots",
    )

    assert first.value == "intent"
    assert second.value == "slots"


@pytest.mark.asyncio
async def test_fake_llm_async_invocation_returns_enqueued_response() -> None:
    settings = AppSettings(planner_llm_provider="fake")
    factory = get_planner_llm(settings)
    queue_fake_response({"value": "async-first"})

    llm = factory()
    result = await llm.invoke_structured_async(
        ExampleSchema,
        prompt="async prompt",
        variables={"foo": "bar"},
        prompt_id="intent",
    )

    assert result.value == "async-first"

