from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.context import get_request_id, reset_request_id, set_request_id

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        request_id_header = request.headers.get("x-request-id")
        token = set_request_id(request_id_header)

        start_time = time.perf_counter()
        extra = {"path": request.url.path, "method": request.method}
        logger.info("request.start", extra=extra)

        try:
            response = await call_next(request)
        finally:
            current_request_id = get_request_id()
            duration_ms = (time.perf_counter() - start_time) * 1000
            extra.update({"duration_ms": round(duration_ms, 2)})
            logger.info("request.end", extra=extra)
            reset_request_id(token)

        response.headers["X-Request-ID"] = request_id_header or (current_request_id or "")
        return response

