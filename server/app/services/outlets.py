from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol

from langchain.prompts import PromptTemplate
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.langfuse import get_langchain_callbacks
from app.core.exceptions import AppError
from app.models.outlets import OutletsQueryResponse


class OutletsQueryError(AppError):
    status_code = 400
    error_type = "OUTLETS_QUERY_ERROR"


class OutletsExecutionError(AppError):
    status_code = 500
    error_type = "OUTLETS_EXECUTION_ERROR"


class SqlGenerator(Protocol):
    def __call__(self, query: str) -> tuple[str, dict[str, Any]]:
        ...


def default_sql_generator(session: Session) -> SqlGenerator:
    from langchain.chains import create_sql_query_chain
    from langchain_community.utilities import SQLDatabase
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    callbacks = get_langchain_callbacks(settings)
    provider = (settings.text2sql_provider or "openai").lower()
    db = SQLDatabase(session.bind)
    if provider == "fake":
        columns = "name, city, state, postal_code, address, open_time, close_time, services"

        def _normalize(text: str) -> str:
            lowered = text.lower()
            stripped = re.sub(r"[^a-z0-9\s]+", " ", lowered)
            return re.sub(r"\s+", " ", stripped).strip()

        def generate(query: str) -> tuple[str, dict[str, Any]]:
            normalized = _normalize(query)
            sql = f"SELECT {columns} FROM outlets"
            params: dict[str, Any] = {}
            where_clauses: list[str] = []

            def add_clause(field: str, value: str) -> None:
                index = len(where_clauses)
                param_key = f"{field}_param_{index}"
                where_clauses.append(f"LOWER({field}) LIKE :{param_key}")
                params[param_key] = f"%{value}%"

            token_aliases = {
                "ampang": ["ampang"],
                "ampang jaya": ["ampang jaya"],
                "bandar baru bangi": ["bandar baru bangi"],
                "bandar sunway": ["bandar sunway", "sunway"],
                "bangi": ["bangi"],
                "banting": ["banting"],
                "batang kali": ["batang kali"],
                "batu caves": ["batu caves"],
                "cheras": ["cheras"],
                "cyberjaya": ["cyberjaya"],
                "dengkil": ["dengkil"],
                "hulu langat": ["hulu langat"],
                "jenjarom": ["jenjarom"],
                "kajang": ["kajang"],
                "kapar": ["kapar"],
                "klang": ["klang", "port klang"],
                "klcc": ["klcc"],
                "klia": ["klia"],
                "kuala lumpur": ["kuala lumpur", "kualalumpur", "kl"],
                "kuala selangor": ["kuala selangor"],
                "petaling jaya": ["petaling jaya", "petalingjaya", "pj"],
                "port klang": ["port klang"],
                "puchong": ["puchong"],
                "putrajaya": ["putrajaya"],
                "rawang": ["rawang"],
                "sabak bernam": ["sabak bernam"],
                "sekinchan": ["sekinchan"],
                "semenyih": ["semenyih"],
                "sepang": ["sepang"],
                "seremban": ["seremban"],
                "serendah": ["serendah"],
                "seri kembangan": ["seri kembangan"],
                "shah alam": ["shah alam"],
                "ss2": ["ss2", "ss 2"],
                "subang": ["subang"],
                "subang jaya": ["subang jaya", "subangjaya"],
                "sungai buloh": ["sungai buloh"],
            }

            for canonical, variants in token_aliases.items():
                for variant in variants:
                    if variant in normalized:
                        add_clause("name", canonical)
                        add_clause("city", canonical)
                        break

            if where_clauses:
                sql = f"{sql} WHERE " + " OR ".join(where_clauses)
            sql += " ORDER BY name LIMIT 10"
            return sql, params

        return generate

    if provider == "local":
        try:
            from langchain_community.chat_models import ChatOllama
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OutletsExecutionError("langchain-community is required for local Text2SQL.") from exc

        kwargs: dict[str, Any] = {
            "model": settings.text2sql_model,
            "temperature": settings.text2sql_temperature,
        }
        if settings.ollama_host:
            kwargs["base_url"] = settings.ollama_host
        if callbacks:
            kwargs["callbacks"] = list(callbacks)
        llm = ChatOllama(**kwargs)
        prompt = _build_sql_prompt()
        chain = create_sql_query_chain(llm, db, prompt=prompt)

        def generate(query: str) -> tuple[str, dict[str, Any]]:
            enriched = _prepare_text2sql_question(query)
            sql = _normalize_generated_sql(chain.invoke({"question": enriched}))
            return sql, {}

        return generate

    if provider == "openai":
        if not settings.openai_api_key:
            raise OutletsExecutionError("OPENAI_API_KEY is not configured for outlets Text2SQL.")

        llm = ChatOpenAI(
            model=settings.text2sql_model,
            temperature=settings.text2sql_temperature,
            api_key=settings.openai_api_key,
            timeout=settings.text2sql_timeout_sec,
            callbacks=list(callbacks),
        )
        prompt = _build_sql_prompt()
        chain = create_sql_query_chain(llm, db, prompt=prompt)

        def generate(query: str) -> tuple[str, dict[str, Any]]:
            enriched = _prepare_text2sql_question(query)
            sql = _normalize_generated_sql(chain.invoke({"question": enriched}))
            return sql, {}

        return generate

    raise OutletsExecutionError(f"Unsupported text2sql provider: {settings.text2sql_provider}")


@dataclass
class OutletsText2SQLService:
    session: Session
    sql_generator: SqlGenerator

    UNSAFE_PATTERN = re.compile(r";|--|/\*|\*/|drop\s|delete\s|insert\s|update\s", re.IGNORECASE)
    MAX_ROWS = 20
    ALLOWED_COLUMNS = {
        "name",
        "city",
        "state",
        "postal_code",
        "address",
        "open_time",
        "close_time",
        "services",
    }

    @classmethod
    def from_session(cls, session: Session) -> "OutletsText2SQLService":
        generator = default_sql_generator(session)
        return cls(session=session, sql_generator=generator)

    async def query_async(self, user_query: str) -> OutletsQueryResponse:
        cleaned = user_query.strip()
        if not cleaned:
            raise OutletsQueryError("Query cannot be empty.", details={"field": "query"})

        sql, params = await asyncio.to_thread(self.sql_generator, cleaned)
        self._validate_sql(sql)

        try:
            rows = self._execute_sql(sql, params)
        except SQLAlchemyError as exc:
            raise OutletsExecutionError("Failed to execute outlet query.") from exc

        return OutletsQueryResponse(query=cleaned, sql=sql, params=params, rows=rows)

    def query(self, user_query: str) -> OutletsQueryResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.query_async(user_query))

        raise RuntimeError("query() cannot be called from an active event loop; use query_async().")

    def _validate_sql(self, sql: str) -> None:
        normalized = sql.strip()
        if not normalized:
            raise OutletsQueryError("Generated SQL was empty.", details={"sql": sql})

        # strip trailing semicolons
        normalized = normalized.rstrip()
        while normalized.endswith(";"):
            normalized = normalized[:-1].rstrip()

        if not normalized.lower().startswith("select "):
            raise OutletsQueryError(
                "Generated SQL must be a SELECT statement.", details={"sql": sql}
            )

        if self.UNSAFE_PATTERN.search(normalized):
            raise OutletsQueryError("Generated SQL was rejected for safety reasons.", details={"sql": sql})

    def _execute_sql(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        sql = sql.strip()
        if sql.endswith(";"):
            sql = sql[:-1]
        result = self.session.execute(text(sql), params)
        rows: list[dict[str, Any]] = []
        raw_keys = [key.lower() for key in result.keys()]
        for row in result.fetchall():
            filtered: dict[str, Any] = {}
            for key, value in zip(raw_keys, row):
                if key in self.ALLOWED_COLUMNS:
                    filtered[key] = value
            rows.append(filtered)
            if len(rows) >= self.MAX_ROWS:
                break
        return rows


def _prepare_text2sql_question(question: str) -> str:
    """
    Provide lightweight guidance to the LLM Text2SQL chain so it generates safe, useful SQL.
    """

    cleaned = question.strip() or "List outlets."
    normalized = re.sub(r"\s+", " ", cleaned)

    def replace_near(match: re.Match[str]) -> str:
        word = match.group(0)
        return "in" if word.lower().startswith("near") or word.lower() == "around" else word

    normalized = re.sub(r"\bnearby\b|\bnear\b|\baround\b", replace_near, normalized, flags=re.IGNORECASE)

    instructions = (
        "Use only the `outlets` table with the columns name, address, city, state, postal_code, open_time, "
        "close_time, services. Return a single SELECT statement that lists those columns explicitly and includes "
        "LIMIT 10."
    )

    return f"{instructions}\n\nUser question: {normalized}"


def _normalize_generated_sql(output: str) -> str:
    if not output:
        return output

    text = output.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        else:
            text = parts[-1]

    match = re.search(r"select\b", text, flags=re.IGNORECASE)
    if match:
        text = text[match.start():]

    return text.strip()


def _build_sql_prompt() -> PromptTemplate:
    template = """
You are an expert SQL generator for the ZUS Coffee outlets database.

Database schema:
{table_info}

Constraints:
- Return only a single SQL query starting with SELECT.
- Do not include explanations, comments, or code fences.
- Always list the columns explicitly (name, address, city, state, postal_code, open_time, close_time, services).
- Use LOWER(...) with LIKE '%value%' for fuzzy matching of names or cities.
- Always include LIMIT {top_k} at the end of the query.
- Never modify data (no INSERT/UPDATE/DELETE).

Question:
{input}

SQL Query:
"""
    return PromptTemplate.from_template(template.strip())


