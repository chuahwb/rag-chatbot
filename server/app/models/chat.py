from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal

from pydantic import BaseModel, Field, model_validator

ChatRole = Literal["user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: ChatRole = Field(..., description="Message role within the conversation history.")
    content: str = Field(..., description="Message body content.")

    @model_validator(mode="after")
    def validate_content(self) -> "ChatMessage":
        if not self.content or not self.content.strip():
            raise ValueError("Message content cannot be empty.")
        return self


class ToolActionType(str, Enum):
    decision = "decision"
    tool_call = "tool_call"
    tool_result = "tool_result"


class ToolStatus(str, Enum):
    success = "success"
    error = "error"


class ToolAction(BaseModel):
    type: ToolActionType = Field(..., description="Type of planner action that occurred.")
    tool: Literal["calc", "products", "outlets"] | None = Field(
        None, description="Tool identifier when applicable."
    )
    args: dict[str, Any] | None = Field(
        default=None, description="Arguments supplied to the tool."
    )
    status: ToolStatus | None = Field(
        default=None, description="Outcome of a tool invocation."
    )
    data: Any | None = Field(
        default=None, description="Optional result payload attached to the action."
    )
    message: str | None = Field(
        default=None, description="Human-readable annotation for the action."
    )


class ChatRequest(BaseModel):
    sessionId: str = Field(..., min_length=1, description="Conversation session identifier.")
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Conversation history supplied by the client."
    )

    @model_validator(mode="after")
    def validate_messages(self) -> "ChatRequest":
        if not self.messages:
            raise ValueError("At least one user message is required.")
        if self.messages[-1].role != "user":
            raise ValueError("Last message in the request must come from the user.")
        return self


class ChatResponse(BaseModel):
    response: ChatMessage = Field(
        ..., description="Final assistant message returned for this turn."
    )
    actions: List[ToolAction] = Field(
        default_factory=list, description="Planner actions performed during the turn."
    )
    memory: dict[str, Any] = Field(
        default_factory=dict, description="Serialized conversation state for the session."
    )



