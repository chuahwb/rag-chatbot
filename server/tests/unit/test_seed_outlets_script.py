import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Outlet
from server.scripts import seed_outlets as script


FIELDNAMES = [
    "name",
    "address",
    "openTime",
    "closeTime",
    "servicesJson",
    "externalId",
    "city",
    "state",
    "postalCode",
]


class DummyResponse:
    def __init__(self, *, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("No JSON payload available")
        return self._json


def override_settings(monkeypatch, **overrides):
    defaults = {
        "outlets_db_backend": "sqlite",
        "outlets_sqlite_url": script.DEFAULT_SQLITE_DB_URL,
        "outlets_postgres_url": None,
    }
    defaults.update(overrides)

    def _stub():
        return SimpleNamespace(**defaults)

    monkeypatch.setattr(script, "AppSettings", _stub)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_seed_record(**overrides):
    base = {
        "name": "ZUS Coffee SS 2",
        "address": "No. 1, Jalan SS2/55, 47300 Petaling Jaya, Selangor",
        "openTime": "09:00",
        "closeTime": "21:00",
        "servicesJson": json.dumps(["wifi", "delivery"]),
        "externalId": "zus-coffee-ss-2",
        "city": "Petaling Jaya",
        "state": "Selangor",
        "postalCode": "47300",
    }
    base.update(overrides)
    return base


def test_load_outlets_from_csv_parses_services(tmp_path: Path) -> None:
    csv_path = tmp_path / "outlets.csv"
    write_csv(csv_path, [make_seed_record()])

    records = script.load_outlets_from_csv(csv_path)

    assert len(records) == 1
    record = records[0]
    assert record.name == "ZUS Coffee SS 2"
    assert record.open_time == "09:00"
    assert record.services == ["wifi", "delivery"]
    assert record.city == "Petaling Jaya"
    assert record.state == "Selangor"
    assert record.postal_code == "47300"
    assert record.external_id == "zus-coffee-ss-2"


def test_load_outlets_from_csv_rejects_invalid_time(tmp_path: Path) -> None:
    csv_path = tmp_path / "outlets.csv"
    write_csv(
        csv_path,
        [
            make_seed_record(
                name="Invalid Outlet",
                address="123 Void Street, 40000 Nowhere, Selangor",
                openTime="9am",
                city="Nowhere",
                state="Selangor",
                postalCode="40000",
                externalId="invalid-outlet",
            )
        ],
    )

    with pytest.raises(ValueError):
        script.load_outlets_from_csv(csv_path)


def test_seed_outlets_writes_to_database(tmp_path: Path) -> None:
    csv_path = tmp_path / "outlets.csv"
    write_csv(
        csv_path,
        [
            make_seed_record(),
            make_seed_record(
                name="ZUS Coffee Uptown",
                address="123 Uptown Street, 47400 Petaling Jaya, Selangor",
                openTime="08:00",
                closeTime="22:00",
                servicesJson=json.dumps(["wifi"]),
                externalId="zus-coffee-uptown",
                city="Petaling Jaya",
                state="Selangor",
                postalCode="47400",
            ),
        ],
    )

    records = script.load_outlets_from_csv(csv_path)
    db_path = tmp_path / "outlets.db"
    db_url = f"sqlite:///{db_path}"

    script.seed_outlets(records=records, db_url=db_url)

    engine = create_engine(db_url, future=True)
    with Session(engine) as session:
        stored_outlets = session.scalars(select(Outlet).order_by(Outlet.name)).all()

    assert len(stored_outlets) == 2
    assert stored_outlets[0].name == "ZUS Coffee SS 2"
    assert stored_outlets[0].services == ["wifi", "delivery"]
    assert stored_outlets[1].open_time == "08:00"
    assert stored_outlets[0].external_id == "zus-coffee-ss-2"
    assert stored_outlets[0].city == "Petaling Jaya"
    assert stored_outlets[0].state == "Selangor"
    assert stored_outlets[0].postal_code == "47300"


def test_load_outlets_from_endpoint_json_payload(monkeypatch) -> None:
    payload = {
        "stores": [
            {
                "name": "ZUS Coffee SS 2",
                "area": "SS 2",
                "city": "Petaling Jaya",
                "address": "No. 1, Jalan SS2/55, Petaling Jaya",
                "hours": {"open": "09:00", "close": "21:00"},
                "services": ["wifi", "delivery"],
            }
        ]
    }

    def fake_get(url, timeout):
        return DummyResponse(json_data=payload, headers={"content-type": "application/json"})

    monkeypatch.setattr(script.httpx, "get", fake_get)

    records = script.load_outlets_from_endpoint("https://example.com/outlets")

    assert len(records) == 1
    assert records[0].name == "ZUS Coffee SS 2"
    assert records[0].open_time == "09:00"
    assert records[0].services == ["wifi", "delivery"]


def test_load_outlets_from_endpoint_html_script(monkeypatch) -> None:
    html = """
    <html>
      <body>
        <script type="application/json" data-source="stores">
          {"stores": [{"name": "ZUS Coffee KLCC", "area": "Suria KLCC", "city": "Kuala Lumpur",
            "address": "Lot C32, Suria KLCC, 50088 Kuala Lumpur, Selangor", "hours": {"open": "09:00", "close": "22:00"},
            "services": ["wifi", "takeaway"]}]}
        </script>
      </body>
    </html>
    """

    def fake_get(url, timeout):
        return DummyResponse(text=html, headers={"content-type": "text/html"})

    monkeypatch.setattr(script.httpx, "get", fake_get)

    records = script.load_outlets_from_endpoint("https://example.com/outlets-html")

    assert len(records) == 1
    assert records[0].name == "ZUS Coffee KLCC"
    assert records[0].close_time == "22:00"
    assert records[0].external_id == "zus-coffee-klcc"
    assert records[0].city == "Kuala Lumpur"
    assert records[0].state == "Selangor"
    assert records[0].postal_code == "50088"


def test_gather_records_prefers_endpoint(monkeypatch) -> None:
    endpoint_records = [script.OutletRecord.model_validate(make_seed_record())]
    csv_records = [
        script.OutletRecord.model_validate(
            make_seed_record(
                name="Fallback",
                externalId="fallback-slug",
                address="2 Example Avenue, 50000 Kuala Lumpur, Kuala Lumpur",
                city="Kuala Lumpur",
                state="Kuala Lumpur",
                postalCode="50000",
            )
        )
    ]

    monkeypatch.setattr(script, "load_outlets_from_endpoint", lambda url: endpoint_records)
    monkeypatch.setattr(script, "load_outlets_from_csv", lambda path: csv_records)

    args = SimpleNamespace(
        endpoint="https://example.com/outlets",
        csv=Path("data/outlets/outlets.csv"),
        skip_endpoint=False,
        fail_on_endpoint_error=False,
    )

    assert script._gather_records(args) == endpoint_records


def test_gather_records_falls_back_to_csv_when_endpoint_fails(monkeypatch, tmp_path: Path) -> None:
    csv_path = tmp_path / "outlets.csv"
    write_csv(
        csv_path,
        [
            make_seed_record(
                name="Fallback Store",
                externalId="fallback-store",
                address="1 Example Street, 43000 Kajang, Selangor",
                city="Kajang",
                state="Selangor",
                postalCode="43000",
            )
        ],
    )

    def fail_endpoint(url):
        raise ValueError("endpoint unavailable")

    monkeypatch.setattr(script, "load_outlets_from_endpoint", fail_endpoint)
    real_load_csv = script.load_outlets_from_csv
    monkeypatch.setattr(script, "load_outlets_from_csv", lambda path: real_load_csv(csv_path))

    args = SimpleNamespace(
        endpoint="https://example.com/outlets",
        csv=csv_path,
        skip_endpoint=False,
        fail_on_endpoint_error=False,
    )

    records = script._gather_records(args)

    assert len(records) == 1
    assert records[0].name == "Fallback Store"
    assert records[0].external_id == "fallback-store"
    assert records[0].city == "Kajang"


def test_load_outlets_from_endpoint_html_uses_wp_api(monkeypatch) -> None:
    html = """
    <script type="text/javascript" id="ecs_ajax_load-js-extra">
    var ecs_ajax_params = {"posts":"{\\"cat\\":64,\\"posts_per_page\\":12}"};
    </script>
    """

    def fake_get(url, timeout):
        return DummyResponse(text=html, headers={"content-type": "text/html"})

    def fake_fetch(endpoint, category_id):
        assert category_id == 64
        return [
            {
                "id": 999,
                "slug": "zus-coffee-test-area",
                "title": {"rendered": "ZUS Coffee – Test Area"},
                "content": {"rendered": "<p>10 Jalan Test, 43000 Kajang, Selangor</p>"},
            }
        ]

    monkeypatch.setattr(script.httpx, "get", fake_get)
    monkeypatch.setattr(script, "_fetch_wp_category_posts", fake_fetch)

    records = script.load_outlets_from_endpoint("https://example.com/category/store/kuala-lumpur-selangor/")

    assert len(records) == 1
    assert records[0].city == "Kajang"
    assert records[0].state == "Selangor"
    assert records[0].postal_code == "43000"
    assert records[0].open_time is None
    assert records[0].external_id == "zus-coffee-test-area"


def test_default_db_url_prefers_postgres_when_backend_requests_it(monkeypatch) -> None:
    override_settings(
        monkeypatch,
        outlets_db_backend="postgres",
        outlets_postgres_url="postgresql+psycopg://supabase",
        outlets_sqlite_url="sqlite:///should-not-use.db",
    )
    assert script._default_db_url() == "postgresql+psycopg://supabase"


def test_default_db_url_raises_when_postgres_missing(monkeypatch) -> None:
    override_settings(
        monkeypatch,
        outlets_db_backend="postgres",
        outlets_postgres_url=None,
        outlets_sqlite_url="sqlite:///preferred.db",
    )
    with pytest.raises(ValueError):
        script._default_db_url()


def test_default_db_url_uses_legacy_sqlite_env(monkeypatch) -> None:
    override_settings(
        monkeypatch,
        outlets_db_backend="sqlite",
        outlets_sqlite_url="sqlite:///legacy.db",
    )

    assert script._default_db_url() == "sqlite:///legacy.db"


def test_default_db_url_falls_back_to_constant(monkeypatch, tmp_path: Path) -> None:
    temp_db = tmp_path / "custom.db"
    monkeypatch.setattr(
        script,
        "DEFAULT_SQLITE_DB_URL",
        f"sqlite:///{temp_db}",
    )
    override_settings(
        monkeypatch,
        outlets_db_backend="sqlite",
        outlets_sqlite_url="",
        outlets_postgres_url=None,
    )

    assert script._default_db_url() == f"sqlite:///{temp_db}"

