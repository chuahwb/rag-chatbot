from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Iterable, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from pydantic import BaseModel, Field, HttpUrl, ValidationError, model_validator

from app.core.config import AppSettings, get_settings
from app.services.pinecone_utils import extract_index_names
from app.services.products import build_product_embeddings
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("ingest_products")

DEFAULT_COLLECTION_URLS = [
    "https://shop.zuscoffee.com/collections/all-tumbler",
    "https://shop.zuscoffee.com/collections/mugs",
]

EMBEDDING_DIMENSIONS: dict[str, int] = {
    # Keep this aligned with build_product_embeddings in app.services.products.
    "openai": 1536,
    "fake": 1536,
    "local": 1536,
}


class VariantRecord(BaseModel):
    id: str = Field(..., description="Variant identifier")
    title: str = Field(..., description="Variant display title")
    sku: Optional[str] = Field(default=None, description="Stock keeping unit")
    price: float = Field(..., description="Current price")
    compare_at_price: Optional[float] = Field(default=None, description="Original price before discount")
    available: bool = Field(default=True, description="Whether the variant is available for purchase")
    image_url: Optional[str] = Field(default=None, description="Image URL for the variant")
    option_values: List[str] = Field(default_factory=list, description="Selected option values (e.g., color)")

    @model_validator(mode="before")
    def normalise_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        price = values.get("price")
        if price is not None:
            try:
                values["price"] = float(price)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid price value {price!r}")
        compare = values.get("compare_at_price")
        if compare:
            try:
                values["compare_at_price"] = float(compare)
            except (TypeError, ValueError):
                values["compare_at_price"] = None
        variant_id = values.get("id")
        if variant_id is not None:
            values["id"] = str(variant_id)
        option_vals = values.get("option_values") or values.get("options") or []
        if isinstance(option_vals, str):
            option_vals = [option_vals]
        values["option_values"] = list(option_vals)
        return values


class ProductRecord(BaseModel):
    slug: str = Field(..., min_length=3)
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    tags: list[str] = Field(default_factory=list)
    url: HttpUrl | None = None
    product_type: str | None = None
    variants: List[VariantRecord] = Field(default_factory=list)

    @model_validator(mode="before")
    def normalise_tags(cls, values: dict[str, Any]) -> dict[str, Any]:
        tags = values.get("tags")
        if tags is None:
            values["tags"] = []
        elif isinstance(tags, str):
            values["tags"] = [tag.strip() for tag in tags.split(",") if tag.strip()]
        return values

    @model_validator(mode="after")
    def ensure_variants(self) -> "ProductRecord":
        if not self.variants:
            raise ValueError("Product must include at least one variant.")
        return self


def load_products_from_file(path: Path) -> List[ProductRecord]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Seed file must contain a list of product objects.")
    records: list[ProductRecord] = []
    for raw in data:
        try:
            records.append(ProductRecord.model_validate(raw))
        except ValidationError as exc:
            raise ValueError(f"Invalid product record: {exc}") from exc
    return records


def load_products_from_url(url: str) -> List[ProductRecord]:
    """
    Load products from either a direct JSON feed or a Shopify collection URL.
    """
    if "/collections/" in url and not url.endswith(".json"):
        return _load_shopify_collection(url)

    logger.info("Fetching product data from %s", url)
    resp = httpx.get(url, timeout=30.0)
    content_type = resp.headers.get("content-type", "")

    if resp.status_code == 200 and "application/json" in content_type:
        return _parse_product_json(resp.json(), base_url=url)

    resp.raise_for_status()
    raise ValueError(f"Unsupported response from {url}")


def _parse_product_json(data: Any, *, base_url: str) -> List[ProductRecord]:
    if isinstance(data, dict) and "products" in data and isinstance(data["products"], list):
        return [_convert_shopify_product(prod, base_url) for prod in data["products"]]

    if isinstance(data, list):
        records: list[ProductRecord] = []
        for raw in data:
            try:
                records.append(ProductRecord.model_validate(raw))
            except ValidationError as exc:
                raise ValueError(f"Invalid product record from remote source: {exc}") from exc
        return records

    raise ValueError("Remote endpoint returned an unsupported JSON structure.")


def _load_shopify_collection(url: str) -> List[ProductRecord]:
    base = url.split("?")[0].rstrip("/")
    json_url = f"{base}/products.json"
    logger.info("Attempting Shopify collection JSON at %s", json_url)

    resp = httpx.get(json_url, timeout=30.0)
    if resp.status_code != 200:
        raise ValueError(f"Unable to fetch Shopify collection JSON from {json_url}")

    return _parse_product_json(resp.json(), base_url=url)


def _convert_shopify_product(product: dict[str, Any], base_url: str) -> ProductRecord:
    handle = product.get("handle")
    title = (product.get("title") or "").strip()
    body_html = product.get("body_html") or ""
    description = _strip_html(body_html) or title
    tags_raw = product.get("tags", "")
    tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()] if isinstance(tags_raw, str) else []

    base_parts = urlparse(base_url)
    product_url = None
    if handle and base_parts.netloc:
        product_url = f"{base_parts.scheme or 'https'}://{base_parts.netloc}/products/{handle}"

    images = product.get("images") or []
    variant_image_map: dict[str, str] = {}
    default_image = None
    for idx, image in enumerate(images):
        src = image.get("src")
        if src:
            if idx == 0:
                default_image = src
            for variant_id in image.get("variant_ids") or []:
                variant_image_map[str(variant_id)] = src

    variants_payload = product.get("variants") or []
    variant_records: list[VariantRecord] = []
    for variant in variants_payload:
        variant_id = variant.get("id")
        image_url = None
        featured = variant.get("featured_image")
        if isinstance(featured, dict):
            image_url = featured.get("src")
        elif isinstance(featured, str):
            image_url = featured
        if not image_url:
            image_url = variant_image_map.get(str(variant_id), default_image)

        option_values = []
        for key in ("option1", "option2", "option3"):
            val = variant.get(key)
            if val and val != "Default Title":
                option_values.append(val)

        variant_records.append(
            VariantRecord(
                id=str(variant_id or handle or title),
                title=(variant.get("title") or option_values[0] if option_values else title).strip() or title,
                sku=variant.get("sku"),
                price=variant.get("price") or product.get("price") or 0.0,
                compare_at_price=variant.get("compare_at_price"),
                available=bool(variant.get("available", False)),
                image_url=image_url,
                option_values=option_values,
            )
        )

    record = {
        "slug": handle or title.lower().replace(" ", "-"),
        "title": title or handle,
        "description": description,
        "tags": tags,
        "url": product_url,
        "product_type": product.get("product_type"),
        "variants": variant_records,
    }
    return ProductRecord.model_validate(record)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def build_documents(records: Iterable[ProductRecord]) -> List[Document]:
    documents: list[Document] = []

    for record in records:
        base_description = record.description
        tags_text = ", ".join(record.tags)
        splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=64)

        for variant in record.variants:
            variant_text_parts = [
                f"Product: {record.title}",
                f"Variant: {variant.title}",
            ]
            if record.product_type:
                variant_text_parts.append(f"Type: {record.product_type}")
            if tags_text:
                variant_text_parts.append(f"Tags: {tags_text}")
            variant_text_parts.append(f"Description: {base_description}")
            variant_text_parts.append(f"Price: {variant.price}")
            if variant.compare_at_price:
                variant_text_parts.append(f"Compare at price: {variant.compare_at_price}")
            variant_text_parts.append(f"Available: {'yes' if variant.available else 'no'}")
            option_text = ", ".join(variant.option_values)
            if option_text:
                variant_text_parts.append(f"Options: {option_text}")

            full_text = "\n".join(variant_text_parts)
            chunks = splitter.split_text(full_text) or [full_text]

            for chunk_index, chunk in enumerate(chunks):
                metadata = {
                    "productTitle": record.title,
                    "productSlug": record.slug,
                    "productUrl": str(record.url) if record.url else None,
                    "productType": record.product_type,
                    "tags": record.tags,
                    "variantId": variant.id,
                    "variantTitle": variant.title,
                    "available": variant.available,
                    "price": variant.price,
                    "compareAtPrice": variant.compare_at_price,
                    "sku": variant.sku,
                    "imageUrl": variant.image_url,
                    "chunkIndex": chunk_index,
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}

                documents.append(
                    Document(
                        page_content=chunk,
                        metadata=metadata,
                    )
                )
    return documents


def get_embeddings(provider: str):
    settings = get_settings()
    normalized = (provider or (settings.embeddings_provider or "openai")).lower()
    try:
        return build_product_embeddings(settings, provider_override=normalized)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def ingest_products(*, records: Iterable[ProductRecord], dest: Path, provider: str) -> Path:
    documents = build_documents(records)
    if not documents:
        raise ValueError("No documents were produced from the provided records.")

    settings = get_settings()
    backend = (settings.product_vector_store_backend or "faiss").lower()
    provider_name = (provider or (settings.embeddings_provider or "openai")).lower()
    embeddings = get_embeddings(provider_name)

    if backend == "faiss":
        logger.info("Creating FAISS index with %d documents", len(documents))
        vector_store = FAISS.from_documents(documents, embeddings)
        dest.mkdir(parents=True, exist_ok=True)
        vector_store.save_local(str(dest))
        logger.info("Saved FAISS index to %s", dest)
        return dest

    if backend == "pinecone":
        return _ingest_into_pinecone(
            documents=documents,
            embeddings=embeddings,
            settings=settings,
            provider=provider_name,
        )

    raise ValueError(f"Unsupported product vector store backend: {backend}")


def _ingest_into_pinecone(
    *,
    documents: List[Document],
    embeddings,
    settings: AppSettings,
    provider: str,
) -> Path:
    from langchain_pinecone import PineconeVectorStore

    dimension = _embedding_dimension(provider)
    index_name, client = _ensure_pinecone_index(settings, dimension=dimension)
    index = client.Index(index_name)
    vector_store = PineconeVectorStore(index=index, embedding=embeddings)
    vector_store.add_documents(documents)
    logger.info("Upserted %d documents into Pinecone index %s", len(documents), index_name)
    return Path(index_name)


def _ensure_pinecone_index(settings: AppSettings, *, dimension: int) -> tuple[str, "Pinecone"]:
    from pinecone import Pinecone, ServerlessSpec

    api_key = (settings.pinecone_api_key or "").strip()
    if not api_key:
        raise ValueError("PINECONE_API_KEY is required when PRODUCT_VECTOR_STORE_BACKEND=pinecone.")
    index_name = (settings.pinecone_index_name or "").strip()
    if not index_name:
        raise ValueError("PINECONE_INDEX_NAME is required when PRODUCT_VECTOR_STORE_BACKEND=pinecone.")

    client = Pinecone(api_key=api_key)
    names = extract_index_names(client.list_indexes())
    if index_name not in names:
        logger.info(
            "Creating Pinecone index %s (cloud=%s, region=%s)",
            index_name,
            settings.pinecone_cloud,
            settings.pinecone_region,
        )
        client.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
        )
    else:
        logger.info("Using existing Pinecone index %s", index_name)

    return index_name, client


def _embedding_dimension(provider: str) -> int:
    dimension = EMBEDDING_DIMENSIONS.get(provider.lower())
    if dimension is None:
        raise ValueError(f"Unsupported embeddings provider for Pinecone index sizing: {provider}")
    return dimension


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    default_dest = Path(settings.vector_store_path)

    parser = argparse.ArgumentParser(description="Ingest ZUS drinkware products into a FAISS or Pinecone vector store.")
    parser.add_argument("--source", type=Path, help="Path to seed JSON file instead of fetching live data.")
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_dest,
        help=f"Destination directory for FAISS index (default: {default_dest}). Ignored when using Pinecone.",
    )
    parser.add_argument("--provider", type=str, default="openai", help="Embeddings provider: openai|local|fake.")
    parser.add_argument("--fetch-url", type=str, default=None, help="Optional HTTPS endpoint returning product JSON list.")
    return parser.parse_args()


def _dedupe_records(records: Iterable[ProductRecord]) -> List[ProductRecord]:
    """
    Deduplicate variants across products by (slug, variant id).
    """
    seen = set()
    unique_records: list[ProductRecord] = []

    for record in records:
        unique_variants = []
        for variant in record.variants:
            key = (record.slug, variant.id)
            if key in seen:
                continue
            seen.add(key)
            unique_variants.append(variant)

        if unique_variants:
            unique_records.append(record.model_copy(update={"variants": unique_variants}))

    return unique_records


def _gather_records(args: argparse.Namespace) -> List[ProductRecord]:
    if args.fetch_url:
        logger.info("Using explicit fetch URL: %s", args.fetch_url)
        return load_products_from_url(args.fetch_url)

    if args.source:
        logger.info("Loading products from seed file: %s", args.source)
        return load_products_from_file(args.source)

    logger.info("Fetching default collections: %s", ", ".join(DEFAULT_COLLECTION_URLS))
    aggregated: list[ProductRecord] = []
    for url in DEFAULT_COLLECTION_URLS:
        try:
            aggregated.extend(load_products_from_url(url))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to load collection %s: %s", url, exc)
    return _dedupe_records(aggregated)


def main() -> None:
    args = parse_args()
    records = _gather_records(args)
    if not records:
        raise ValueError("No products were loaded; aborting ingestion.")
    ingest_products(records=records, dest=args.dest, provider=args.provider)


if __name__ == "__main__":
    main()

