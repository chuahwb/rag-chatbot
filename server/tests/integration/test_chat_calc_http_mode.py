from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import clear_fake_responses, queue_fake_response
from app.agents.memory import memory_store
from app.core.config import get_settings
from app.main import create_app
from app.models.calculator import CalculatorResult


class StubCalculatorHttpService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate(self, expression: str) -> CalculatorResult:
        self.calls.append(expression)
        return CalculatorResult(expression=expression, result=25)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CALC_TOOL_MODE", "http")
    monkeypatch.setenv("CALC_HTTP_BASE_URL", "http://calc.internal")
    monkeypatch.setenv("PLANNER_LLM_PROVIDER", "fake")
    get_settings.cache_clear()

    stub_service = StubCalculatorHttpService()
    monkeypatch.setattr(
        "app.services.calculator_http.CalculatorHttpService.from_settings",
        lambda: stub_service,
    )

    app = create_app()

    with TestClient(app) as test_client:
        yield test_client, stub_service

    clear_fake_responses()
    memory_store.clear("http-calc-session")
    get_settings.cache_clear()


def test_chat_uses_http_calculator(client):
    test_client, stub_service = client
    clear_fake_responses()
    queue_fake_response({"intent": "calc"})
    queue_fake_response({"calcExpression": "5+10"})
    queue_fake_response({"decision": "call_calc"})
    queue_fake_response({"message": "The result is 15."})

    payload = {
        "sessionId": "http-calc-session",
        "messages": [{"role": "user", "content": "Calculate 5+10"}],
    }

    response = test_client.post("/chat", json=payload)

    assert response.status_code == 200
    assert stub_service.calls == ["5+10"]


