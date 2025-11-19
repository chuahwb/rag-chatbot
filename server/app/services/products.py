from __future__ import annotations

import asyncio
import inspect
from textwrap import dedent
from typing import Awaitable, Callable, Protocol, Sequence

from langchain_core.documents import Document

from app.core.config import AppSettings, get_settings
from app.core.langfuse import get_langchain_callbacks
from app.core.exceptions import AppError
from app.models.products import ProductHit, ProductSearchResponse


class ProductSearchError(AppError):
    status_code = 503
    error_type = "PRODUCT_INDEX_ERROR"


class ProductVectorStore(Protocol):
    def similarity_search_with_relevance_scores(  # pragma: no cover - protocol definition
        self, query: str, k: int
    ) -> Sequence[tuple[Document, float]]:
        ...


SummaryFn = Callable[[str, Sequence[Document]], Awaitable[str] | str]


class ProductSearchService:
    def __init__(
        self,
        vector_store: ProductVectorStore,
        summary_fn: SummaryFn | None = None,
        summary_context_k: int = 8,
    ) -> None:
        self._vector_store = vector_store
        self._summary_fn = summary_fn
        self._summary_context_k = max(1, summary_context_k)

    @classmethod
    def from_settings(cls, summary_fn: SummaryFn | None = None) -> "ProductSearchService":
        from langchain_community.embeddings.fake import FakeEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings

        settings = get_settings()

        provider = (settings.embeddings_provider or "openai").lower()

        if provider == "openai":
            if not settings.openai_api_key:
                raise ProductSearchError("OPENAI_API_KEY is not configured for product search.")
            embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=settings.openai_api_key,
            )
        elif provider in {"fake", "local"}:
            embeddings = FakeEmbeddings(size=1536)
        else:
            raise ProductSearchError(f"Unsupported embeddings provider: {provider}")

        try:
            vector_store = FAISS.load_local(
                settings.vector_store_path,
                embeddings,
                allow_dangerous_deserialization=True,
            )
        except (FileNotFoundError, RuntimeError, OSError) as exc:  # pragma: no cover - depends on runtime env
            raise ProductSearchError("Product vector store is not available.") from exc

        summary_callable = summary_fn if summary_fn is not None else cls._create_summary_fn(settings)

        return cls(vector_store=vector_store, summary_fn=summary_callable)

    async def search_async(self, query: str, *, k: int = 3) -> ProductSearchResponse:
        if not query.strip():
            raise AppError("Query cannot be empty.", details={"field": "query"})

        effective_k = max(k, self._summary_context_k)
        try:
            results = await asyncio.to_thread(
                self._vector_store.similarity_search_with_relevance_scores,
                query,
                k=effective_k,
            )
        except Exception as exc:  # pragma: no cover - protective guard
            raise ProductSearchError("Failed to query product index.") from exc

        results = self._apply_result_filters(results)

        hits = [self._document_to_hit(doc, score) for doc, score in results[:k]]
        summary = await self._summarize_async(query, [doc for doc, _ in results])

        return ProductSearchResponse(query=query, topK=hits, summary=summary)

    def search(self, query: str, *, k: int = 3) -> ProductSearchResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.search_async(query, k=k))

        raise RuntimeError("search() cannot be called from an active event loop; use search_async().")

    def _document_to_hit(self, doc: Document, score: float) -> ProductHit:
        metadata = doc.metadata or {}
        title = metadata.get("productTitle") or metadata.get("title") or metadata.get("name") or "Unknown product"
        variant_title = metadata.get("variantTitle")
        variant_id = metadata.get("variantId")
        url = metadata.get("productUrl") or metadata.get("url")
        price = _coerce_float(metadata.get("price"))
        compare_at_price = _coerce_float(metadata.get("compareAtPrice"))
        available = metadata.get("available")
        image_url = metadata.get("imageUrl")
        sku = metadata.get("sku")
        product_type = metadata.get("productType")
        tags_raw = metadata.get("tags") or []
        if isinstance(tags_raw, str):
            tags = [tags_raw]
        else:
            tags = list(tags_raw)
        snippet = doc.page_content.strip() if doc.page_content else None
        clipped_score = max(0.0, min(1.0, score))

        if snippet and len(snippet) > 400:
            snippet = snippet[:397] + "..."

        return ProductHit(
            title=title,
            variantTitle=variant_title,
            variantId=str(variant_id) if variant_id else None,
            score=clipped_score,
            url=url,
            price=price,
            compareAtPrice=compare_at_price,
            available=available,
            imageUrl=image_url,
            sku=sku,
            productType=product_type,
            tags=tags,
            snippet=snippet,
        )

    async def _summarize_async(self, query: str, documents: Sequence[Document]) -> str | None:
        if not self._summary_fn:
            return None

        try:
            result = self._summary_fn(query, documents)
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception:  # pragma: no cover - best-effort summary
            return None

    @staticmethod
    def _create_summary_fn(settings: AppSettings) -> SummaryFn | None:
        provider = (settings.product_summary_provider or "none").lower()

        if provider in {"", "none"}:
            return None

        if provider == "fake":
            async def summarize(query: str, documents: Sequence[Document]) -> str:
                return _fake_summary(query, documents)

            return summarize

        if provider == "openai":
            if not settings.openai_api_key:
                raise ProductSearchError("OPENAI_API_KEY is required for product summaries.")

            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI

            prompt = dedent(
                """
                You are a product specialist for ZUS Coffee drinkware.
                Answer the customer using only the supplied product context.
                Keep the reply to two concise sentences and mention product titles when relevant.
                Prices are in Malaysian Ringgit; format them like RM55 (no trailing decimals).
                When multiple variants or colors for the same product appear, mention that breadth even if only a few examples are shown.
                """
            ).strip()

            callbacks = get_langchain_callbacks(settings)

            chat = ChatOpenAI(
                model=settings.product_summary_model,
                temperature=settings.product_summary_temperature,
                api_key=settings.openai_api_key,
                callbacks=list(callbacks),
            )

            async def summarize(query: str, documents: Sequence[Document]) -> str:
                context = _build_summary_context(documents)
                if not context:
                    return ""
                messages = [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=dedent(
                            f"""
                            Customer question: {query}

                            Product context:
                            {context}

                            Provide a grounded answer. Cite product titles inline.
                            """
                        ).strip(),
                    ),
                ]
                response = await chat.ainvoke(
                    messages,
                    config={"timeout": settings.product_summary_timeout_sec},
                )
                return _normalize_message_content(response)

            return summarize

        raise ProductSearchError(f"Unsupported product summary provider: {provider}")

    def _apply_result_filters(
        self, results: Sequence[tuple[Document, float]]
    ) -> Sequence[tuple[Document, float]]:
        """
        Placeholder hook for future RAG guardrails (e.g., configurable score thresholds or
        semantic specificity checks). Currently returns results unchanged.
        """
        return results


def _coerce_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_message_content(result: object) -> str:
    if isinstance(result, str):
        return result.strip()

    attr = getattr(result, "content", None)
    if isinstance(attr, str):
        return attr.strip()

    if isinstance(attr, list):
        parts: list[str] = []
        for item in attr:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()

    return str(result or "").strip()


def _build_summary_context(documents: Sequence[Document], *, max_docs: int = 4, max_chars: int = 600) -> str:
    snippets: list[str] = []
    for index, doc in enumerate(documents):
        if index >= max_docs:
            break
        content = (doc.page_content or "").strip()
        if not content:
            continue
        if len(content) > max_chars:
            content = content[: max_chars - 3].rstrip() + "..."
        title = (
            doc.metadata.get("productTitle")
            or doc.metadata.get("title")
            or doc.metadata.get("name")
            or ""
        )
        header = f"Product: {title}\n" if title else ""
        snippets.append(f"{header}{content}")
    return "\n\n".join(snippets)


def _fake_summary(query: str, documents: Sequence[Document]) -> str:
    titles = []
    for doc in documents:
        title = doc.metadata.get("productTitle") or doc.metadata.get("title") or doc.metadata.get("name")
        if title:
            titles.append(str(title))
    if not titles:
        return ""
    joined = ", ".join(titles[:4])
    return f"Top matches for '{query}' include: {joined}."

