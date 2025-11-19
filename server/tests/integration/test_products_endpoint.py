from fastapi.testclient import TestClient

from app.api.routes.products import get_product_search_service
from app.main import create_app
from app.models.products import ProductHit, ProductSearchResponse
from app.services.products import ProductSearchError


class StubProductService:
    def __init__(self, response: ProductSearchResponse | None = None, *, should_fail: bool = False):
        self.response = response
        self.should_fail = should_fail
        self.received = []

    def search(self, query: str, k: int = 3) -> ProductSearchResponse:
        self.received.append((query, k))
        if self.should_fail:
            raise ProductSearchError("Index offline.")
        assert self.response is not None
        return self.response

    async def search_async(self, query: str, k: int = 3) -> ProductSearchResponse:
        return self.search(query, k=k)


def create_client(service: StubProductService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_product_search_service] = lambda: service
    return TestClient(app)


def test_products_endpoint_returns_hits():
    response = ProductSearchResponse(
        query="steel bottle",
        topK=[
            ProductHit(
                title="Steel Bottle 500ml",
                variantTitle="Matte Black",
                score=0.9,
                url="https://example.com/steel",
                price=79.0,
                compareAtPrice=99.0,
                available=True,
                imageUrl="https://example.com/image.jpg",
                sku="SKU-1",
                productType="Tumbler",
                tags=["tumbler"],
                snippet="Steel bottle",
            ),
        ],
        summary="Summary",
    )
    service = StubProductService(response=response)
    client = create_client(service)

    res = client.get("/products", params={"query": "steel bottle", "k": 1})

    assert res.status_code == 200
    payload = res.json()
    assert payload["query"] == "steel bottle"
    assert payload["summary"] == "Summary"
    assert payload["topK"][0]["title"] == "Steel Bottle 500ml"
    assert service.received == [("steel bottle", 1)]
    assert res.headers["X-Request-ID"]


def test_products_endpoint_handles_service_failure():
    service = StubProductService(should_fail=True)
    client = create_client(service)

    res = client.get("/products", params={"query": "steel bottle"})

    assert res.status_code == 503
    body = res.json()
    assert body["error"]["type"] == "PRODUCT_INDEX_ERROR"
    assert body["error"]["traceId"] == res.headers["X-Request-ID"]


