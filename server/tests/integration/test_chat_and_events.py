from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import clear_fake_responses, get_planner_llm, queue_fake_response
from app.agents.planner import create_planner
from app.api.routes.chat import get_chat_planner
from app.agents.events import event_broker
from app.models.products import ProductHit, ProductSearchResponse
from app.models.outlets import OutletsQueryResponse
from app.services.calculator import CalculatorResult
from app.main import create_app
from app.core.config import AppSettings


class StubCalculatorService:
    def evaluate(self, expression: str) -> CalculatorResult:
        return CalculatorResult(expression=expression, result=15)


class StubProductService:
    def search(self, query: str, k: int = 3) -> ProductSearchResponse:
        return ProductSearchResponse(
            query=query,
            topK=[
                ProductHit(
                    title="Steel Bottle",
                    variantTitle="Matte Black",
                    variantId="steel",
                    score=0.9,
                    url="https://example.com/steel",
                    price=79.0,
                    available=True,
                    snippet="Steel bottle keeps drinks cold.",
                )
            ],
            summary="Popular bottle.",
        )

    async def search_async(self, query: str, k: int = 3) -> ProductSearchResponse:
        return self.search(query, k=k)


class StubOutletsService:
    def query(self, user_query: str) -> OutletsQueryResponse:
        return OutletsQueryResponse(
            query=user_query,
            sql="SELECT * FROM outlets",
            params={},
            rows=[{"name": "ZUS Coffee SS 2", "open_time": "09:00", "close_time": "21:00"}],
        )

    async def query_async(self, user_query: str) -> OutletsQueryResponse:
        return self.query(user_query)


@pytest.fixture()
def client():
    app = create_app()
    calculator = StubCalculatorService()
    product_service = StubProductService()
    outlets_service = StubOutletsService()

    settings = AppSettings(
        planner_llm_provider="fake",
        planner_max_calls_per_turn=4,
    )
    llm_factory = get_planner_llm(settings)

    planner = create_planner(
        calculator_factory=lambda: calculator,
        products_factory=lambda: product_service,
        outlets_factory=lambda: outlets_service,
        llm_factory=llm_factory,
        max_llm_calls=settings.planner_max_calls_per_turn,
    )

    app.dependency_overrides[get_chat_planner] = lambda: planner

    with TestClient(app) as test_client:
        clear_fake_responses()
        yield test_client
        clear_fake_responses()


def test_chat_endpoint_returns_response(client: TestClient):
    clear_fake_responses()
    queue_fake_response({"intent": "calc"})
    queue_fake_response({"calcExpression": "5 + 10"})
    queue_fake_response({"decision": "call_calc"})
    queue_fake_response({"message": "The result for `5 + 10` is **15**."})
    payload = {
        "sessionId": "chat-session",
        "messages": [
            {"role": "user", "content": "What is 5 + 10?"}
        ],
    }

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["response"]["role"] == "assistant"
    assert "15" in body["response"]["content"]
    assert body["memory"]["sessionId"] == "chat-session"


def test_chat_endpoint_handles_follow_up(client: TestClient):
    clear_fake_responses()
    queue_fake_response({"intent": "products"})
    queue_fake_response({"productQuery": "drinkware"})
    queue_fake_response({"decision": "call_products"})
    queue_fake_response({"message": "Here are some drinkware options you might like."})
    payload = {
        "sessionId": "follow-up-session",
        "messages": [
            {"role": "user", "content": "Tell me about products"}
        ],
    }

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "drinkware" in body["response"]["content"].lower()
    assert body["actions"], "Expected planner actions to be returned."


def test_events_endpoint_streams_updates(client: TestClient):
    session_id = "events-session"

    event_data = {"type": "node_start", "node": "classify_intent", "timestamp": "now"}
    event_broker.publish(session_id, event_data)

    with client.stream(
        "GET",
        "/events",
        params={"sessionId": session_id, "maxEvents": 2},
    ) as stream:
        line_iter = stream.iter_lines()

        ready_payload = None
        for _ in range(10):
            try:
                line = next(line_iter)
            except StopIteration:
                break
            if not line:
                continue
            if line.startswith("data:"):
                ready_payload = json.loads(line.replace("data:", "").strip())
                break

        assert ready_payload is not None
        assert ready_payload.get("status") == "ready"

        payload = None
        for _ in range(10):
            try:
                line = next(line_iter)
            except StopIteration:
                break
            if not line or not line.startswith("data:"):
                continue
            candidate = json.loads(line.replace("data:", "").strip())
            if candidate.get("node") == "classify_intent":
                payload = candidate
                break

        assert payload is not None
        assert payload["node"] == "classify_intent"


def test_events_endpoint_includes_llm_calls(client: TestClient):
    session_id = "events-llm-session"
    clear_fake_responses()
    queue_fake_response({"intent": "products"})
    queue_fake_response({"productQuery": "tumbler"})
    queue_fake_response({"decision": "call_products"})
    queue_fake_response({"message": "Found tumbler options based on your request."})

    payload = {
        "sessionId": session_id,
        "messages": [
            {"role": "user", "content": "Show me tumbler options"}
        ],
    }

    response = client.post("/chat", json=payload)
    assert response.status_code == 200

    channel = event_broker._channels[session_id]
    backlog_llm_events = [event for event in channel.events if event["type"] == "llm_call"]
    assert backlog_llm_events, "Expected llm_call events in broker backlog."
    assert [event["data"]["status"] for event in backlog_llm_events] == [
        "success",
        "success",
        "success",
        "success",
    ]

    expected_events = len(channel.events) + 1  # include ready ping

    with client.stream(
        "GET",
        "/events",
        params={"sessionId": session_id, "maxEvents": expected_events},
    ) as stream:
        line_iter = stream.iter_lines()
        llm_events: list[dict[str, object]] = []

        for _ in range(50):
            try:
                line = next(line_iter)
            except StopIteration:
                break
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line.replace("data:", "").strip())
            if data.get("status") == "ready":
                continue
            if data.get("type") == "llm_call":
                llm_events.append(data)
                if len(llm_events) == 4:
                    break

    assert llm_events, "Expected llm_call events in SSE stream."
    assert [event["node"] for event in llm_events] == [
        "classify_intent",
        "extract_slots",
        "decide_action",
        "synthesize",
    ]
    assert [event["data"]["status"] for event in llm_events] == ["success", "success", "success", "success"]
    assert llm_events[-1]["data"]["remainingCalls"] == 0
    event_broker._channels.pop(session_id, None)


def test_outlets_follow_up_enriches_query(client: TestClient):
    session_id = "session-outlets-context"
    clear_fake_responses()
    # First turn: ask for outlets near Petaling Jaya
    queue_fake_response({"intent": "outlets"})
    queue_fake_response({"outletArea": "Petaling Jaya"})
    queue_fake_response({"decision": "call_outlets"})
    queue_fake_response({"message": "Here are some outlets near Petaling Jaya."})
    first_payload = {
        "sessionId": session_id,
        "messages": [
            {"role": "user", "content": "any outlets near Petaling Jaya?"}
        ],
    }

    first_response = client.post("/chat", json=first_payload)
    assert first_response.status_code == 200
    first_body = first_response.json()
    first_assistant = first_body["response"]

    # Second turn: follow-up question about the same outlets
    queue_fake_response({"intent": "outlets"})
    queue_fake_response({"outletArea": "Petaling Jaya"})
    queue_fake_response({"decision": "call_outlets"})
    queue_fake_response({"message": "These are their operating hours."})
    second_payload = {
        "sessionId": session_id,
        "messages": [
            {"role": "user", "content": "any outlets near Petaling Jaya?"},
            first_assistant,
            {"role": "user", "content": "what are their opening hours?"},
        ],
    }

    second_response = client.post("/chat", json=second_payload)
    assert second_response.status_code == 200
    second_body = second_response.json()

    tool_actions = [action for action in second_body["actions"] if action["tool"] == "outlets"]
    assert tool_actions, "Expected an outlets tool action."
    enriched_query = tool_actions[-1]["data"]["query"]
    assert "Previous outlets question: any outlets near Petaling Jaya?" in enriched_query
    assert "Previous assistant response" in enriched_query
    assert "Here are some outlets near Petaling Jaya." in enriched_query
    assert "ZUS Coffee SS 2" in enriched_query  # from StubOutletsService rows
    assert enriched_query.endswith("Follow-up question: what are their opening hours?")
