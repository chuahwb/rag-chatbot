from __future__ import annotations

from app.agents import prompts


def test_structured_prompt_renders_with_missing_variables() -> None:
    rendered = prompts.INTENT_PROMPT.render({"user_message": "Hello"})
    assert "Hello" in rendered
    assert "planner.intent.v1" not in rendered


def test_slot_prompt_includes_instructions() -> None:
    rendered = prompts.SLOT_PROMPT.render(
        {"user_message": "Find SS2 hours", "conversation": "User: Find SS2 hours"}
    )
    assert "outletArea" in rendered
    assert "Find SS2 hours" in rendered


def test_decision_prompt_formats_slots() -> None:
    rendered = prompts.DECISION_PROMPT.render(
        {"intent": "calc", "slots_json": '{"calcExpression": "3+4"}'}
    )
    assert "calcExpression" in rendered
    assert "3+4" in rendered


def test_synthesis_prompt_mentions_tool_summary() -> None:
    rendered = prompts.SYNTHESIS_PROMPT.render(
        {"conversation": "Tool responded", "tool_summary": "Calculated 3+4 = 7"}
    )
    assert "Calculated 3+4 = 7" in rendered


def test_decision_prompt_guides_vague_product_requests() -> None:
    rendered = prompts.DECISION_PROMPT.render(
        {"intent": "products", "slots_json": '{"productQuery": "drinkware info"}', "conversation": ""}
    )
    assert "generic" in rendered
    assert "ask_follow_up" in rendered


def test_synthesis_prompt_limits_follow_up_scope() -> None:
    rendered = prompts.SYNTHESIS_PROMPT.render({"conversation": "", "tool_summary": ""})
    assert "ordering" in rendered
    assert "calculator" in rendered


def test_follow_up_prompt_mentions_capabilities() -> None:
    rendered = prompts.FOLLOW_UP_PROMPT.render(
        {"intent": "products", "slots_json": "{}", "conversation": "User: drinkware info"}
    )
    text = rendered.lower()
    assert "calculator" in text
    assert "drinkware" in text
    assert "outlet" in text
    assert "ordering" in text  # reminder to avoid ordering guidance


def test_synthesis_prompt_mentions_aggregation_warning() -> None:
    rendered = prompts.SYNTHESIS_PROMPT.render({"conversation": "", "tool_summary": "Note: aggregation"})
    assert "aggregation" in rendered.lower()
    assert "exact" in rendered.lower()


def test_synthesis_prompt_mentions_privacy_and_internal_guardrails() -> None:
    raw_text = prompts.SYNTHESIS_PROMPT.raw.lower()
    # Should explicitly guard against leaking internal/system details and credentials.
    assert "api key" in raw_text or "token" in raw_text
    assert "stack trace" in raw_text or "internal error" in raw_text
    # Should explicitly avoid collecting highly sensitive personal data.
    assert "password" in raw_text
    assert "card number" in raw_text or "credit card" in raw_text


def test_follow_up_prompt_avoids_sensitive_data_questions() -> None:
    rendered = prompts.FOLLOW_UP_PROMPT.render(
        {"intent": "products", "slots_json": "{}", "conversation": "User: share my card number"}
    ).lower()
    # Template should clearly state that these are not to be requested.
    assert "card number" in rendered or "credit card" in rendered
    assert "password" in rendered

