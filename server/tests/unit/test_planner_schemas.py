from __future__ import annotations

import pytest

from app.agents.schemas import (
    DecisionResult,
    IntentResult,
    SynthesisResult,
    SlotResult,
)


def test_intent_result_trims_rationale() -> None:
    result = IntentResult(intent="calc", rationale=" needs calc ")
    assert result.rationale == "needs calc"


def test_slot_result_trims_fields() -> None:
    slots = SlotResult(
        calcExpression=" 3 + 5 ",
        productQuery="   bottle ",
        outletArea=" ss2 ",
        outletName=" ZUS Curve ",
    )

    assert slots.calcExpression == "3 + 5"
    assert slots.productQuery == "bottle"
    assert slots.outletArea == "ss2"
    assert slots.outletName == "ZUS Curve"


def test_decision_result_requires_known_value() -> None:
    with pytest.raises(ValueError):
        DecisionResult(decision="unknown")  # type: ignore[arg-type]


def test_synthesis_result_trims_message() -> None:
    result = SynthesisResult(message="  Hello world.  ")
    assert result.message == "Hello world."


