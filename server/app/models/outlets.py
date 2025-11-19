from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class OutletRow(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class OutletsQueryResponse(BaseModel):
    query: str
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)
    rows: List[dict[str, Any]] = Field(default_factory=list)



