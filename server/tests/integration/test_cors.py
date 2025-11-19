from fastapi.testclient import TestClient

from app.main import create_app


def test_cors_allows_configured_origin() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


