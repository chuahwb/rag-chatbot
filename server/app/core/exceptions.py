from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.context import get_request_id


class AppError(Exception):
    status_code: int = 500
    error_type: str = "APP_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        payload = {
            "error": {
                "type": exc.error_type,
                "message": exc.message,
            }
        }
        if exc.details:
            payload["error"]["details"] = exc.details
        trace_id = get_request_id()
        if trace_id:
            payload["error"]["traceId"] = trace_id

        return JSONResponse(status_code=exc.status_code, content=payload)


