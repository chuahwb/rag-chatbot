from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.chat import ChatMessage


class SlotState(BaseModel):
    calcExpression: Optional[str] = Field(default=None)
    outletArea: Optional[str] = Field(default=None)
    outletName: Optional[str] = Field(default=None)
    productQuery: Optional[str] = Field(default=None)


class ToolState(BaseModel):
    lastTool: Optional[str] = Field(default=None)
    lastResult: Any | None = Field(default=None)


class ErrorState(BaseModel):
    type: str = Field(..., description="Normalized error type.")
    message: str = Field(..., description="User-facing error message.")


class ChatState(BaseModel):
    sessionId: str = Field(..., description="Session identifier for the conversation.")
    messages: List[ChatMessage] = Field(default_factory=list)
    intent: Optional[str] = Field(default=None)
    slots: SlotState = Field(default_factory=SlotState)
    tools: ToolState = Field(default_factory=ToolState)
    error: Optional[ErrorState] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def append_message(self, message: ChatMessage) -> None:
        self.messages.append(message)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()



