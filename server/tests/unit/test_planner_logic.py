from __future__ import annotations

from app.agents.events import event_broker
from app.agents.llm import PlannerLlmError
from app.agents.planner import Intent, buildOutletsQueryFromContext, create_planner
from app.agents.schemas import DecisionResult, FollowUpResult, IntentResult, SlotResult, SynthesisResult
from app.agents.state import ChatState, ToolState
from app.models.chat import ChatMessage, ChatRequest, ToolStatus
from app.models.products import ProductHit, ProductSearchResponse
from app.models.outlets import OutletsQueryResponse
from app.services.calculator import CalculatorResult
from app.services.outlets import OutletsExecutionError
from app.services.products import ProductSearchError


class StubPlannerLlm:
    def __init__(self) -> None:
        self.responses: dict[type, list[dict[str, object]]] = {}
        self.calls: list[str] = []
        self.last_prompt_by_id: dict[str, str] = {}

    def queue_response(self, schema: type, payload: dict[str, object]) -> None:
        self.responses.setdefault(schema, []).append(payload)

    def invoke_structured(self, schema, *, prompt, variables, prompt_id):
        self.calls.append(prompt_id)
        self.last_prompt_by_id[prompt_id] = prompt
        queue = self.responses.get(schema)
        if queue:
            payload = queue.pop(0)
            return schema.model_validate(payload)
        raise PlannerLlmError(f"No stub response for schema={schema.__name__}")

    async def invoke_structured_async(self, schema, *, prompt, variables, prompt_id):
        return self.invoke_structured(schema, prompt=prompt, variables=variables, prompt_id=prompt_id)


class StubCalculatorService:
    def __init__(self, result: float = 42.0) -> None:
        self.result = result
        self.expressions: list[str] = []

    def evaluate(self, expression: str) -> CalculatorResult:
        self.expressions.append(expression)
        return CalculatorResult(expression=expression, result=self.result)


class StubProductService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, k: int = 3) -> ProductSearchResponse:
        self.queries.append(query)
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
            summary="A popular insulated bottle.",
        )

    async def search_async(self, query: str, k: int = 3) -> ProductSearchResponse:
        return self.search(query, k=k)


class StubOutletsService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, user_query: str) -> OutletsQueryResponse:
        self.queries.append(user_query)
        return OutletsQueryResponse(
            query=user_query,
            sql="SELECT * FROM outlets",
            params={},
            rows=[
                {"name": "ZUS Coffee SS 2", "open_time": "09:00", "close_time": "21:00"},
            ],
        )

    async def query_async(self, user_query: str) -> OutletsQueryResponse:
        return self.query(user_query)


def make_planner(
    *,
    calculator: StubCalculatorService | None = None,
    product_service: StubProductService | None = None,
    outlets_service: StubOutletsService | None = None,
    llm: StubPlannerLlm | None = None,
    max_llm_calls: int = 4,
):
    calculator = calculator or StubCalculatorService()
    product_service = product_service or StubProductService()
    outlets_service = outlets_service or StubOutletsService()
    llm = llm or StubPlannerLlm()

    planner = create_planner(
        calculator_factory=lambda: calculator,
        products_factory=lambda: product_service,
        outlets_factory=lambda: outlets_service,
        llm_factory=lambda: llm,
        max_llm_calls=max_llm_calls,
    )
    return planner, calculator, product_service, outlets_service, llm


def make_request(session_id: str, content: str) -> ChatRequest:
    return ChatRequest(
        sessionId=session_id,
        messages=[ChatMessage(role="user", content=content)],
    )


def test_planner_returns_calc_result():
    planner, calculator, _, _, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "calc"})
    llm.queue_response(SlotResult, {"calcExpression": "7*6"})
    llm.queue_response(DecisionResult, {"decision": "call_calc"})
    llm.queue_response(
        SynthesisResult,
        {"message": "The result for `7*6` is **42**."},
    )
    request = make_request("session-calc", "What is 7*6?")

    response = planner.run(request)

    assert response.response.role == "assistant"
    assert "42" in response.response.content
    assert calculator.expressions == ["7*6"]


def test_planner_prompts_for_missing_calc_expression():
    planner, calculator, _, _, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "calc"})
    llm.queue_response(SlotResult, {"calcExpression": None})
    llm.queue_response(DecisionResult, {"decision": "ask_follow_up"})
    llm.queue_response(
        SynthesisResult,
        {"message": "I can help calculate it. Could you share the full expression?"},
    )
    request = make_request("session-calc-missing", "Can you calculate something for me?")

    response = planner.run(request)

    assert "expression" in response.response.content.lower()
    assert calculator.expressions == []


def test_planner_routes_to_products_service():
    planner, _, product_service, _, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "Show me insulated bottles"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "I found insulated drinkware options that might suit you."},
    )
    request = make_request("session-products", "Show me insulated bottles")

    response = planner.run(request)

    assert "drinkware" in response.response.content.lower()
    assert product_service.queries == ["Show me insulated bottles"]


def test_planner_llm_generates_follow_up_for_generic_product_request():
    planner, _, product_service, _, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "drinkware product info"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(FollowUpResult, {"question": "Any preferred size or material for the drinkware?"})
    request = make_request("session-products-generic", "drinkware product info")

    response = planner.run(request)

    assert product_service.queries == []
    assert response.response.content == "Any preferred size or material for the drinkware?"


def test_planner_follow_up_falls_back_when_llm_errors():
    planner, _, product_service, _, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "drinkware product info"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    # Intentionally do NOT queue a FollowUpResult to force the helper to catch PlannerLlmError.
    request = make_request("session-products-generic-fallback", "drinkware product info")

    response = planner.run(request)

    assert product_service.queries == []
    assert response.response.content == "Which drinkware item or style are you looking for?"
    assert llm.calls.count("planner.follow_up.v1") == 1


def test_planner_follow_up_skipped_when_budget_exhausted():
    planner, _, product_service, _, llm = make_planner(max_llm_calls=3)
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "drinkware product info"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    request = make_request("session-products-generic-budget", "drinkware product info")

    response = planner.run(request)

    assert product_service.queries == []
    assert response.response.content == "Which drinkware item or style are you looking for?"
    assert llm.calls.count("planner.follow_up.v1") == 0


def test_planner_allows_constrained_product_request():
    planner, _, product_service, _, llm = make_planner()
    query = "How many drinkware products are below RM100?"
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": query})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Here are a few drinkware picks under RM100."},
    )
    request = make_request("session-products-specific", query)

    response = planner.run(request)

    assert product_service.queries == [query]
    assert "under rm100" in response.response.content.lower()
    assert response.memory["metadata"].get("productAggregation") is True


def test_product_aggregation_flag_not_set_for_descriptive_queries():
    planner, _, product_service, _, llm = make_planner()
    query = "Show me insulated bottles"
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": query})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Here are a few insulated picks."},
    )
    request = make_request("session-products-non-aggregation", query)

    response = planner.run(request)

    assert product_service.queries == [query]
    assert response.memory["metadata"].get("productAggregation") is not True


def test_planner_routes_to_outlets_service():
    planner, _, _, outlets_service, llm = make_planner()
    llm.queue_response(IntentResult, {"intent": "outlets"})
    llm.queue_response(SlotResult, {"outletArea": "SS2"})
    llm.queue_response(DecisionResult, {"decision": "call_outlets"})
    llm.queue_response(
        SynthesisResult,
        {"message": "ZUS Coffee SS 2 is open from 09:00 to 21:00."},
    )
    request = make_request("session-outlets", "What are the hours for SS2 outlet?")

    response = planner.run(request)

    assert "open" in response.response.content.lower()
    assert outlets_service.queries == ["What are the hours for SS2 outlet?"]


def test_classify_intent_prefers_llm_result():
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "random message with no keywords"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Here are some drinkware ideas based on your request."},
    )
    planner, _, product_service, _, _ = make_planner(llm=llm)
    request = make_request("session-llm", "random message with no keywords")

    response = planner.run(request)

    assert response.memory["intent"] == Intent.products.value
    assert product_service.queries == ["random message with no keywords"]


def test_classify_intent_falls_back_on_llm_failure():
    llm = StubPlannerLlm()
    # no response queued; stub raises PlannerLlmError
    planner, calculator, _, _, _ = make_planner(llm=llm)
    request = make_request("session-llm-fallback", "3 + 9")

    response = planner.run(request)

    assert response.memory["intent"] == Intent.unknown.value
    assert calculator.expressions == []


def test_extract_slots_prefers_llm_values():
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "calc"})
    llm.queue_response(SlotResult, {"calcExpression": "3+4"})
    llm.queue_response(DecisionResult, {"decision": "call_calc"})
    llm.queue_response(
        SynthesisResult,
        {"message": "The result for `3+4` is **7**."},
    )
    planner, calculator, _, _, _ = make_planner(llm=llm)
    request = make_request("session-llm-slots", "Please help me with this math problem.")

    response = planner.run(request)

    assert response.memory["slots"]["calcExpression"] == "3+4"
    assert calculator.expressions == ["3+4"]


def test_decide_action_prefers_llm_result():
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "calc"})
    llm.queue_response(SlotResult, {"calcExpression": "3+4"})
    llm.queue_response(DecisionResult, {"decision": "respond_smalltalk"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Sure thing! If you need help with math, just share the full expression."},
    )
    planner, calculator, _, _, _ = make_planner(llm=llm)
    request = make_request("session-llm-decision", "Please help me with this math problem.")

    response = planner.run(request)

    assert "small-talk" in response.actions[-1].message
    assert response.actions[-1].status == ToolStatus.success
    assert response.response.content == "Sure thing! If you need help with math, just share the full expression."
    assert calculator.expressions == []
    assert llm.calls[-2] == "planner.decision.v1"
    assert llm.calls[-1] == "planner.synthesis.v1"


def test_smalltalk_fallback_mentions_capabilities():
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "chitchat"})
    llm.queue_response(SlotResult, {})
    llm.queue_response(DecisionResult, {"decision": "respond_smalltalk"})
    # Intentionally omit a synthesis response to force the rule-based fallback.
    planner, _, _, _, _ = make_planner(llm=llm)
    request = make_request("session-smalltalk", "hey there")

    response = planner.run(request)

    content = response.response.content.lower()
    assert "calculator" in content
    assert "drinkware" in content or "product" in content
    assert "outlet" in content


def test_llm_call_events_include_budget_snapshot():
    session_id = "session-llm-events"
    event_broker._channels.pop(session_id, None)
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "tumbler"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Here are a few tumbler picks.", "followUp": "Want to see prices?"},
    )
    planner, _, product_service, _, _ = make_planner(llm=llm, max_llm_calls=4)
    request = make_request(session_id, "Looking for tumblers")

    planner.run(request)

    channel = event_broker._channels[session_id]
    llm_events = [event for event in channel.events if event["type"] == "llm_call"]

    assert [event["node"] for event in llm_events] == [
        "classify_intent",
        "extract_slots",
        "decide_action",
        "synthesize",
    ]
    assert [event["data"]["status"] for event in llm_events] == ["success", "success", "success", "success"]
    assert [event["data"]["callsUsed"] for event in llm_events] == [1, 2, 3, 4]
    assert llm_events[-1]["data"]["remainingCalls"] == 0
    assert product_service.queries == ["tumbler"]
    event_broker._channels.pop(session_id, None)


def test_llm_call_skipped_when_budget_exhausted():
    session_id = "session-llm-budget"
    event_broker._channels.pop(session_id, None)
    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "tumbler"})
    planner, _, product_service, _, _ = make_planner(llm=llm, max_llm_calls=2)
    request = make_request(session_id, "Looking for tumblers")

    planner.run(request)

    channel = event_broker._channels[session_id]
    llm_events = [event for event in channel.events if event["type"] == "llm_call"]

    assert [event["node"] for event in llm_events] == [
        "classify_intent",
        "extract_slots",
        "decide_action",
        "ask_follow_up",
    ]
    assert [event["data"]["status"] for event in llm_events] == [
        "success",
        "success",
        "skipped",
        "skipped",
    ]
    assert llm_events[-1]["data"]["reason"] == "budget_exhausted"
    assert product_service.queries == []
    event_broker._channels.pop(session_id, None)


def test_build_outlets_query_from_context_includes_previous_rows():
    chat_state = ChatState(
        sessionId="session-outlets-followup",
        messages=[
            ChatMessage(role="user", content="any outlets near Petaling Jaya?"),
            ChatMessage(
                role="assistant",
                content="There are several outlets near Petaling Jaya. Do you want opening hours?",
            ),
            ChatMessage(role="user", content="what are their opening hours?"),
        ],
        metadata={"outletsContext": {"lastRawQuestion": "any outlets near Petaling Jaya?"}},
        tools=ToolState(
            lastTool="outlets",
            lastResult={
                "query": "any outlets near Petaling Jaya?",
                "rows": [
                    {"name": "ZUS Coffee SS 2", "city": "Petaling Jaya"},
                    {"name": "ZUS Coffee Uptown", "city": "Petaling Jaya"},
                ],
            },
        ),
    )

    enriched = buildOutletsQueryFromContext(chat_state)

    assert "Previous outlets question: any outlets near Petaling Jaya?" in enriched
    assert "Previous assistant response" in enriched
    assert "Do you want opening hours?" in enriched
    assert "ZUS Coffee SS 2" in enriched
    assert enriched.endswith("Follow-up question: what are their opening hours?")


def test_build_outlets_query_from_context_without_prior_result_returns_latest():
    chat_state = ChatState(
        sessionId="session-outlets-single",
        messages=[ChatMessage(role="user", content="any outlets near Damansara?")],
    )

    enriched = buildOutletsQueryFromContext(chat_state)

    assert enriched == "any outlets near Damansara?"


def test_build_outlets_query_sanitizes_enriched_previous_query():
    noisy_query = (
        "Previous outlets question: previous question here. "
        "Previous assistant response: some response. Follow-up question: any outlets near Bangsar?"
    )
    chat_state = ChatState(
        sessionId="session-outlets-sanitize",
        messages=[
            ChatMessage(role="user", content="any outlets near Bangsar?"),
            ChatMessage(role="assistant", content="Listing outlets..."),
            ChatMessage(role="user", content="what about their opening hours?"),
        ],
        tools=ToolState(
            lastTool="outlets",
            lastResult={
                "query": noisy_query,
                "rows": [],
            },
        ),
    )

    enriched = buildOutletsQueryFromContext(chat_state)

    assert enriched.count("Previous outlets question: ") == 1
    assert "any outlets near Bangsar?" in enriched


class FailingProductService(StubProductService):
    def search(self, query: str, k: int = 3) -> ProductSearchResponse:  # type: ignore[override]
        raise ProductSearchError("Index offline.")

    async def search_async(self, query: str, k: int = 3) -> ProductSearchResponse:  # type: ignore[override]
        raise ProductSearchError("Index offline.")


def test_planner_surfaces_product_error():
    failing_product_service = FailingProductService()
    planner, _, _, _, llm = make_planner(product_service=failing_product_service)
    llm.queue_response(IntentResult, {"intent": "products"})
    llm.queue_response(SlotResult, {"productQuery": "tumbler"})
    llm.queue_response(DecisionResult, {"decision": "call_products"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Product search is currently unavailable. Please try again later."},
    )
    request = make_request("session-product-error", "Show me tumblers")

    response = planner.run(request)

    assert response.actions[-1].tool == "products"
    assert response.actions[-1].status == ToolStatus.error
    assert response.memory["error"]["type"] == "product_error"
    assert "unavailable" in response.response.content.lower()


class FailingOutletsService(StubOutletsService):
    def query(self, user_query: str) -> OutletsQueryResponse:  # type: ignore[override]
        raise OutletsExecutionError("Database offline.")

    async def query_async(self, user_query: str) -> OutletsQueryResponse:  # type: ignore[override]
        raise OutletsExecutionError("Database offline.")


def test_planner_surfaces_outlet_execution_error():
    failing_outlets_service = FailingOutletsService()
    planner, _, _, _, llm = make_planner(outlets_service=failing_outlets_service)
    llm.queue_response(IntentResult, {"intent": "outlets"})
    llm.queue_response(SlotResult, {"outletArea": "SS2"})
    llm.queue_response(DecisionResult, {"decision": "call_outlets"})
    llm.queue_response(
        SynthesisResult,
        {"message": "Outlet lookup had an issue. Please try again later."},
    )
    request = make_request("session-outlet-error", "Find SS2 hours")

    response = planner.run(request)

    assert response.actions[-1].tool == "outlets"
    assert response.actions[-1].status == ToolStatus.error
    assert response.memory["error"]["type"] == "outlet_exec_error"
    assert "issue" in response.response.content.lower()


def test_tool_summary_redacts_outlet_sql_from_llm_prompt():
    session_id = "session-outlets-redact-sql"
    event_broker._channels.pop(session_id, None)

    llm = StubPlannerLlm()
    llm.queue_response(IntentResult, {"intent": "outlets"})
    llm.queue_response(SlotResult, {"outletArea": "SS2"})
    llm.queue_response(DecisionResult, {"decision": "call_outlets"})
    llm.queue_response(
        SynthesisResult,
        {"message": "ZUS Coffee SS 2 is open from 09:00 to 21:00."},
    )

    class StubOutletsServiceWithSql(StubOutletsService):
        def query(self, user_query: str) -> OutletsQueryResponse:  # type: ignore[override]
            self.queries.append(user_query)
            return OutletsQueryResponse(
                query=user_query,
                sql="SELECT * FROM outlets; -- internal",
                params={"secret": "value"},
                rows=[
                    {"name": "ZUS Coffee SS 2", "open_time": "09:00", "close_time": "21:00"},
                ],
            )

        async def query_async(self, user_query: str) -> OutletsQueryResponse:  # type: ignore[override]
            return self.query(user_query)

    outlets_service = StubOutletsServiceWithSql()
    planner, _, _, _, _ = make_planner(outlets_service=outlets_service, llm=llm)
    request = make_request(session_id, "What are the hours for SS2 outlet?")

    response = planner.run(request)

    # Ensure the tool was called as normal.
    assert outlets_service.queries == ["What are the hours for SS2 outlet?"]
    assert "open" in response.response.content.lower()

    # The synthesis prompt should not expose raw SQL or params back to the LLM.
    synthesis_prompt = llm.last_prompt_by_id.get("planner.synthesis.v1", "")
    assert "select * from outlets" not in synthesis_prompt.lower()
    assert "secret" not in synthesis_prompt.lower()
