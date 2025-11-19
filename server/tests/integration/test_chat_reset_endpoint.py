from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import clear_fake_responses, get_planner_llm, queue_fake_response
from app.agents.events import event_broker
from app.agents.memory import memory_store
from app.agents.planner import create_planner
from app.api.routes.chat import get_chat_planner
from app.core.config import AppSettings, get_settings
from app.main import create_app
from app.models.products import ProductHit, ProductSearchResponse
from app.models.outlets import OutletsQueryResponse
from app.services.calculator import CalculatorResult


class StubCalculatorService:
    def evaluate(self, expression: str) -> CalculatorResult:
        return CalculatorResult(expression=expression, result=42)


class StubProductService:
    async def search_async(self, query: str, k: int = 3) -> ProductSearchResponse:
        return ProductSearchResponse(
            query=query,
            topK=[
                ProductHit(
                    title="Steel Bottle",
                    variantTitle="Matte Black",
                    score=0.9,
                    url="https://example.com/steel",
                    price=79.0,
                    available=True,
                    snippet="Steel bottle keeps drinks cold.",
                )
            ],
            summary="Popular bottle.",
        )


class StubOutletsService:
    async def query_async(self, user_query: str) -> OutletsQueryResponse:
        return OutletsQueryResponse(
            query=user_query,
            sql="SELECT name FROM outlets",
            params={},
            rows=[{"name": "ZUS Coffee SS 2"}],
        )


@pytest.fixture()
def client(monkeypatch):
    clear_fake_responses()
    monkeypatch.setenv("PLANNER_LLM_PROVIDER", "fake")
    monkeypatch.setenv("CALC_TOOL_MODE", "local")
    get_settings.cache_clear()

    app = create_app()

    calculator = StubCalculatorService()
    product_service = StubProductService()
    outlet_service = StubOutletsService()

    settings = AppSettings(planner_llm_provider="fake", planner_max_calls_per_turn=4)
    llm_factory = get_planner_llm(settings)

    planner = create_planner(
        calculator_factory=lambda: calculator,
        products_factory=lambda: product_service,
        outlets_factory=lambda: outlet_service,
        llm_factory=llm_factory,
        max_llm_calls=settings.planner_max_calls_per_turn,
    )

    app.dependency_overrides[get_chat_planner] = lambda: planner

    with TestClient(app) as test_client:
        yield test_client

    memory_store.clear("reset-session")
    clear_fake_responses()
    get_settings.cache_clear()


def test_reset_endpoint_clears_memory(client: TestClient, monkeypatch):
    session_id = "reset-session"
    memory_store.clear(session_id)
    clear_fake_responses()
    queue_fake_response({"intent": "calc"})
    queue_fake_response({"calcExpression": "5+5"})
    queue_fake_response({"decision": "call_calc"})
    queue_fake_response({"message": "The result is 10."})

    payload = {
        "sessionId": session_id,
        "messages": [{"role": "user", "content": "What is 5+5?"}],
    }

    cleared_counts: list[int] = []
    original_clear = event_broker.clear

    def spy_clear(target_session: str) -> int:
        cleared = original_clear(target_session)
        cleared_counts.append(cleared)
        return cleared

    monkeypatch.setattr(event_broker, "clear", spy_clear)

    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    assert memory_store.get(session_id) is not None

    event_broker.publish(session_id, {"type": "node_start", "node": "classify_intent"})

    reset_response = client.delete(f"/chat/session/{session_id}")
    assert reset_response.status_code == 204
    assert memory_store.get(session_id) is None
    assert cleared_counts, "event_broker.clear was not invoked"
    assert cleared_counts[-1] >= 1


