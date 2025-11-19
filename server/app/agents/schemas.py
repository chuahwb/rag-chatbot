from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


IntentLiteral = Literal["calc", "products", "outlets", "chitchat", "unknown"]
DecisionLiteral = Literal[
    "ask_follow_up",
    "call_calc",
    "call_products",
    "call_outlets",
    "respond_smalltalk",
]


class IntentResult(BaseModel):
    """Structured output for intent classification."""

    intent: IntentLiteral = Field(
        ...,
        description="Best matching intent for the turn.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score between 0 and 1.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short natural language justification for the decision.",
    )

    @field_validator("rationale")
    @classmethod
    def _strip_rationale(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class SlotResult(BaseModel):
    """Structured slot extraction per supported tool."""

    calcExpression: Optional[str] = Field(
        default=None,
        description="Arithmetic expression to evaluate for /calc intent.",
    )
    productQuery: Optional[str] = Field(
        default=None,
        description="Keywords or query for product search.",
    )
    outletArea: Optional[str] = Field(
        default=None,
        description="City, postcode, or area name for outlet lookup.",
    )
    outletName: Optional[str] = Field(
        default=None,
        description="Specific outlet name if provided.",
    )

    @field_validator("calcExpression", "productQuery", "outletArea", "outletName")
    @classmethod
    def _strip_fields(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else value


class DecisionResult(BaseModel):
    """Structured decision for the planner graph."""

    decision: DecisionLiteral = Field(
        ...,
        description="Next planner action.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short natural language justification for the decision.",
    )

    @field_validator("rationale")
    @classmethod
    def _strip_rationale(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class SynthesisResult(BaseModel):
    """Structured synthesis response grounded in tool output."""

    message: str = Field(
        ...,
        description="Final assistant utterance to return to the user.",
        min_length=1,
    )
    followUp: Optional[str] = Field(
        default=None,
        description="Optional follow-up question to keep the conversation going.",
    )

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        return value.strip()

    @field_validator("followUp")
    @classmethod
    def _strip_follow_up(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else value


class FollowUpResult(BaseModel):
    """Structured follow-up question for clarification turns."""

    question: str = Field(
        ...,
        min_length=1,
        description="Single clarifying question to ask the user.",
    )

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        return value.strip()


