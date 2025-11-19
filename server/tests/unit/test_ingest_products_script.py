import json
import sys
from pathlib import Path

import pytest

from app.core.config import AppSettings
from server.scripts import ingest_products as script


def write_seed(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


@pytest.mark.slow
def test_ingest_products_creates_faiss_index(tmp_path, monkeypatch):
    source = tmp_path / "seed.json"
    write_seed(
        source,
        [
            {
                "slug": "sample",
                "title": "Sample Bottle",
                "description": "Keeps drinks hot.",
                "specs": {"capacity_ml": 500},
                "tags": ["bottle"],
                "url": "https://example.com/bottle",
                "variants": [
                    {
                        "id": "sample-bottle-default",
                        "title": "Default",
                        "sku": "SAMPLE-1",
                        "price": 42.0,
                        "compare_at_price": None,
                        "available": True,
                        "image_url": "https://example.com/image.jpg",
                        "option_values": ["Standard"],
                    }
                ],
            }
        ],
    )

    records = script.load_products_from_file(source)
    dest = tmp_path / "index"

    saved = {}

    class DummyVectorStore:
        def __init__(self, documents, embeddings):
            self.documents = documents
            self.embeddings = embeddings

        def save_local(self, path: str) -> None:
            saved["path"] = path
            path_obj = Path(path)
            path_obj.mkdir(parents=True, exist_ok=True)
            (path_obj / "index.faiss").write_text("stub", encoding="utf-8")
            (path_obj / "index.pkl").write_text("stub", encoding="utf-8")

    def fake_from_documents(documents, embeddings):
        saved["documents"] = documents
        saved["embeddings"] = embeddings
        return DummyVectorStore(documents, embeddings)

    monkeypatch.setattr(
        script,
        "FAISS",
        type("FakeFAISS", (), {"from_documents": staticmethod(fake_from_documents)}),
    )
    monkeypatch.setattr(script, "get_embeddings", lambda provider: object())

    script.ingest_products(records=records, dest=dest, provider="fake")

    assert (dest / "index.faiss").exists()
    assert (dest / "index.pkl").exists()
    assert saved["path"] == str(dest)
    assert saved["documents"][0].metadata["variantId"] == "sample-bottle-default"

    documents = script.build_documents(records)
    assert len(documents) >= 1
    doc = documents[0]
    assert "Sample Bottle" in doc.page_content
    assert doc.metadata["variantId"] == "sample-bottle-default"
    assert doc.metadata["price"] == 42.0


def test_load_products_from_file_invalid(tmp_path):
    source = tmp_path / "seed.json"
    write_seed(source, [{"slug": "invalid", "description": "missing title"}])

    with pytest.raises(ValueError):
        script.load_products_from_file(source)


def test_load_products_from_url(monkeypatch):
    called = {}

    class DummyResponse:
        def __init__(self, payload, status_code=200, headers=None):
            self._payload = payload
            self.status_code = status_code
            self.headers = headers or {"content-type": "application/json"}

        def json(self):
            return self._payload

    def fake_get(url, timeout):
        called["url"] = url
        return DummyResponse(
            [
                {
                    "slug": "remote",
                    "title": "Remote Tumbler",
                    "description": "Pulls from remote JSON.",
                    "tags": ["remote"],
                    "variants": [
                        {
                            "id": "remote-variant",
                            "title": "Remote Blue",
                            "price": 59.0,
                            "available": True,
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr(script.httpx, "get", fake_get)

    records = script.load_products_from_url("https://zuscoffee.example/mock")

    assert called["url"] == "https://zuscoffee.example/mock"
    assert records[0].slug == "remote"
    assert records[0].variants[0].title == "Remote Blue"


def test_load_products_from_shopify_collection(monkeypatch):
    requested = []

    class DummyResponse:
        def __init__(self, *, status_code=200, json_data=None, text="", headers=None):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.headers = headers or {}

        def json(self):
            return self._json

    def fake_get(url, timeout):
        requested.append(url)
        if url.endswith("/collections/all-tumbler"):
            return DummyResponse(
                status_code=200,
                text="<html></html>",
                headers={"content-type": "text/html"},
            )
        if url.endswith("/collections/all-tumbler/products.json"):
            return DummyResponse(
                status_code=200,
                json_data={
                    "products": [
                        {
                            "handle": "shopify-cup",
                            "title": "Shopify Cup",
                            "body_html": "<p>Great cup</p>",
                            "tags": "cup,drinkware",
                            "product_type": "Tumbler",
                            "vendor": "ZUS",
                            "variants": [
                                {
                                    "id": 123,
                                    "title": "Misty Blue",
                                    "sku": "SKU-123",
                                    "price": "79.00",
                                    "compare_at_price": "99.00",
                                    "available": True,
                                    "featured_image": {"src": "https://example.com/blue.jpg"},
                                    "option1": "Blue",
                                }
                            ],
                            "images": [
                                {
                                    "src": "https://example.com/blue.jpg",
                                    "variant_ids": [123],
                                }
                            ],
                        }
                    ]
                },
                headers={"content-type": "application/json"},
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(script.httpx, "get", fake_get)

    records = script.load_products_from_url("https://shop.zuscoffee.com/collections/all-tumbler")

    assert len(records) == 1
    record = records[0]
    assert record.slug == "shopify-cup"
    assert record.variants[0].available is True
    assert record.variants[0].compare_at_price == 99.0
    assert record.variants[0].image_url == "https://example.com/blue.jpg"
    assert "cup" in record.tags
    assert requested == [
        "https://shop.zuscoffee.com/collections/all-tumbler/products.json",
    ]


def test_parse_args_default_dest_uses_settings(monkeypatch, tmp_path):
    settings = AppSettings(vector_store_path=str(tmp_path / "vector-store"))
    monkeypatch.setattr(script, "get_settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["ingest_products.py"])

    args = script.parse_args()

    assert args.dest == tmp_path / "vector-store"

