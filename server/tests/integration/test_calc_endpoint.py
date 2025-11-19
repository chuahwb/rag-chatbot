from fastapi.testclient import TestClient

from app.main import create_app


def create_test_client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_calc_endpoint_returns_result_for_valid_expression() -> None:
    client = create_test_client()

    response = client.get("/calc", params={"query": "3*(4+5)"})

    assert response.status_code == 200
    assert response.json() == {
        "expression": "3*(4+5)",
        "result": 27,
    }
    assert response.headers["X-Request-ID"]


def test_calc_endpoint_returns_error_for_invalid_expression() -> None:
    client = create_test_client()

    response = client.get("/calc", params={"query": "abc"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "CALCULATOR_ERROR"
    assert "expression" in payload["error"]["message"].lower()
    assert payload["error"]["traceId"] == response.headers["X-Request-ID"]


def test_calc_endpoint_requires_query_param() -> None:
    client = create_test_client()

    response = client.get("/calc")

    assert response.status_code == 422


