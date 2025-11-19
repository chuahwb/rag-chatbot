from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.models.calculator import CalculatorResult
from app.services.calculator import CalculatorError


class CalculatorHttpServiceError(CalculatorError):
    status_code = 502
    error_type = "CALCULATOR_HTTP_ERROR"


@dataclass
class CalculatorHttpService:
    base_url: str
    timeout: float = 5.0

    @classmethod
    def from_settings(cls) -> "CalculatorHttpService":
        settings = get_settings()
        if not settings.calc_http_base_url:
            raise CalculatorHttpServiceError("CALC_HTTP_BASE_URL is not configured.")
        return cls(
            base_url=settings.calc_http_base_url.rstrip("/"),
            timeout=float(settings.calc_http_timeout_sec),
        )

    def evaluate(self, expression: str) -> CalculatorResult:
        query = expression.strip()
        if not query:
            raise CalculatorError("Expression cannot be empty.")

        url = f"{self.base_url}/calc"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params={"query": query})
        except httpx.RequestError as exc:
            raise CalculatorHttpServiceError("Calculator service is unavailable.") from exc

        if response.status_code != 200:
            message = "Calculator request failed."
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = error.get("message", message)
            raise CalculatorHttpServiceError(message)

        try:
            payload = response.json()
        except ValueError as exc:
            raise CalculatorHttpServiceError("Calculator response was not valid JSON.") from exc

        return CalculatorResult.model_validate(payload)


