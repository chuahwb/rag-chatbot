from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from app.core.config import AppSettings
from app.services.calculator import CalculatorError
from app.services.calculator_http import CalculatorHttpService, CalculatorHttpServiceError


@respx.mock
def test_evaluate_returns_result(respx_mock):
    service = CalculatorHttpService(base_url="http://calculator.local", timeout=1.5)
    respx_mock.get("http://calculator.local/calc").mock(
        return_value=Response(200, json={"expression": "1+2", "result": 3})
    )

    result = service.evaluate("1+2")

    assert result.result == 3


@respx.mock
def test_evaluate_raises_on_http_error(respx_mock):
    service = CalculatorHttpService(base_url="http://calculator.local")
    respx_mock.get("http://calculator.local/calc").mock(return_value=Response(500, json={"error": {"message": "fail"}}))

    with pytest.raises(CalculatorHttpServiceError):
        service.evaluate("5+5")


@respx.mock
def test_evaluate_rejects_empty_expression(respx_mock):
    service = CalculatorHttpService(base_url="http://calculator.local")
    with pytest.raises(CalculatorError):
        service.evaluate("   ")
    assert not respx_mock.calls


def test_evaluate_handles_network_error(monkeypatch):
    service = CalculatorHttpService(base_url="http://calculator.local")

    def fail_request(*args, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummyClient(fail_request))

    with pytest.raises(CalculatorHttpServiceError):
        service.evaluate("2+2")


class DummyClient:
    def __init__(self, callback):
        self._callback = callback

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get(self, *args, **kwargs):
        return self._callback(*args, **kwargs)


def test_from_settings_requires_base_url(monkeypatch):
    monkeypatch.setattr("app.services.calculator_http.get_settings", lambda: AppSettings(calc_http_base_url=None))

    with pytest.raises(CalculatorHttpServiceError):
        CalculatorHttpService.from_settings()


def test_from_settings_uses_timeout(monkeypatch):
    settings = AppSettings(calc_http_base_url="http://calculator.local", calc_http_timeout_sec=7.5)
    monkeypatch.setattr("app.services.calculator_http.get_settings", lambda: settings)

    service = CalculatorHttpService.from_settings()

    assert service.base_url == "http://calculator.local"
    assert service.timeout == 7.5


