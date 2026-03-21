from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from typing import Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

UTC = timezone.utc
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"
MARKETPLACE_FINANCE_DIR = DATA_DIR

try:
    from .runtime_config import DATA_PATHS
    from .runtime_config import EXPORT_API_CONFIG
except ImportError:
    from runtime_config import DATA_PATHS
    from runtime_config import EXPORT_API_CONFIG
MARKETPLACE_SALES_FIELDNAMES = [
    "date",
    "sold_at",
    "source",
    "listing_id",
    "seller_id",
    "seller_type",
    "sale_mechanism",
    "brand",
    "model",
    "reference",
    "condition",
    "currency",
    "sale_price",
    "days_to_sell",
    "sell_speed_eligible",
    "sold_inference",
]


def _parse_sources(value: str) -> list[str]:
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    if not parsed:
        return []
    lowered = {item.lower() for item in parsed}
    if "all" in lowered or "*" in lowered:
        return []
    return sorted(set(parsed))


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for pattern in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S%z",
        ):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_optional_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return _parse_timestamp(text)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_iso_date_from_timestamp(value: str) -> str:
    parsed = _parse_timestamp(value)
    if parsed is not None:
        return parsed.date().isoformat()
    if "T" in value:
        return value.split("T", 1)[0]
    return value


def _normalize_analysis_api_base_url(value: str) -> str:
    base = value.strip()
    if not base:
        raise RuntimeError("analysis api base URL must not be empty")
    while base.endswith("/"):
        base = base[:-1]
    if base.endswith("/v1/analysis/artifacts"):
        return base[: -len("/artifacts")]
    if base.endswith("/v1/analysis"):
        return base
    if "/v1/analysis/" in base:
        return base.split("/v1/analysis/", 1)[0] + "/v1/analysis"
    if "://" in base:
        return base + "/v1/analysis"
    raise RuntimeError(f"invalid analysis api base URL: {value}")


def _http_get_json(
    url: str,
    *,
    bearer_token: str | None,
    timeout_seconds: float,
) -> Any:
    headers: dict[str, str] = {
        "accept": "application/json",
        "user-agent": "watchbook-export-csv/1.0",
    }
    token = (bearer_token or "").strip()
    if token:
        headers["authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code in {401, 403}:
            raise RuntimeError(
                f"cloudflare api auth failed ({error.code}) for {url}. "
                "Set --analysis-api-bearer-token or ANALYSIS_API_BEARER_TOKEN."
            ) from error
        raise RuntimeError(
            f"cloudflare api request failed ({error.code}) for {url}: {detail[:400]}"
        ) from error

    try:
        return json.loads(body)
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"cloudflare api returned non-JSON payload for {url}") from error


def _fetch_api_sold_listing_rows(
    *,
    analysis_api_base_url: str,
    bearer_token: str | None,
    timeout_seconds: float,
    page_size: int,
    min_sale_date: datetime | None,
    sales_sources: list[str] | None,
) -> list[dict[str, Any]]:
    collected_rows: list[dict[str, Any]] = []
    page = 1
    max_pages = 10000
    date_start = min_sale_date.date().isoformat() if min_sale_date is not None else None

    while page <= max_pages:
        query_items: list[tuple[str, str]] = [
            ("page", str(page)),
            ("page_size", str(page_size)),
        ]
        if date_start:
            query_items.append(("date_start", date_start))
        if sales_sources:
            for source in sales_sources:
                query_items.append(("source", source))

        url = f"{analysis_api_base_url}/sold_listings?{urlencode(query_items)}"
        payload = _http_get_json(
            url,
            bearer_token=bearer_token,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("cloudflare sold_listings response was not an object")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("cloudflare sold_listings payload missing data object")
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError("cloudflare sold_listings payload missing rows array")

        for row in rows:
            if isinstance(row, dict):
                collected_rows.append(row)

        pagination = data.get("pagination")
        has_next = False
        if isinstance(pagination, dict):
            has_next = bool(pagination.get("has_next"))
        if not has_next:
            break
        page += 1

    if page > max_pages:
        raise RuntimeError("cloudflare sold_listings pagination exceeded max_pages safety limit")

    return collected_rows


def _normalized_seller_type(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "unknown"
    lowered = text.lower()
    if "dealer" in lowered:
        return "dealer"
    if "private" in lowered:
        return "private"
    return "unknown"


def _sale_mechanism_for_source(source: str) -> str:
    source_key = source.strip().lower()
    if source_key in {"bezel_auctions", "ebay_auctions"}:
        return "auction"
    return "listing"


def _to_major_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value) / 100.0, 2)
    if isinstance(value, str) and value.strip():
        try:
            return round(float(value.strip()) / 100.0, 2)
        except ValueError:
            return None
    return None


def _extract_sale_price(row: dict[str, Any]) -> float | None:
    for key in (
        "price_minor",
        "transaction_price_minor",
        "sale_price_minor",
        "ask_price_minor",
    ):
        price = _to_major_price(row.get(key))
        if price is not None:
            return price
    return None


def _map_api_sold_rows_to_marketplace_sales_rows(
    api_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in api_rows:
        sold_at_raw = str(row.get("sold_at") or "").strip()
        if not sold_at_raw:
            continue
        source = str(row.get("source_site") or "unknown").strip() or "unknown"
        listing_id = str(row.get("source_listing_id") or "unknown").strip() or "unknown"
        seller_name = str(row.get("seller_name") or "").strip()
        seller_id = seller_name if seller_name else "unknown"

        mapped.append(
            {
                "date": _to_iso_date_from_timestamp(sold_at_raw),
                "sold_at": sold_at_raw,
                "source": source,
                "listing_id": listing_id,
                "seller_id": seller_id,
                "seller_type": _normalized_seller_type(str(row.get("seller_type") or "")),
                "sale_mechanism": _sale_mechanism_for_source(source),
                "brand": str(row.get("brand") or "unknown").strip() or "unknown",
                "model": str(row.get("model") or "unknown").strip() or "unknown",
                "reference": str(row.get("reference_number") or "unknown").strip() or "unknown",
                "condition": str(row.get("condition_text") or "unknown").strip() or "unknown",
                "currency": str(
                    row.get("price_currency")
                    or row.get("currency")
                    or "unknown"
                ).strip()
                or "unknown",
                "sale_price": _extract_sale_price(row),
                "days_to_sell": None,
                "sell_speed_eligible": False,
                "sold_inference": "api_sold_listing_state",
            }
        )

    mapped.sort(
        key=lambda item: (
            str(item.get("sold_at") or ""),
            str(item.get("source") or ""),
            str(item.get("listing_id") or ""),
        )
    )
    return mapped


def _fetch_and_write_gbp_usd_rates_csv(url: str, output_path: Path) -> int:
    with urlopen(url) as response:
        raw_csv = response.read().decode("utf-8")
    lines = [line for line in raw_csv.splitlines() if line.strip()]
    if len(lines) < 2:
        raise RuntimeError("GBP/USD rates response was empty")

    output_lines = ["date,usd_per_gbp"]
    for line in lines[1:]:
        raw_date, raw_rate = (line.split(",", 1) + [""])[:2]
        date_text = raw_date.strip()
        rate_text = raw_rate.strip()
        if not date_text or not rate_text or rate_text == ".":
            continue
        try:
            rate = float(rate_text)
        except ValueError:
            continue
        if rate <= 0:
            continue
        output_lines.append(f"{date_text},{rate}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return len(output_lines) - 1


def _load_gbp_usd_rates(path: Path) -> dict[date, float]:
    if not path.exists():
        return {}

    rates: dict[date, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_key = _parse_date((row.get("date") or row.get("DATE") or "").strip())
            rate_text = (row.get("usd_per_gbp") or row.get("DEXUSUK") or "").strip()
            if date_key is None or not rate_text or rate_text == ".":
                continue
            try:
                rate = float(rate_text)
            except ValueError:
                continue
            if rate <= 0:
                continue
            rates[date_key] = rate
    return rates


def _lookup_gbp_usd_rate(rates: dict[date, float], at_datetime: datetime | None) -> float | None:
    if not rates or at_datetime is None:
        return None

    target = at_datetime.date()
    if target in rates:
        return rates[target]

    min_date = min(rates.keys())
    probe = target - timedelta(days=1)
    while probe >= min_date:
        rate = rates.get(probe)
        if rate is not None:
            return rate
        probe -= timedelta(days=1)
    return None


def _convert_gbp_amount_to_usd(
    amount_text: str,
    currency_text: str,
    at_datetime: datetime | None,
    rates: dict[date, float],
) -> tuple[str, str]:
    amount = amount_text.strip()
    currency = (currency_text or "").strip().upper()
    if not amount or currency != "GBP":
        return amount_text, currency_text
    try:
        numeric_amount = float(amount)
    except ValueError:
        return amount_text, currency_text

    rate = _lookup_gbp_usd_rate(rates, at_datetime)
    if rate is None:
        return amount_text, currency_text
    converted = round(numeric_amount * rate, 2)
    return str(converted), "USD"


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [{key: (value or "") for key, value in row.items()} for row in reader]
    return fieldnames, rows


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _convert_marketplace_sales_prices_to_usd(path: Path, rates: dict[date, float]) -> int:
    fieldnames, rows = _read_csv_rows(path)
    if not rows:
        return 0
    converted_count = 0
    for row in rows:
        converted_price, converted_currency = _convert_gbp_amount_to_usd(
            row.get("sale_price", ""),
            row.get("currency", ""),
            _parse_timestamp(row.get("sold_at")),
            rates,
        )
        if converted_currency == "USD" and row.get("currency", "").strip().upper() == "GBP":
            converted_count += 1
        row["sale_price"] = converted_price
        row["currency"] = converted_currency
    _write_csv_rows(path, fieldnames, rows)
    return converted_count


def _aggregate_daily_sales(
    marketplace_sales_csv: Path,
    output_path: Path,
) -> None:
    with marketplace_sales_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    seller_sets: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        date_key = (row.get("date") or "").strip()
        source = (row.get("source") or "").strip() or "unknown"
        currency = (row.get("currency") or "").strip() or "unknown"
        sale_mechanism = (row.get("sale_mechanism") or "").strip() or "listing"
        seller_type = (row.get("seller_type") or "").strip() or "unknown"
        group_key = (date_key, source, currency, sale_mechanism, seller_type)

        if group_key not in grouped:
            grouped[group_key] = {
                "date": date_key,
                "source": source,
                "currency": currency,
                "sale_mechanism": sale_mechanism,
                "seller_type": seller_type,
                "sold_count": 0,
                "transaction_count": 0,
                "transaction_gross_market_value": 0.0,
                "distinct_seller_count": 0,
            }

        bucket = grouped[group_key]
        bucket["sold_count"] += 1
        sale_price_text = (row.get("sale_price") or "").strip()
        if sale_price_text:
            try:
                sale_price = float(sale_price_text)
            except ValueError:
                sale_price = 0.0
            bucket["transaction_count"] += 1
            bucket["transaction_gross_market_value"] += sale_price

        seller_id = (row.get("seller_id") or "").strip()
        if seller_id:
            seller_sets[group_key].add(seller_id)

    output_rows: list[dict[str, Any]] = []
    for group_key in sorted(grouped.keys()):
        bucket = grouped[group_key]
        bucket["distinct_seller_count"] = len(seller_sets.get(group_key, set()))
        output_rows.append(bucket)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "date",
            "source",
            "currency",
            "sale_mechanism",
            "seller_type",
            "sold_count",
            "transaction_count",
            "transaction_gross_market_value",
            "distinct_seller_count",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    marketplace_transactions_path = MARKETPLACE_FINANCE_DIR / DATA_PATHS.raw_marketplace_transactions_csv
    marketplace_daily_path = MARKETPLACE_FINANCE_DIR / DATA_PATHS.raw_marketplace_daily_sales_csv
    gbp_usd_rates_csv = DATA_DIR / DATA_PATHS.fx_gbp_usd_csv

    analysis_api_base_url = _normalize_analysis_api_base_url(
        EXPORT_API_CONFIG.analysis_api_base_url
    )
    bearer_token = (EXPORT_API_CONFIG.analysis_api_bearer_token or "").strip() or None
    sales_sources = (
        _parse_sources(EXPORT_API_CONFIG.sales_sources)
        if EXPORT_API_CONFIG.sales_sources
        else None
    )
    min_sale_date = _parse_optional_timestamp(EXPORT_API_CONFIG.min_sale_date)

    api_rows = _fetch_api_sold_listing_rows(
        analysis_api_base_url=analysis_api_base_url,
        bearer_token=bearer_token,
        timeout_seconds=max(float(EXPORT_API_CONFIG.analysis_api_timeout_seconds), 1.0),
        page_size=max(1, min(int(EXPORT_API_CONFIG.analysis_api_page_size), 100)),
        min_sale_date=min_sale_date,
        sales_sources=sales_sources,
    )
    marketplace_sales_rows = _map_api_sold_rows_to_marketplace_sales_rows(api_rows)
    _write_csv_rows(
        marketplace_transactions_path,
        MARKETPLACE_SALES_FIELDNAMES,
        marketplace_sales_rows,
    )

    gbp_usd_rate_rows = 0
    if not EXPORT_API_CONFIG.skip_fx_fetch:
        gbp_usd_rate_rows = _fetch_and_write_gbp_usd_rates_csv(
            EXPORT_API_CONFIG.gbp_usd_fred_url,
            gbp_usd_rates_csv,
        )
    rates = _load_gbp_usd_rates(gbp_usd_rates_csv)
    converted_sales_prices = _convert_marketplace_sales_prices_to_usd(
        marketplace_transactions_path,
        rates,
    )
    _aggregate_daily_sales(marketplace_transactions_path, marketplace_daily_path)

    print(f"analysis_api_base_url={analysis_api_base_url}")
    print(f"analysis_api_sold_rows={len(api_rows)}")
    print(f"marketplace_transactions_csv={marketplace_transactions_path}")
    print(f"marketplace_daily_sales_csv={marketplace_daily_path}")
    print(f"gbp_usd_rates_csv={gbp_usd_rates_csv}")
    print(f"gbp_usd_rate_rows={gbp_usd_rate_rows or len(rates)}")
    print(f"converted_marketplace_sales_gbp_rows={converted_sales_prices}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
