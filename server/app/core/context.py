from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from typing import Optional

_request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_request_id(request_id: Optional[str] = None) -> Token:
    value = request_id or str(uuid.uuid4())
    return _request_id_ctx_var.set(value)


def get_request_id() -> Optional[str]:
    return _request_id_ctx_var.get()


def reset_request_id(token: Token) -> None:
    _request_id_ctx_var.reset(token)



