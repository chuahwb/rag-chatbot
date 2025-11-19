from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, List, Optional

from langgraph.graph import END, START, StateGraph

from app.agents.events import event_broker
from app.agents.llm import PlannerLlmFactory
from app.agents.memory import memory_store
from app.agents.prompts import (
    DECISION_PROMPT,
    FOLLOW_UP_PROMPT,
    INTENT_PROMPT,
    SLOT_PROMPT,
    SYNTHESIS_PROMPT,
)
from app.agents.schemas import DecisionResult, FollowUpResult, IntentResult, SlotResult, SynthesisResult
from app.agents.state import ChatState, ErrorState, SlotState, ToolState
from app.models.chat import ChatMessage, ChatRequest, ChatResponse, ToolAction, ToolActionType, ToolStatus
from app.services.calculator import CalculatorError, CalculatorService
from app.services.outlets import OutletsExecutionError, OutletsQueryError, OutletsText2SQLService
from app.services.products import ProductSearchError, ProductSearchService

_PRODUCT_GENERIC_TOKENS = {
    "drinkware",
    "product",
    "products",
    "info",
    "information",
    "details",
    "options",
    "option",
    "catalog",
    "catalogue",
    "recommendation",
    "recommendations",
    "show",
    "list",
    "anything",
    "something",
    "ideas",
    "suggestions",
    "suggestion",
}

_PRODUCT_DESCRIPTOR_HINTS = {
    "tumbler",
    "tumblers",
    "cup",
    "cups",
    "mug",
    "mugs",
    "bottle",
    "bottles",
    "glass",
    "steel",
    "ceramic",
    "insulated",
    "thermal",
    "travel",
    "kids",
    "gift",
    "blue",
    "black",
    "matte",
    "gradient",
    "limited",
    "series",
    "edition",
    "set",
    "bundle",
    "handle",
    "strap",
    "sleeve",
    "corak",
    "malaysia",
    "marble",
    "double",
    "wall",
    "vacuum",
}

_PRODUCT_COMPARATOR_HINTS = {
    "under",
    "below",
    "over",
    "above",
    "less",
    "more",
    "cheaper",
    "expensive",
    "between",
    "around",
    "budget",
    "price",
}

class Intent(str, Enum):
    calc = "calc"
    products = "products"
    outlets = "outlets"
    chitchat = "chitchat"
    unknown = "unknown"


class Decision(str, Enum):
    ask_follow_up = "ask_follow_up"
    call_calc = "call_calc"
    call_products = "call_products"
    call_outlets = "call_outlets"
    respond_smalltalk = "respond_smalltalk"


class PlannerError(Exception):
    pass


def _timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _publish_event(session_id: str, event_type: str, node: str, data: dict[str, Any] | None = None) -> None:
    payload = {
        "sessionId": session_id,
        "type": event_type,
        "node": node,
        "timestamp": _timestamp(),
        "data": data or {},
    }
    event_broker.publish(session_id, payload)


@dataclass
class PlannerContext:
    calculator_factory: Callable[[], CalculatorService]
    products_factory: Callable[[], ProductSearchService]
    outlets_factory: Callable[[], OutletsText2SQLService]
    llm_factory: PlannerLlmFactory
    max_llm_calls: int
    callbacks: tuple[Any, ...] | None = None


@dataclass
class PlannerBudget:
    max_calls: int
    calls_used: int = 0

    def consume(self) -> bool:
        if self.calls_used >= self.max_calls:
            return False
        self.calls_used += 1
        return True

    @property
    def remaining(self) -> int:
        remaining = self.max_calls - self.calls_used
        return remaining if remaining > 0 else 0


class ChatPlanner:
    def __init__(self, context: PlannerContext) -> None:
        self._context = context
        self._llm = context.llm_factory()
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("classify_intent", self._node_classify_intent)
        graph.add_node("extract_slots", self._node_extract_slots)
        graph.add_node("decide_action", self._node_decide_action)
        graph.add_node("ask_follow_up", self._node_ask_follow_up)
        graph.add_node("call_calc", self._node_call_calc)
        graph.add_node("call_products", self._node_call_products)
        graph.add_node("call_outlets", self._node_call_outlets)
        graph.add_node("respond_smalltalk", self._node_respond_smalltalk)
        graph.add_node("synthesize", self._node_synthesize)

        graph.add_edge(START, "classify_intent")
        graph.add_edge("classify_intent", "extract_slots")
        graph.add_edge("extract_slots", "decide_action")

        graph.add_conditional_edges(
            "decide_action",
            self._conditional_route,
            {
                Decision.ask_follow_up.value: "ask_follow_up",
                Decision.call_calc.value: "call_calc",
                Decision.call_products.value: "call_products",
                Decision.call_outlets.value: "call_outlets",
                Decision.respond_smalltalk.value: "respond_smalltalk",
            },
        )

        graph.add_edge("ask_follow_up", END)
        graph.add_edge("call_calc", "synthesize")
        graph.add_edge("call_products", "synthesize")
        graph.add_edge("call_outlets", "synthesize")
        graph.add_edge("respond_smalltalk", "synthesize")
        graph.add_edge("synthesize", END)

        compiled = graph.compile()
        if self._context.callbacks:
            compiled = compiled.with_config({"callbacks": list(self._context.callbacks)})
        return compiled

    async def run_async(self, request: ChatRequest) -> ChatResponse:
        state = memory_store.get(request.sessionId)
        if state is None:
            state = ChatState(sessionId=request.sessionId, messages=list(request.messages))
        else:
            state.messages = list(request.messages)

        runtime_state = {
            "chat_state": state,
            "actions": [],
            "decision": None,
            "budget": PlannerBudget(self._context.max_llm_calls),
        }

        invoke_config: dict[str, Any] | None = None
        if self._context.callbacks:
            invoke_config = {"metadata": {"session_id": request.sessionId}}
        result_state = await self._graph.ainvoke(runtime_state, config=invoke_config)
        final_state: ChatState = result_state["chat_state"]
        memory_store.save(final_state)

        response_message = final_state.messages[-1]
        response = ChatResponse(
            response=response_message,
            actions=result_state.get("actions", []),
            memory=final_state.to_dict(),
        )
        return response

    def run(self, request: ChatRequest) -> ChatResponse:
        return asyncio.run(self.run_async(request))

    # Node implementations -------------------------------------------------

    async def _node_classify_intent(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        budget: PlannerBudget = state["budget"]

        _publish_event(chat_state.sessionId, "node_start", "classify_intent")
        intent = await self._classify_intent_with_llm(chat_state, budget)
        if intent is None:
            intent = Intent.unknown
        chat_state.intent = intent.value
        _publish_event(
            chat_state.sessionId,
            "decision",
            "classify_intent",
            {"intent": chat_state.intent},
        )
        _publish_event(chat_state.sessionId, "node_end", "classify_intent")
        return state

    async def _classify_intent_with_llm(
        self,
        chat_state: ChatState,
        budget: PlannerBudget,
    ) -> Optional[Intent]:
        node_name = "classify_intent"
        if not budget.consume():
            self._emit_llm_call(
                chat_state,
                node_name,
                INTENT_PROMPT.prompt_id,
                "skipped",
                budget,
                extra={"reason": "budget_exhausted"},
            )
            return None

        variables = {
            "conversation": self._format_conversation(chat_state.messages[:-1]),
            "user_message": chat_state.messages[-1].content,
        }
        prompt_text = INTENT_PROMPT.render(variables)
        start = time.perf_counter()
        try:
            result = await self._llm.invoke_structured_async(
                IntentResult,
                prompt=prompt_text,
                variables=variables,
                prompt_id=INTENT_PROMPT.prompt_id,
            )
            intent = Intent(result.intent)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._emit_llm_call(
                chat_state,
                node_name,
                INTENT_PROMPT.prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": str(exc)},
            )
            return None

        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_llm_call(
            chat_state,
            node_name,
            INTENT_PROMPT.prompt_id,
            "success",
            budget,
            latency_ms=latency_ms,
            extra={"intent": intent.value},
        )
        return intent

    @staticmethod
    def _format_conversation(messages: List[ChatMessage]) -> str:
        if not messages:
            return ""
        return "\n".join(f"{message.role}: {message.content.strip()}" for message in messages[-6:])

    def _emit_llm_call(
        self,
        chat_state: ChatState,
        node: str,
        prompt_id: str,
        status: str,
        budget: PlannerBudget,
        *,
        latency_ms: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "promptId": prompt_id,
            "status": status,
            "callsUsed": budget.calls_used,
            "maxCalls": budget.max_calls,
            "remainingCalls": budget.remaining,
        }
        if latency_ms is not None:
            payload["latencyMs"] = round(latency_ms, 2)
        if extra:
            payload.update(extra)
        _publish_event(chat_state.sessionId, "llm_call", node, payload)

    async def _synthesize_with_llm(
        self,
        chat_state: ChatState,
        budget: PlannerBudget,
    ) -> Optional[SynthesisResult]:
        node_name = "synthesize"
        if not budget.consume():
            self._emit_llm_call(
                chat_state,
                node_name,
                SYNTHESIS_PROMPT.prompt_id,
                "skipped",
                budget,
                extra={"reason": "budget_exhausted"},
            )
            return None

        variables = {
            "conversation": self._format_conversation(chat_state.messages),
            "intent": chat_state.intent,
            "slots_json": json.dumps(chat_state.slots.model_dump(), ensure_ascii=False),
            "tool_summary": self._build_tool_summary(chat_state),
        }
        prompt_text = SYNTHESIS_PROMPT.render(variables)
        start = time.perf_counter()
        try:
            result = await self._llm.invoke_structured_async(
                SynthesisResult,
                prompt=prompt_text,
                variables=variables,
                prompt_id=SYNTHESIS_PROMPT.prompt_id,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._emit_llm_call(
                chat_state,
                node_name,
                SYNTHESIS_PROMPT.prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": str(exc)},
            )
            return None

        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_llm_call(
            chat_state,
            node_name,
            SYNTHESIS_PROMPT.prompt_id,
            "success",
            budget,
            latency_ms=latency_ms,
        )
        return result

    @staticmethod
    def _build_tool_summary(chat_state: ChatState) -> str:
        parts: list[str] = []
        tools = chat_state.tools
        error = chat_state.error
        if chat_state.metadata.get("productAggregation"):
            parts.append(
                "Note: User asked for a product count/aggregate. Product search only returns a limited sample;"
                " do not claim an exact catalog-wide number."
            )

        if tools.lastTool:
            parts.append(f"Last tool: {tools.lastTool}")
        if tools.lastResult:
            parts.append(
                "Tool result:\n"
                + json.dumps(tools.lastResult, indent=2, ensure_ascii=False)
            )
        if error:
            parts.append(f"Error: {error.type} - {error.message}")
        if not parts:
            parts.append("No tool call yet; planner still needs information.")
        return "\n".join(parts)

    @staticmethod
    def _rule_based_message(chat_state: ChatState) -> str:
        tools = chat_state.tools
        error = chat_state.error

        if tools.lastTool == "calc" and tools.lastResult:
            result = tools.lastResult
            return f"The result for `{result['expression']}` is **{result['result']}**."
        if tools.lastTool == "products" and tools.lastResult:
            result = tools.lastResult
            top_hits = result.get("topK", [])
            if top_hits:
                titles = ", ".join(hit["title"] for hit in top_hits[:3])
                summary = result.get("summary")
                suffix = f" {summary}" if summary else ""
                return f"I found these drinkware options: {titles}.{suffix}"
            return "I couldn't find matching drinkware right now."
        if tools.lastTool == "outlets" and tools.lastResult:
            result = tools.lastResult
            rows = result.get("rows", [])
            if rows:
                first = rows[0]
                name = first.get("name") or "That outlet"
                open_time = first.get("open_time") or first.get("openTime")
                close_time = first.get("close_time") or first.get("closeTime")
                hours_text = ""
                if open_time and close_time:
                    hours_text = f" They open at {open_time} and close at {close_time}."
                return f"{name} is available.{hours_text}"
            return "I didn't find matching outlets."
        if error:
            return (
                "I'm the ZUS Coffee assistant for calculator checks, drinkware finds, "
                "and outlet guidance, but something went wrong "
                f"({error.type}). {error.message} Please try again or clarify your request."
            )
        return (
            "I'm the ZUS Coffee assistant who can use a calculator, suggest drinkware, "
            "and locate outlets. Could you share a bit more so I can point you to the right tool?"
        )

    async def _node_extract_slots(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        intent = Intent(chat_state.intent or Intent.unknown)
        budget: PlannerBudget = state["budget"]

        _publish_event(chat_state.sessionId, "node_start", "extract_slots")
        llm_slots = await self._extract_slots_with_llm(intent, chat_state, budget)
        if llm_slots is not None:
            chat_state.slots = llm_slots
        else:
            chat_state.slots = SlotState()
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "extract_slots",
            {"slots": chat_state.slots.model_dump()},
        )
        return state

    async def _extract_slots_with_llm(
        self,
        intent: Intent,
        chat_state: ChatState,
        budget: PlannerBudget,
    ) -> Optional[SlotState]:
        node_name = "extract_slots"
        if not budget.consume():
            self._emit_llm_call(
                chat_state,
                node_name,
                SLOT_PROMPT.prompt_id,
                "skipped",
                budget,
                extra={"reason": "budget_exhausted"},
            )
            return None

        variables = {
            "conversation": self._format_conversation(chat_state.messages[:-1]),
            "user_message": chat_state.messages[-1].content,
            "intent": intent.value,
        }
        prompt_text = SLOT_PROMPT.render(variables)
        start = time.perf_counter()
        try:
            result = await self._llm.invoke_structured_async(
                SlotResult,
                prompt=prompt_text,
                variables=variables,
                prompt_id=SLOT_PROMPT.prompt_id,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._emit_llm_call(
                chat_state,
                node_name,
                SLOT_PROMPT.prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": str(exc)},
            )
            return None

        data = result.model_dump(exclude_none=True)
        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_llm_call(
            chat_state,
            node_name,
            SLOT_PROMPT.prompt_id,
            "success",
            budget,
            latency_ms=latency_ms,
            extra={"slots": data},
        )
        if not data:
            return None
        return SlotState(**data)

    async def _decide_action_with_llm(
        self,
        intent: Intent,
        slots: SlotState,
        chat_state: ChatState,
        budget: PlannerBudget,
    ) -> Optional[Decision]:
        node_name = "decide_action"
        if not budget.consume():
            self._emit_llm_call(
                chat_state,
                node_name,
                DECISION_PROMPT.prompt_id,
                "skipped",
                budget,
                extra={"reason": "budget_exhausted"},
            )
            return None

        slots_payload = slots.model_dump()
        variables = {
            "intent": intent.value,
            "slots_json": json.dumps(slots_payload, ensure_ascii=False),
            "conversation": self._format_conversation(chat_state.messages),
        }
        prompt_text = DECISION_PROMPT.render(variables)
        start = time.perf_counter()
        try:
            result = await self._llm.invoke_structured_async(
                DecisionResult,
                prompt=prompt_text,
                variables=variables,
                prompt_id=DECISION_PROMPT.prompt_id,
            )
            decision = Decision(result.decision)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._emit_llm_call(
                chat_state,
                node_name,
                DECISION_PROMPT.prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": str(exc)},
            )
            return None

        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_llm_call(
            chat_state,
            node_name,
            DECISION_PROMPT.prompt_id,
            "success",
            budget,
            latency_ms=latency_ms,
            extra={"decision": decision.value},
        )
        return decision

    async def _node_decide_action(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        intent_value = chat_state.intent or Intent.unknown.value
        intent = Intent(intent_value)
        budget: PlannerBudget = state["budget"]
        _publish_event(chat_state.sessionId, "node_start", "decide_action")

        slots = chat_state.slots
        decision = await self._decide_action_with_llm(intent, slots, chat_state, budget)
        if decision is None:
            decision = Decision.ask_follow_up
        elif (
            intent == Intent.products
            and decision == Decision.call_products
            and self._needs_product_clarification(slots.productQuery)
        ):
            # Lightweight guardrail: defer to a follow-up when the product query lacks qualifiers.
            # Future enhancement: this is also where we could fan out to RAG-level heuristics
            # (e.g., score thresholds or semantic specificity checks) before issuing a search.
            decision = Decision.ask_follow_up
        elif intent == Intent.products and decision == Decision.call_products:
            is_aggregation = self._is_product_aggregation_query(chat_state.messages[-1].content)
            chat_state.metadata["productAggregation"] = is_aggregation

        state["decision"] = decision.value
        _publish_event(
            chat_state.sessionId,
            "decision",
            "decide_action",
            {"decision": decision.value},
        )
        _publish_event(chat_state.sessionId, "node_end", "decide_action")
        return state

    async def _node_ask_follow_up(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        _publish_event(chat_state.sessionId, "node_start", "ask_follow_up")
        intent = Intent(chat_state.intent or Intent.unknown.value)
        budget: PlannerBudget = state["budget"]
        prompt_status = ToolStatus.success
        prompt = await self._ask_follow_up_with_llm(intent, chat_state, budget)
        if not prompt:
            prompt = self._fallback_follow_up_prompt(intent)
        if not prompt:
            prompt = "Could you clarify what you need help with?"
            prompt_status = ToolStatus.error

        assistant_message = ChatMessage(role="assistant", content=prompt)
        chat_state.append_message(assistant_message)

        action = ToolAction(
            type=ToolActionType.decision,
            tool=None,
            status=prompt_status,
            message=prompt,
        )
        state.setdefault("actions", []).append(action)
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "ask_follow_up",
            {"message": prompt},
        )
        return state

    async def _node_call_calc(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        slots = chat_state.slots
        service = self._context.calculator_factory()

        _publish_event(chat_state.sessionId, "node_start", "call_calc", {"expression": slots.calcExpression})

        try:
            result = await asyncio.to_thread(service.evaluate, slots.calcExpression or "")
            chat_state.tools = ToolState(lastTool="calc", lastResult=result.model_dump())
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="calc",
                status=ToolStatus.success,
                data=result.model_dump(),
                message=f"Calculated `{result.expression}` successfully.",
            )
        except CalculatorError as exc:
            chat_state.error = ErrorState(type="calc_error", message=str(exc))
            chat_state.tools = ToolState(lastTool="calc", lastResult=None)
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="calc",
                status=ToolStatus.error,
                data={"error": str(exc)},
                message="Calculator failed.",
            )

        state.setdefault("actions", []).append(action)
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "call_calc",
            {"status": action.status.value if action.status else None},
        )
        return state

    async def _node_call_products(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        service = self._context.products_factory()
        query = chat_state.slots.productQuery or ""

        _publish_event(chat_state.sessionId, "node_start", "call_products", {"query": query})

        try:
            result = await service.search_async(query)
            chat_state.tools = ToolState(lastTool="products", lastResult=result.model_dump())
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="products",
                status=ToolStatus.success,
                data=result.model_dump(),
                message=f"Retrieved {len(result.topK)} product matches.",
            )
        except ProductSearchError as exc:
            chat_state.error = ErrorState(type="product_error", message=str(exc))
            chat_state.tools = ToolState(lastTool="products", lastResult=None)
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="products",
                status=ToolStatus.error,
                data={"error": str(exc)},
                message="Product search failed.",
            )

        state.setdefault("actions", []).append(action)
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "call_products",
            {"status": action.status.value if action.status else None},
        )
        return state

    async def _node_call_outlets(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        service = self._context.outlets_factory()
        raw_question = chat_state.messages[-1].content.strip()
        query = buildOutletsQueryFromContext(chat_state)

        _publish_event(chat_state.sessionId, "node_start", "call_outlets", {"query": query})

        try:
            result = await service.query_async(query)
            chat_state.tools = ToolState(lastTool="outlets", lastResult=result.model_dump())
            outlets_meta = chat_state.metadata.setdefault("outletsContext", {})
            outlets_meta["lastRawQuestion"] = raw_question
            outlets_meta["lastEnrichedQuery"] = query
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="outlets",
                status=ToolStatus.success,
                data=result.model_dump(),
                message=f"Fetched {len(result.rows)} outlets.",
            )
        except OutletsQueryError as exc:
            chat_state.error = ErrorState(type="outlet_query_error", message=str(exc))
            chat_state.tools = ToolState(lastTool="outlets", lastResult=None)
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="outlets",
                status=ToolStatus.error,
                data={"error": str(exc)},
                message="Outlet query rejected.",
            )
        except OutletsExecutionError as exc:
            chat_state.error = ErrorState(type="outlet_exec_error", message=str(exc))
            chat_state.tools = ToolState(lastTool="outlets", lastResult=None)
            action = ToolAction(
                type=ToolActionType.tool_result,
                tool="outlets",
                status=ToolStatus.error,
                data={"error": str(exc)},
                message="Outlet query failed.",
            )

        state.setdefault("actions", []).append(action)
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "call_outlets",
            {"status": action.status.value if action.status else None},
        )
        return state

    async def _node_respond_smalltalk(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        _publish_event(chat_state.sessionId, "node_start", "respond_smalltalk")

        state.setdefault("actions", []).append(
            ToolAction(
                type=ToolActionType.decision,
                tool=None,
                status=ToolStatus.success,
                message="Responded with small-talk guidance.",
                data={"decision": Decision.respond_smalltalk.value},
            )
        )
        _publish_event(chat_state.sessionId, "node_end", "respond_smalltalk")
        return state

    async def _node_synthesize(self, state: dict[str, Any]) -> dict[str, Any]:
        chat_state: ChatState = state["chat_state"]
        budget: PlannerBudget = state["budget"]
        _publish_event(chat_state.sessionId, "node_start", "synthesize")

        synthesis = await self._synthesize_with_llm(chat_state, budget)
        if synthesis is not None:
            response_text = synthesis.message
            if synthesis.followUp:
                response_text = f"{response_text}\n\n{synthesis.followUp}"
        else:
            response_text = self._rule_based_message(chat_state)

        message = ChatMessage(role="assistant", content=response_text)
        chat_state.append_message(message)
        _publish_event(
            chat_state.sessionId,
            "node_end",
            "synthesize",
            {"response": response_text},
        )
        return state

    def _conditional_route(self, state: dict[str, Any]) -> str:
        return state.get("decision", Decision.respond_smalltalk.value)

    async def _ask_follow_up_with_llm(
        self,
        intent: Intent,
        chat_state: ChatState,
        budget: PlannerBudget,
    ) -> Optional[str]:
        node_name = "ask_follow_up"
        prompt_id = FOLLOW_UP_PROMPT.prompt_id
        if not budget.consume():
            self._emit_llm_call(
                chat_state,
                node_name,
                prompt_id,
                "skipped",
                budget,
                extra={"reason": "budget_exhausted"},
            )
            return None

        variables = {
            "intent": intent.value,
            "slots_json": json.dumps(chat_state.slots.model_dump(), ensure_ascii=False),
            "conversation": self._format_conversation(chat_state.messages),
        }
        prompt_text = FOLLOW_UP_PROMPT.render(variables)
        start = time.perf_counter()
        try:
            result = await self._llm.invoke_structured_async(
                FollowUpResult,
                prompt=prompt_text,
                variables=variables,
                prompt_id=prompt_id,
            )
            question = result.question.strip()
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._emit_llm_call(
                chat_state,
                node_name,
                prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": str(exc)},
            )
            return None

        latency_ms = (time.perf_counter() - start) * 1000
        if not question:
            self._emit_llm_call(
                chat_state,
                node_name,
                prompt_id,
                "error",
                budget,
                latency_ms=latency_ms,
                extra={"error": "empty_follow_up"},
            )
            return None

        self._emit_llm_call(
            chat_state,
            node_name,
            prompt_id,
            "success",
            budget,
            latency_ms=latency_ms,
            extra={"question": question},
        )
        return question

    @staticmethod
    def _fallback_follow_up_prompt(intent: Intent) -> str:
        if intent == Intent.calc:
            return "I can help calculate it. Could you share the full expression?"
        if intent == Intent.products:
            return "Which drinkware item or style are you looking for?"
        if intent == Intent.outlets:
            return "Which outlet or area should I check?"
        return "Could you clarify what you need help with?"

    @staticmethod
    def _needs_product_clarification(query: Optional[str]) -> bool:
        if not query:
            return True
        normalized = re.sub(r"[^a-z0-9\s]", " ", query.lower()).strip()
        if not normalized:
            return True
        tokens = normalized.split()
        if any(char.isdigit() for char in normalized):
            return False
        if any(token in _PRODUCT_COMPARATOR_HINTS for token in tokens):
            return False
        if any(token in _PRODUCT_DESCRIPTOR_HINTS for token in tokens):
            return False
        if len(tokens) == 1:
            return tokens[0] in {
                "drinkware",
                "product",
                "products",
                "catalog",
                "catalogue",
            }
        if len(tokens) <= 4 and all(token in _PRODUCT_GENERIC_TOKENS for token in tokens):
            return True
        return False

    @staticmethod
    def _is_product_aggregation_query(message: str | None) -> bool:
        if not message:
            return False
        text = message.lower()
        aggregation_patterns = [
            r"\bhow\s+many\b",
            r"\bnumber\s+of\b",
            r"\bcount\b",
            r"\baverage\b",
            r"\bavg\b",
            r"\bminimum\b",
            r"\bmaximum\b",
            r"\bmin\b",
            r"\bmax\b",
            r"\bmost\b",
            r"\bleast\b",
        ]
        return any(re.search(pattern, text) for pattern in aggregation_patterns)


def buildOutletsQueryFromContext(chat_state: ChatState) -> str:
    """
    Build a natural-language outlets query enriched with prior tool and assistant context.
    """

    if not chat_state.messages:
        return ""

    latest_question = chat_state.messages[-1].content.strip()
    if not latest_question:
        return ""

    tools = chat_state.tools
    last_result = tools.lastResult if tools.lastTool == "outlets" else None

    previous_query = _get_previous_outlets_question(chat_state, last_result)
    rows: list[dict[str, Any]] = []
    if isinstance(last_result, dict):
        rows = last_result.get("rows") or []

    assistant_context = _get_last_assistant_summary(chat_state)

    if not previous_query and not rows and not assistant_context:
        return latest_question

    city_set: list[str] = []
    city_seen: set[str] = set()
    outlet_names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        city = str(row.get("city") or "").strip()
        name = str(row.get("name") or "").strip()
        if city:
            normalized_city = city.lower()
            if normalized_city not in city_seen:
                city_seen.add(normalized_city)
                city_set.append(city)
        if name and name not in outlet_names:
            outlet_names.append(name)
        if len(city_set) >= 3 and len(outlet_names) >= 3:
            break

    summary_bits: list[str] = []
    seen_sentences: set[str] = set()

    def add_sentence(prefix: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        sentence = f"{prefix}{text}"
        if not sentence.endswith("."):
            sentence = f"{sentence}."
        if sentence not in seen_sentences:
            seen_sentences.add(sentence)
            summary_bits.append(sentence)

    add_sentence("Previous outlets question: ", previous_query)
    add_sentence("Previous assistant response: ", assistant_context)
    if outlet_names:
        joined = ", ".join(outlet_names[:3])
        add_sentence("Previous results mentioned: ", joined)
    elif city_set:
        joined = ", ".join(city_set[:3])
        add_sentence("Previous results covered cities: ", joined)

    summary = " ".join(summary_bits).strip()
    if not summary:
        return latest_question

    return f"{summary} Follow-up question: {latest_question}"


def _get_last_assistant_summary(chat_state: ChatState, *, max_chars: int = 320) -> str:
    """
    Extract and truncate the most recent assistant reply before the latest user message.
    """

    if len(chat_state.messages) < 2:
        return ""

    for message in reversed(chat_state.messages[:-1]):
        if message.role == "assistant":
            summary = message.content.strip()
            if not summary:
                return ""
            if len(summary) <= max_chars:
                return summary
            truncated = summary[: max_chars - 3].rsplit(" ", 1)[0]
            return f"{truncated.strip()}..."
    return ""


def _get_previous_outlets_question(chat_state: ChatState, last_result: Any) -> str:
    outlets_meta = chat_state.metadata.get("outletsContext") or {}
    question = str(outlets_meta.get("lastRawQuestion") or "").strip()
    if question:
        return question
    if isinstance(last_result, dict):
        enriched_query = str(last_result.get("query") or "")
        inferred = _extract_follow_up_question(enriched_query)
        if inferred:
            return inferred
    return ""


def _extract_follow_up_question(enriched_query: str) -> str:
    if not enriched_query:
        return ""
    match = re.findall(r"Follow-up question:\s*(.+)", enriched_query, flags=re.IGNORECASE)
    if match:
        return match[-1].strip().rstrip(".")
    return enriched_query.strip()


def create_planner(
    *,
    calculator_factory: Callable[[], CalculatorService],
    products_factory: Callable[[], ProductSearchService],
    outlets_factory: Callable[[], OutletsText2SQLService],
    llm_factory: PlannerLlmFactory,
    max_llm_calls: int,
    callbacks: tuple[Any, ...] | None = None,
) -> ChatPlanner:
    context = PlannerContext(
        calculator_factory=calculator_factory,
        products_factory=products_factory,
        outlets_factory=outlets_factory,
        llm_factory=llm_factory,
        max_llm_calls=max_llm_calls,
        callbacks=callbacks,
    )
    return ChatPlanner(context)


