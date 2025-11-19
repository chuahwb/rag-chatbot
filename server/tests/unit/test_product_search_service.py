import pytest
from langchain_core.documents import Document

from app.core.config import AppSettings
from app.core.exceptions import AppError
from app.services.products import ProductSearchError, ProductSearchService


class StubVectorStore:
    def __init__(self, results: list[tuple[Document, float]]):
        self._results = results
        self.last_query = None
        self.last_k = None

    def similarity_search_with_relevance_scores(self, query: str, k: int):
        self.last_query = query
        self.last_k = k
        return self._results[:k]


def test_search_returns_hits_and_summary():
    docs = [
        (
            Document(
                page_content="Stainless steel bottle with 500ml capacity and leak-proof lid.",
                metadata={
                    "productTitle": "Steel Bottle 500ml",
                    "variantTitle": "Matte Black",
                    "productUrl": "https://example.com/steel",
                    "price": "79.0",
                    "compareAtPrice": "99.0",
                    "available": True,
                    "productType": "Tumbler",
                    "tags": ["tumbler", "stainless"],
                },
            ),
            0.92,
        ),
        (
            Document(
                page_content="Glass tumbler includes silicone sleeve for grip.",
                metadata={
                    "productTitle": "Glass Tumbler",
                    "variantTitle": "Frosted",
                    "productUrl": "https://example.com/glass",
                    "price": "59.0",
                    "available": False,
                    "productType": "Tumbler",
                },
            ),
            0.78,
        ),
    ]
    store = StubVectorStore(results=docs)

    def summary_fn(query: str, retrieved_docs):
        assert query == "insulated bottle"
        assert len(retrieved_docs) == 2
        return "Top results include insulated stainless steel options."

    service = ProductSearchService(vector_store=store, summary_fn=summary_fn)

    response = service.search("insulated bottle", k=2)

    assert response.query == "insulated bottle"
    assert len(response.topK) == 2
    assert response.topK[0].title == "Steel Bottle 500ml"
    assert response.topK[0].variantTitle == "Matte Black"
    assert response.topK[0].price == 79.0
    assert response.topK[0].compareAtPrice == 99.0
    assert response.topK[0].available is True
    assert response.topK[0].tags == ["tumbler", "stainless"]
    assert response.topK[0].score == pytest.approx(0.92)
    assert response.summary == "Top results include insulated stainless steel options."


def test_search_truncates_snippet_and_clamps_score():
    long_text = "A" * 1000
    docs = [(Document(page_content=long_text, metadata={"productTitle": "Long Doc"}), 1.5)]
    store = StubVectorStore(results=docs)
    service = ProductSearchService(vector_store=store)

    response = service.search("long doc")

    assert len(response.topK) == 1
    hit = response.topK[0]
    assert hit.score == 1.0
    assert hit.snippet.endswith("...")
    assert len(hit.snippet) <= 400


def test_search_rejects_empty_query():
    store = StubVectorStore(results=[])
    service = ProductSearchService(vector_store=store)

    with pytest.raises(AppError):
        service.search("")


def test_from_settings_missing_index(monkeypatch, tmp_path):
    settings = AppSettings(vector_store_path=str(tmp_path / "missing"), openai_api_key="test-key")
    monkeypatch.setattr("app.services.products.get_settings", lambda: settings)

    class DummyEmbeddings:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", DummyEmbeddings)

    def fake_load_local(*args, **kwargs):
        raise FileNotFoundError("missing index")

    monkeypatch.setattr("langchain_community.vectorstores.FAISS.load_local", fake_load_local)

    with pytest.raises(ProductSearchError):
        ProductSearchService.from_settings()


def test_from_settings_runtime_error_wrapped(monkeypatch, tmp_path):
    settings = AppSettings(vector_store_path=str(tmp_path / "missing"), openai_api_key="test-key")
    monkeypatch.setattr("app.services.products.get_settings", lambda: settings)

    class DummyEmbeddings:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", DummyEmbeddings)

    def fake_load_local(*args, **kwargs):
        raise RuntimeError("faiss read failure")

    monkeypatch.setattr("langchain_community.vectorstores.FAISS.load_local", fake_load_local)

    with pytest.raises(ProductSearchError) as excinfo:
        ProductSearchService.from_settings()
    assert "Product vector store is not available." in str(excinfo.value)


def test_search_includes_summary_when_summary_fn_provided():
    document = Document(
        page_content="Insulated bottle that keeps drinks cold for 12 hours.",
        metadata={"productTitle": "Insulated Bottle"},
    )
    store = StubVectorStore(results=[(document, 0.88)])

    def summary_fn(query: str, documents):
        assert query == "insulated bottle"
        assert documents == [document]
        return "Insulated Bottle keeps drinks cold for 12 hours."

    service = ProductSearchService(vector_store=store, summary_fn=summary_fn)

    response = service.search("insulated bottle")

    assert response.summary == "Insulated Bottle keeps drinks cold for 12 hours."


def test_search_expands_vector_k_for_summary_context():
    docs = [
        (Document(page_content=f"Variant {idx}", metadata={"productTitle": f"Title {idx}"}), 0.9 - idx * 0.1)
        for idx in range(5)
    ]
    store = StubVectorStore(results=docs)
    service = ProductSearchService(vector_store=store, summary_context_k=5)

    response = service.search("show me options", k=2)

    assert store.last_k == 5
    assert len(response.topK) == 2

