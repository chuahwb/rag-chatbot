from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.agents.events import event_broker
from app.agents.llm import get_planner_llm
from app.agents.planner import ChatPlanner, create_planner
from app.agents.memory import memory_store
from app.db.session import get_session
from app.models.chat import ChatRequest, ChatResponse
from app.services.calculator import CalculatorService
from app.services.calculator_http import CalculatorHttpService
from app.services.outlets import OutletsText2SQLService
from app.services.products import ProductSearchService
from app.core.config import get_settings
from app.core.langfuse import get_langchain_callbacks

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_planner(session: Session = Depends(get_session)) -> ChatPlanner:
    settings = get_settings()
    callbacks = tuple(get_langchain_callbacks(settings))
    llm_factory = get_planner_llm(settings, callbacks=callbacks)
    calculator_mode = settings.calc_tool_mode.lower()
    if calculator_mode == "http":
        calculator_factory = CalculatorHttpService.from_settings
    else:
        calculator_factory = CalculatorService
    return create_planner(
        calculator_factory=calculator_factory,
        products_factory=ProductSearchService.from_settings,
        outlets_factory=lambda: OutletsText2SQLService.from_session(session),
        llm_factory=llm_factory,
        max_llm_calls=settings.planner_max_calls_per_turn,
        callbacks=callbacks,
    )


@router.post("", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    planner: ChatPlanner = Depends(get_chat_planner),
) -> ChatResponse:
    return await planner.run_async(request)


@router.delete("/session/{session_id}", status_code=204)
async def reset_chat_session(session_id: str) -> Response:
    memory_store.clear(session_id)
    event_broker.clear(session_id)
    return Response(status_code=204)


