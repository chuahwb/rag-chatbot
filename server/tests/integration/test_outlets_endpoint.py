from fastapi.testclient import TestClient

from app.api.routes.outlets import get_outlets_service
from app.main import create_app
from app.models.outlets import OutletsQueryResponse
from app.services.outlets import OutletsExecutionError, OutletsQueryError


class StubOutletsService:
    def __init__(self, response: OutletsQueryResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    def query(self, user_query: str) -> OutletsQueryResponse:
        self.calls.append(user_query)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response

    async def query_async(self, user_query: str) -> OutletsQueryResponse:
        return self.query(user_query)


def create_client(service: StubOutletsService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_outlets_service] = lambda: service
    return TestClient(app)


def test_outlets_endpoint_returns_rows():
    response = OutletsQueryResponse(
        query="opening hours ss2",
        sql="SELECT open_time FROM outlets WHERE area = 'SS 2'",
        params={},
        rows=[{"open_time": "09:00"}],
    )
    service = StubOutletsService(response=response)
    client = create_client(service)

    res = client.get("/outlets", params={"query": "opening hours ss2"})

    assert res.status_code == 200
    assert res.json()["rows"][0]["open_time"] == "09:00"
    assert service.calls == ["opening hours ss2"]
    assert res.headers["X-Request-ID"]


def test_outlets_endpoint_handles_validation_error():
    service = StubOutletsService(error=OutletsQueryError("missing info"))
    client = create_client(service)

    res = client.get("/outlets", params={"query": "bad"})

    assert res.status_code == 400
    assert res.json()["error"]["type"] == "OUTLETS_QUERY_ERROR"
    assert res.json()["error"]["traceId"] == res.headers["X-Request-ID"]


def test_outlets_endpoint_handles_execution_error():
    service = StubOutletsService(error=OutletsExecutionError("db down"))
    client = create_client(service)

    res = client.get("/outlets", params={"query": "anything"})

    assert res.status_code == 500
    assert res.json()["error"]["type"] == "OUTLETS_EXECUTION_ERROR"
    assert res.json()["error"]["traceId"] == res.headers["X-Request-ID"]

