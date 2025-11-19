from __future__ import annotations

from app.agents.prompts import SYNTHESIS_PROMPT


def test_synthesis_prompt_mentions_core_capabilities():
    raw_text = SYNTHESIS_PROMPT.raw.lower()
    assert "calculator" in raw_text
    assert "drinkware" in raw_text or "product" in raw_text
    assert "outlet" in raw_text

