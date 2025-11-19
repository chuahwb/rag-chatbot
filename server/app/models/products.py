from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ProductHit(BaseModel):
    title: str = Field(..., description="Product title")
    variantTitle: str | None = Field(None, description="Variant display name")
    variantId: str | None = Field(None, description="Variant identifier")
    score: float = Field(..., ge=0, le=1, description="Relevance score between 0 and 1")
    url: str | None = Field(None, description="Source URL of the product")
    price: float | None = Field(None, description="Variant price")
    compareAtPrice: float | None = Field(None, description="Original price before discount")
    available: bool | None = Field(None, description="Whether the variant is in stock")
    imageUrl: str | None = Field(None, description="Image representing the variant")
    sku: str | None = Field(None, description="Stock keeping unit")
    productType: str | None = Field(None, description="Product type classification")
    tags: list[str] = Field(default_factory=list, description="Tags associated with the product")
    snippet: str | None = Field(None, description="Relevant excerpt from the product data")


class ProductSearchResponse(BaseModel):
    query: str = Field(..., description="Original user query")
    topK: List[ProductHit] = Field(default_factory=list, description="Retrieved documents")
    summary: str | None = Field(None, description="Optional AI-generated summary grounded in the retrieved context")

