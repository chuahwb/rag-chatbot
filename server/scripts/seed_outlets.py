from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Iterable, List
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import AppSettings
from app.db.base import Base
from app.db.models import Outlet

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_outlets")

DEFAULT_ENDPOINT = "https://zuscoffee.com/category/store/kuala-lumpur-selangor/"
DEFAULT_ENDPOINTS = [DEFAULT_ENDPOINT]
DEFAULT_SQLITE_DB_URL = "sqlite:///./data/sqlite/outlets.db"

CSV_FIELDNAMES = [
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


class OutletRecord(BaseModel):
    name: str = Field(..., min_length=3)
    address: str = Field(..., min_length=3)
    open_time: str | None = Field(default=None, alias="openTime")
    close_time: str | None = Field(default=None, alias="closeTime")
    services: List[str] = Field(default_factory=list, alias="servicesJson")
    external_id: str = Field(..., min_length=1, alias="externalId")
    city: str | None = Field(default=None, alias="city")
    state: str | None = Field(default=None, alias="state")
    postal_code: str | None = Field(default=None, alias="postalCode")

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }

    @model_validator(mode="before")
    @classmethod
    def _normalise_raw(cls, values: dict) -> dict:
        services_raw = values.get("servicesJson") or values.get("services") or []
        if isinstance(services_raw, str):
            services_raw = services_raw.strip()
            if services_raw:
                try:
                    services_raw = json.loads(services_raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"servicesJson is not valid JSON: {services_raw}") from exc
        if not isinstance(services_raw, list):
            raise ValueError("servicesJson must be a JSON array of service names.")
        values["servicesJson"] = [
            str(item).strip()
            for item in services_raw
            if str(item).strip()
        ]
        for key in ("openTime", "closeTime"):
            val = values.get(key)
            if isinstance(val, str):
                val = val.strip()
                values[key] = val or None
        external = values.get("externalId") or values.get("external_id")
        if not external:
            name = values.get("name") or values.get("title")
            values["externalId"] = _slugify(str(name) if name else "")
        else:
            values["externalId"] = str(external).strip()
        for key in ("city", "state", "postalCode"):
            if key in values:
                raw_value = values.get(key)
                if raw_value is None:
                    continue
                cleaned = str(raw_value).strip()
                values[key] = cleaned or None
        return values

    @model_validator(mode="after")
    def _validate_times(self) -> "OutletRecord":
        for field_name in ("open_time", "close_time"):
            value = getattr(self, field_name)
            if value is None:
                continue
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError as exc:
                raise ValueError(f"{field_name} must be in HH:MM 24h format, got {value!r}") from exc
        return self


@dataclass
class SeedResult:
    inserted: int = 0
    updated: int = 0


STATE_ALIASES = {
    "selangor": "Selangor",
    "wilayah persekutuan kuala lumpur": "Kuala Lumpur",
    "kuala lumpur": "Kuala Lumpur",
    "wilayah persekutuan putrajaya": "Putrajaya",
    "putrajaya": "Putrajaya",
    "johor": "Johor",
    "kedah": "Kedah",
    "kelantan": "Kelantan",
    "melaka": "Malacca",
    "malacca": "Malacca",
    "negeri sembilan": "Negeri Sembilan",
    "pahang": "Pahang",
    "penang": "Penang",
    "pulau pinang": "Penang",
    "perak": "Perak",
    "perlis": "Perlis",
    "sabah": "Sabah",
    "sarawak": "Sarawak",
    "terengganu": "Terengganu",
    "labuan": "Labuan",
    "wilayah persekutuan labuan": "Labuan",
}

CITY_ALIASES = {
    "wilayah persekutuan kuala lumpur": "Kuala Lumpur",
    "wilayah persekutuan putrajaya": "Putrajaya",
    "wilayah persekutuan labuan": "Labuan",
}


def _strip_html_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        if "<" in value and ">" in value:
            soup = BeautifulSoup(value, "html.parser")
            return soup.get_text(" ", strip=True)
        return value.strip()
    return str(value).strip()


def _slugify(value: str) -> str:
    if not value:
        return "outlet"
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return cleaned or "outlet"


def _normalise_state(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None
    key = cleaned.lower()
    if key in STATE_ALIASES:
        return STATE_ALIASES[key]
    if key == "malaysia":
        return None
    return cleaned.title()


def _normalise_city(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None
    key = cleaned.lower()
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    return cleaned.title()


def _extract_city_state_postal(
    address: str, *, city_hint: str | None, state_hint: str | None
) -> tuple[str | None, str | None, str | None]:
    segments = [seg.strip() for seg in re.split(r"[,\n]", address) if seg.strip()]
    postal_code = None
    postal_idx = None
    match_info: re.Match[str] | None = None
    for idx in range(len(segments) - 1, -1, -1):
        match = re.search(r"(\d{5})", segments[idx])
        if match:
            postal_code = match.group(1)
            postal_idx = idx
            match_info = match
            break

    city = _normalise_city(city_hint)
    state = _normalise_state(state_hint)

    if postal_idx is not None and match_info is not None:
        segment = segments[postal_idx]
        before = segment[: match_info.start()].strip(" ,")
        after = segment[match_info.end() :].strip(" ,")

        candidates = [after, before]
        for candidate in candidates:
            if candidate:
                city_candidate = _normalise_city(candidate)
                if city_candidate:
                    city = city_candidate
                    break

        for seg in segments[postal_idx + 1 :]:
            state_candidate = _normalise_state(seg)
            if state_candidate:
                state = state_candidate
                break

    if not state and city:
        state = _normalise_state(city)

    return city, state, postal_code


def _standardize_time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    lower = cleaned.lower()
    replacements = {
        ".": ":",
        "–": "-",
        "—": "-",
        "hrs": "",
        "hours": "",
    }
    for needle, repl in replacements.items():
        lower = lower.replace(needle, repl)
    lower = lower.replace(" ", "")
    candidates = [
        "%H:%M",
        "%H%M",
        "%I:%M%p",
        "%I%p",
        "%I%M%p",
        "%I.%M%p",
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(lower.upper(), fmt)
            return dt.strftime("%H:%M")
        except ValueError:
            continue
    # Handle cases like "9:00" after stripping spaces
    if len(lower) == 4 and lower.isdigit():
        return f"{lower[:2]}:{lower[2:]}"
    if len(lower) == 5 and lower[2] == ":":
        try:
            datetime.strptime(lower, "%H:%M")
            return lower
        except ValueError:
            return None
    return None


def _parse_hours_range(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    expanded = value.replace("–", "-").replace("—", "-")
    separators = [" to ", "-", "–", "—", "–", "—"]
    for sep in separators:
        if sep in expanded:
            parts = [part.strip() for part in expanded.split(sep, 1)]
            if len(parts) == 2:
                return _standardize_time(parts[0]), _standardize_time(parts[1])
    return _standardize_time(expanded), None


def _coerce_services_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [part.strip() for part in stripped.replace("|", ",").split(",") if part.strip()]
    return []


def _normalise_outlet_payload(raw: dict[str, Any]) -> dict[str, Any]:
    def extract(key: str, default: Any = None) -> Any:
        value: Any = raw
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part, default)
            else:
                value = default
                break
        return value

    title_value = extract("title")
    if isinstance(title_value, dict):
        title_value = title_value.get("rendered") or title_value.get("raw")
    name = html.unescape(str(title_value or raw.get("name") or raw.get("storeName") or raw.get("outlet") or raw.get("outletName") or "")).strip()
    if not name:
        raise ValueError("Outlet missing name.")

    external_id_raw = raw.get("externalId") or raw.get("external_id") or raw.get("slug") or raw.get("permalink")
    if isinstance(external_id_raw, dict):
        external_id_raw = external_id_raw.get("rendered") or external_id_raw.get("raw")
    if not external_id_raw:
        post_id = raw.get("id")
        if post_id is not None:
            external_id = f"wp-{post_id}"
        else:
            external_id = _slugify(name)
    else:
        external_id = str(external_id_raw).strip()
    if not external_id:
        external_id = _slugify(name)

    address_value = raw.get("address")
    if isinstance(address_value, dict):
        address_value = address_value.get("rendered") or address_value.get("text")
    if not address_value:
        content_value = extract("content")
        if isinstance(content_value, dict):
            address_value = content_value.get("rendered")
        else:
            address_value = content_value
    if not address_value:
        excerpt_value = extract("excerpt")
        if isinstance(excerpt_value, dict):
            address_value = excerpt_value.get("rendered")
        else:
            address_value = excerpt_value
    address = _strip_html_text(address_value)
    if isinstance(address, list):
        address = ", ".join(str(part).strip() for part in address if str(part).strip())

    if not address:
        raise ValueError(f"Outlet {name!r} missing address.")

    city_hint_raw = raw.get("city") or raw.get("region")
    state_hint_raw = raw.get("state") or raw.get("province")
    city_hint = _strip_html_text(city_hint_raw) or None
    state_hint = _strip_html_text(state_hint_raw) or None

    open_time_value = extract("hours.open") or extract("operatingHours.open") or extract("openingHours.open") or raw.get("openTime") or raw.get("open_time") or raw.get("open")
    close_time_value = extract("hours.close") or extract("operatingHours.close") or extract("openingHours.close") or raw.get("closeTime") or raw.get("close_time") or raw.get("close")
    hours_text = extract("hours") or extract("operatingHours") or extract("openingHours") or raw.get("hoursText") or raw.get("businessHours")
    if isinstance(hours_text, dict):
        hours_text = hours_text.get("range") or hours_text.get("text")

    open_standard = _standardize_time(open_time_value)
    close_standard = _standardize_time(close_time_value)
    if (open_standard is None or close_standard is None) and isinstance(hours_text, str):
        range_open, range_close = _parse_hours_range(hours_text)
        open_standard = open_standard or range_open
        close_standard = close_standard or range_close

    services = _coerce_services_list(raw.get("services") or raw.get("servicesJson") or raw.get("service") or raw.get("amenities") or raw.get("capabilities"))

    if open_standard is None:
        logger.debug("Outlet %s missing open time; defaulting to None", name)
    if close_standard is None:
        logger.debug("Outlet %s missing close time; defaulting to None", name)

    city, state, postal_code = _extract_city_state_postal(address, city_hint=city_hint, state_hint=state_hint)

    return {
        "externalId": external_id,
        "name": str(name).strip(),
        "address": str(address).strip(),
        "city": city,
        "state": state,
        "postalCode": postal_code,
        "openTime": open_standard,
        "closeTime": close_standard,
        "services": services,
    }


def _default_db_url() -> str:
    settings = AppSettings()
    backend = (settings.outlets_db_backend or "sqlite").strip().lower()
    postgres_url = (settings.outlets_postgres_url or "").strip()
    sqlite_url = (settings.outlets_sqlite_url or DEFAULT_SQLITE_DB_URL).strip()
    if backend == "postgres":
        if postgres_url:
            return postgres_url
        raise ValueError(
            "OUTLETS_POSTGRES_URL must be set when OUTLETS_DB_BACKEND=postgres."
        )
    return sqlite_url


def load_outlets_from_csv(path: Path) -> List[OutletRecord]:
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found at {path}")

    records: list[OutletRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing headers.")
        missing = [field for field in CSV_FIELDNAMES if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV file is missing required columns: {', '.join(missing)}")

        for row in reader:
            if not any(row.values()):
                continue
            for optional_key in ("city", "state", "postalCode"):
                row.setdefault(optional_key, None)
            try:
                record = OutletRecord.model_validate(row)
            except ValidationError as exc:
                raise ValueError(f"Invalid outlet row {row}: {exc}") from exc
            records.append(record)

    if not records:
        raise ValueError("CSV file did not contain any outlet records.")

    return records


def _fetch_wp_category_posts(endpoint_url: str, category_id: int) -> list[dict[str, Any]]:
    parsed = urlparse(endpoint_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rest_url = urljoin(base, "/wp-json/wp/v2/posts")
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        params = {
            "categories": category_id,
            "per_page": 100,
            "page": page,
            "_fields": "id,slug,title.rendered,content.rendered,excerpt.rendered",
        }
        resp = httpx.get(rest_url, params=params, timeout=30.0)
        if resp.status_code == 400 and "rest_post_invalid_page_number" in resp.text:
            break
        resp.raise_for_status()
        chunk = resp.json()
        if not isinstance(chunk, list) or not chunk:
            break
        results.extend(chunk)
        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    return results


def _parse_outlets_json(payload: Any) -> List[OutletRecord]:
    candidates = payload
    if isinstance(payload, dict):
        for key in ("stores", "outlets", "data", "items", "results", "locations"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
    if not isinstance(candidates, list):
        raise ValueError("Endpoint JSON must contain a list of outlets.")

    records: list[OutletRecord] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        try:
            normalised = _normalise_outlet_payload(item)
            records.append(OutletRecord.model_validate(normalised))
        except ValueError as exc:
            logger.debug("Skipping outlet due to validation error: %s", exc)
            continue
    if not records:
        raise ValueError("Endpoint JSON did not contain any valid outlet records.")
    return records


def _parse_outlets_html(html: str, endpoint_url: str) -> List[OutletRecord]:
    match = re.search(r"var\s+ecs_ajax_params\s*=\s*(\{.*?\});", html, re.DOTALL)
    if match:
        try:
            config = json.loads(match.group(1))
            posts_conf_raw = config.get("posts")
            if posts_conf_raw:
                posts_conf = json.loads(posts_conf_raw)
                category_id = posts_conf.get("cat")
                if category_id is not None:
                    wp_posts = _fetch_wp_category_posts(endpoint_url, int(category_id))
                    if wp_posts:
                        return _parse_outlets_json(wp_posts)
        except json.JSONDecodeError as exc:
            logger.debug("Failed to parse ecs_ajax_params: %s", exc)

    soup = BeautifulSoup(html, "html.parser")
    for script_tag in soup.find_all("script"):
        script_content = (script_tag.string or script_tag.text or "").strip()
        if not script_content:
            continue
        try:
            payload = json.loads(script_content)
        except json.JSONDecodeError:
            continue
        try:
            return _parse_outlets_json(payload)
        except ValueError:
            continue
    records: list[OutletRecord] = []
    for article in soup.select("article.elementor-post"):
        title_node = article.select_one(".elementor-widget-theme-post-title .elementor-heading-title")
        content_node = article.select_one(".elementor-widget-theme-post-content")
        name = title_node.get_text(" ", strip=True) if title_node else ""
        address = content_node.get_text(" ", strip=True) if content_node else ""
        payload = {"name": name, "address": address}
        try:
            normalised = _normalise_outlet_payload(payload)
            records.append(OutletRecord.model_validate(normalised))
        except ValueError as exc:
            logger.debug("Skipping outlet from HTML article: %s", exc)
            continue

    if records:
        return records

    raise ValueError("Endpoint HTML did not contain parsable outlet data.")


def load_outlets_from_endpoint(url: str) -> List[OutletRecord]:
    logger.info("Fetching outlet data from %s", url)
    resp = httpx.get(url, timeout=30.0)
    if resp.status_code >= 400:
        raise ValueError(f"Endpoint {url} returned status {resp.status_code}")
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    text = resp.text
    if "application/json" in content_type or (text and text.lstrip().startswith(("{", "["))):
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise ValueError("Endpoint did not return valid JSON payload.") from exc
        return _parse_outlets_json(payload)
    return _parse_outlets_html(text, url)


def _prepare_engine(db_url: str):
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database:
        db_path = Path(url.database).expanduser()
        if not db_path.is_absolute():
            db_path = (Path.cwd() / db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(db_path))
    engine = create_engine(url, future=True)
    return engine


def seed_outlets(*, records: Iterable[OutletRecord], db_url: str) -> SeedResult:
    records = list(records)
    if not records:
        raise ValueError("No outlet records were provided.")

    engine = _prepare_engine(db_url)
    Base.metadata.create_all(engine)

    result = SeedResult()
    try:
        with Session(engine) as session:
            for record in records:
                stmt = select(Outlet).where(Outlet.external_id == record.external_id)
                outlet = session.execute(stmt).scalar_one_or_none()
                if outlet is None:
                    outlet = Outlet(
                        external_id=record.external_id,
                        name=record.name,
                        city=record.city,
                        state=record.state,
                        postal_code=record.postal_code,
                        address=record.address,
                        open_time=record.open_time,
                        close_time=record.close_time,
                        services=record.services,
                    )
                    session.add(outlet)
                    result.inserted += 1
                else:
                    outlet.name = record.name
                    outlet.city = record.city
                    outlet.state = record.state
                    outlet.postal_code = record.postal_code
                    outlet.address = record.address
                    outlet.open_time = record.open_time
                    outlet.close_time = record.close_time
                    outlet.services = record.services
                    result.updated += 1
            session.commit()
    except SQLAlchemyError as exc:
        logger.error("Failed to seed outlets database: %s", exc)
        raise

    logger.info(
        "Seeded outlets database at %s (inserted=%d, updated=%d)",
        db_url,
        result.inserted,
        result.updated,
    )
    return result


def _gather_records(args: argparse.Namespace) -> List[OutletRecord]:
    errors: list[Exception] = []
    endpoint_candidates: list[str] = []
    if not getattr(args, "skip_endpoint", False):
        if getattr(args, "endpoint", None):
            endpoint_candidates.append(args.endpoint)
        else:
            endpoint_candidates.extend(DEFAULT_ENDPOINTS)

    for endpoint in endpoint_candidates:
        try:
            return load_outlets_from_endpoint(endpoint)
        except Exception as exc:  # pragma: no cover - logged and optionally re-raised
            logger.error("Failed to load outlets from endpoint %s: %s", endpoint, exc)
            errors.append(exc)
            if getattr(args, "fail_on_endpoint_error", False):
                raise

    if getattr(args, "csv", None):
        return load_outlets_from_csv(Path(args.csv))

    if errors:
        raise errors[0]
    raise ValueError("No outlet data source could be loaded.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the outlets database (SQLite or Postgres) from CSV/endpoint data.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/outlets/outlets.csv"),
        help="Path to the outlets CSV file.",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help=f"HTTP endpoint providing real-time outlet data (default: {DEFAULT_ENDPOINT}).",
    )
    parser.add_argument(
        "--skip-endpoint",
        action="store_true",
        help="Skip fetching the remote endpoint and rely solely on CSV data.",
    )
    parser.add_argument(
        "--fail-on-endpoint-error",
        action="store_true",
        help="Abort seeding if the endpoint fetch fails instead of falling back to CSV.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=_default_db_url(),
        help="SQLAlchemy database URL for outlets (SQLite or Postgres).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = _gather_records(args)
    seed_outlets(records=records, db_url=args.db)


if __name__ == "__main__":
    main()


