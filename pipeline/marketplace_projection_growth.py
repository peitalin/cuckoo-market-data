from __future__ import annotations

import csv
import html
import json
import math
import random
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any
from typing import Sequence

try:
    from .assumptions import MAU_ASSUMPTIONS
    from .assumptions import PROJECTION_MONTHS
    from .assumptions import REVENUE_ASSUMPTIONS
    from .runtime_config import DATA_PATHS
except ImportError:
    from assumptions import MAU_ASSUMPTIONS
    from assumptions import PROJECTION_MONTHS
    from assumptions import REVENUE_ASSUMPTIONS
    from runtime_config import DATA_PATHS

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"
MARKETPLACE_FINANCE_DIR = DATA_DIR


@dataclass(frozen=True)
class Chrono24VisitsPoint:
    month_start: date
    visits: int
    desktop_visits: int
    mobile_visits: int


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _month_delta(anchor: date, value: date) -> int:
    return (value.year - anchor.year) * 12 + (value.month - anchor.month)


def _decode_astro_serialized(node: Any) -> Any:
    if isinstance(node, list) and len(node) == 2 and isinstance(node[0], int):
        tag, payload = node
        if tag == 0:
            if isinstance(payload, dict):
                return {key: _decode_astro_serialized(value) for key, value in payload.items()}
            if isinstance(payload, list):
                return [_decode_astro_serialized(value) for value in payload]
            return payload
        if tag == 1:
            return [_decode_astro_serialized(value) for value in payload]
        return payload
    if isinstance(node, dict):
        return {key: _decode_astro_serialized(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_decode_astro_serialized(value) for value in node]
    return node


def _fetch_chrono24_visits_series(url: str) -> list[Chrono24VisitsPoint]:
    html_text = ""
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
            break
        except Exception:
            if attempt == attempts:
                fallback = subprocess.run(
                    ["curl", "-L", "--silent", "--max-time", "60", url],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if fallback.returncode == 0 and fallback.stdout.strip():
                    html_text = fallback.stdout
                    break
                raise
            time.sleep(attempt * 1.5)

    match = re.search(r'<astro-island[^>]*\sprops=\"([^\"]+)\"[^>]*>', html_text)
    if not match:
        raise ValueError("unable to locate Semrush astro props payload")

    props_raw = html.unescape(match.group(1))
    parsed = json.loads(props_raw)
    decoded = _decode_astro_serialized(parsed)

    history = (
        decoded.get("page", {})
        .get("data", {})
        .get("trafficByDevice", {})
        .get("history", [])
    )
    if not isinstance(history, list) or not history:
        raise ValueError("Semrush payload did not include trafficByDevice.history")

    output: list[Chrono24VisitsPoint] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        display_date = str(row.get("displayDate") or "").strip()
        if not display_date:
            continue
        month_key = date.fromisoformat(display_date)
        visits = int(float(row.get("visits") or 0))
        desktop = int(float(row.get("desktopVisits") or 0))
        mobile = int(float(row.get("mobileVisits") or 0))
        output.append(
            Chrono24VisitsPoint(
                month_start=_month_start(month_key),
                visits=visits,
                desktop_visits=desktop,
                mobile_visits=mobile,
            )
        )

    if not output:
        raise ValueError("Semrush trafficByDevice history produced no valid rows")

    return sorted(output, key=lambda item: item.month_start)


def _write_reference_visits_csv(path: Path, rows: list[Chrono24VisitsPoint], source_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "month",
                "visits",
                "desktop_visits",
                "mobile_visits",
                "source_url",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "month": row.month_start.isoformat(),
                    "visits": row.visits,
                    "desktop_visits": row.desktop_visits,
                    "mobile_visits": row.mobile_visits,
                    "source_url": source_url,
                }
            )


def _read_sales_projection(path: Path) -> dict[date, dict[str, float]]:
    if not path.exists():
        raise FileNotFoundError(f"sales projection input not found: {path}")
    rows: dict[date, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            month_text = (row.get("month") or "").strip()
            if not month_text:
                continue
            month_key = date.fromisoformat(month_text)
            rows[month_key] = {
                "gmv_usd": float(
                    (
                        row.get("gross_market_value_usd")
                        or row.get("gmv_usd")
                        or "0"
                    ).strip()
                    or "0"
                ),
                "transaction_count": float(
                    (row.get("transaction_count") or "0").strip() or "0"
                ),
            }
    if len(rows) != PROJECTION_MONTHS:
        raise ValueError(
            f"expected {PROJECTION_MONTHS} rows in sales projection, found {len(rows)} ({path})"
        )
    return rows


def _read_seasonality_factors(path: Path) -> dict[int, float]:
    if not path.exists():
        return {month: 1.0 for month in range(1, 13)}
    latest_by_month: dict[int, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            month_text = (row.get("month") or "").strip()
            blended_text = (row.get("blended_factor") or "").strip()
            if not month_text or not blended_text:
                continue
            month = int(month_text)
            latest_by_month[month] = float(blended_text)
    if len(latest_by_month) < 12:
        return {month: latest_by_month.get(month, 1.0) for month in range(1, 13)}
    return latest_by_month


def _sigmoid_progress(position: float, total: float, steepness: float = 8.0) -> float:
    if total <= 0:
        return 1.0
    x = max(0.0, min(1.0, position / total))
    # Normalized sigmoid from 0..1.
    lower = 1.0 / (1.0 + math.exp(steepness / 2.0))
    upper = 1.0 / (1.0 + math.exp(-steepness / 2.0))
    raw = 1.0 / (1.0 + math.exp(-steepness * (x - 0.5)))
    return (raw - lower) / (upper - lower)


def _lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * max(0.0, min(1.0, progress))


def _piecewise_month_value(
    month_number: int,
    *,
    month_1: float,
    month_6: float,
    month_12: float,
    month_36: float,
) -> float:
    if month_number <= 6:
        return _lerp(month_1, month_6, (month_number - 1) / 5.0)
    if month_number <= 12:
        return _lerp(month_6, month_12, (month_number - 6) / 6.0)
    return _lerp(month_12, month_36, (month_number - 12) / 24.0)


def _year1_mau(index: int, scale: float) -> float:
    return float(MAU_ASSUMPTIONS.year1_mau_trajectory[index]) * max(0.0, scale)


def _project_post_year1_mau(previous_mau: float, index: int, rng: random.Random) -> float:
    # Decelerating growth profile after the first 12 months:
    # still strong in early Year 2, then gradually normalizing.
    post_year1_index = index - 12
    progress = _sigmoid_progress(post_year1_index, 23)
    base_mom_growth = _lerp(0.22, 0.06, progress)
    noise = max(0.88, min(1.12, 1.0 + rng.gauss(0.0, 0.035)))
    growth = max(0.03, base_mom_growth * noise)
    return max(previous_mau * 1.03, previous_mau * (1.0 + growth))


def _normalized_shares(shares: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in shares.values())
    if total <= 0:
        n = max(1, len(shares))
        return {key: 1.0 / n for key in shares.keys()}
    return {key: max(0.0, value) / total for key, value in shares.items()}


def _allocate_counts(total: int, shares: dict[str, float]) -> dict[str, int]:
    normalized = _normalized_shares(shares)
    raw = {key: normalized[key] * max(0, total) for key in normalized.keys()}
    floored = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = max(0, total - sum(floored.values()))
    ranked = sorted(
        normalized.keys(),
        key=lambda key: (raw[key] - floored[key]),
        reverse=True,
    )
    for key in ranked[:remainder]:
        floored[key] += 1
    return floored


def _traffic_source_shares(month_number: int) -> dict[str, float]:
    # Anchors from user-provided trajectory:
    # Month 6: X 48%, IG 24%, Direct 18%, SEO 6%, Referrals 4%
    # Month 12 counts target: X 9000, IG 6000, Direct 8500, SEO 3500, Referrals 1000 (at 28k MAU)
    return _normalized_shares(
        {
            "twitter_x": _piecewise_month_value(
                month_number,
                month_1=0.70,
                month_6=0.48,
                month_12=9000.0 / 28000.0,
                month_36=0.24,
            ),
            "instagram": _piecewise_month_value(
                month_number,
                month_1=0.10,
                month_6=0.24,
                month_12=6000.0 / 28000.0,
                month_36=0.16,
            ),
            "direct_repeat": _piecewise_month_value(
                month_number,
                month_1=0.15,
                month_6=0.18,
                month_12=8500.0 / 28000.0,
                month_36=0.39,
            ),
            "seo": _piecewise_month_value(
                month_number,
                month_1=0.03,
                month_6=0.06,
                month_12=3500.0 / 28000.0,
                month_36=0.15,
            ),
            "referrals": _piecewise_month_value(
                month_number,
                month_1=0.02,
                month_6=0.04,
                month_12=1000.0 / 28000.0,
                month_36=0.06,
            ),
        }
    )


def _segment_shares(month_number: int) -> dict[str, float]:
    # Month 12 target from user prompt:
    # Casual 45%, Serious 30%, Flippers 15%, Dealers 10%
    return _normalized_shares(
        {
            "casual_enthusiasts": _piecewise_month_value(
                month_number,
                month_1=0.65,
                month_6=0.56,
                month_12=0.45,
                month_36=0.40,
            ),
            "serious_collectors": _piecewise_month_value(
                month_number,
                month_1=0.20,
                month_6=0.25,
                month_12=0.30,
                month_36=0.32,
            ),
            "flippers_traders": _piecewise_month_value(
                month_number,
                month_1=0.10,
                month_6=0.13,
                month_12=0.15,
                month_36=0.17,
            ),
            "dealers": _piecewise_month_value(
                month_number,
                month_1=0.05,
                month_6=0.06,
                month_12=0.10,
                month_36=0.11,
            ),
        }
    )


def _growth_stage_from_mau(mau: float) -> str:
    if mau < 5000:
        return "content_market_fit_0_to_5k"
    if mau < 15000:
        return "behavior_forming_5k_to_15k"
    if mau < 30000:
        return "early_marketplace_substrate_15k_to_30k"
    return "scaled_marketplace_layer_30k_plus"


def _product_feel(month_number: int) -> str:
    if month_number <= 3:
        return "content_site"
    if month_number <= 8:
        return "tool"
    return "habit_layer"


def _phase_label(index: int) -> str:
    if index < 12:
        return "phase_1_user_growth"
    if index < 24:
        return "phase_2_marketplace_activation"
    return "phase_3_projection"


def _project_chrono24_reference_visits(
    months: list[date],
    observed_points: list[Chrono24VisitsPoint],
    seasonal_factors: dict[int, float],
    benchmark_cagr: float,
) -> dict[date, float]:
    observed_by_month = {point.month_start: float(point.visits) for point in observed_points}
    latest_observed_month = max(observed_by_month.keys())
    latest_observed_visits = observed_by_month[latest_observed_month]
    latest_factor = seasonal_factors[latest_observed_month.month]

    projected: dict[date, float] = {}
    for month in months:
        if month in observed_by_month:
            projected[month] = observed_by_month[month]
            continue
        months_from_latest = _month_delta(latest_observed_month, month)
        growth = math.pow(1 + benchmark_cagr, months_from_latest / 12)
        season_ratio = seasonal_factors[month.month] / latest_factor
        projected[month] = latest_observed_visits * growth * season_ratio
    return projected


def _build_projection_rows(
    months: list[date],
    sales_projection: dict[date, dict[str, float]],
    chrono24_reference_visits: dict[date, float],
    premium_price_usd: float,
    take_rate: float,
    fee_switch_mau_threshold: float,
    fee_switch_retention_threshold: float,
    year1_mau_scale: float,
    seed: int,
) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    fee_switch_on = False
    previous_mau = 0.0

    for index, month in enumerate(months):
        month_number = index + 1
        phase = _phase_label(index)
        visits = chrono24_reference_visits[month]

        if index < 12:
            mau = _year1_mau(index, year1_mau_scale)
        else:
            mau = _project_post_year1_mau(previous_mau, index, rng)

        source_shares = _traffic_source_shares(month_number)
        source_counts = _allocate_counts(round(mau), source_shares)
        segment_shares = _segment_shares(month_number)
        segment_counts = _allocate_counts(round(mau), segment_shares)

        dau_ratio = _piecewise_month_value(
            month_number,
            month_1=0.12,
            month_6=0.18,
            month_12=0.25,
            month_36=0.28,
        )
        dau = mau * dau_ratio

        avg_sessions_per_user_month = _piecewise_month_value(
            month_number,
            month_1=2.1,
            month_6=3.2,
            month_12=5.5,
            month_36=6.2,
        )
        analytics_dashboard_view_rate = _piecewise_month_value(
            month_number,
            month_1=0.72,
            month_6=0.65,
            month_12=0.62,
            month_36=0.58,
        )
        listing_click_rate = _piecewise_month_value(
            month_number,
            month_1=0.16,
            month_6=0.25,
            month_12=0.35,
            month_36=0.42,
        )
        high_intent_user_rate = _piecewise_month_value(
            month_number,
            month_1=0.04,
            month_6=0.09,
            month_12=0.12,
            month_36=0.16,
        )
        repeat_user_rate = _piecewise_month_value(
            month_number,
            month_1=0.12,
            month_6=0.28,
            month_12=0.41,
            month_36=0.55,
        )
        power_user_rate = _piecewise_month_value(
            month_number,
            month_1=0.05,
            month_6=0.11,
            month_12=0.20,
            month_36=0.27,
        )

        visitor_to_signup_rate = _piecewise_month_value(
            month_number,
            month_1=0.015,
            month_6=0.023,
            month_12=0.033,
            month_36=0.038,
        )
        if month_number <= 3:
            signup_to_buyer_rate = 0.0
        else:
            signup_to_buyer_rate = _piecewise_month_value(
                month_number,
                month_1=0.0,
                month_6=0.008,
                month_12=0.022,
                month_36=0.050,
            )

        mau_to_buyer_conversion_rate = visitor_to_signup_rate * signup_to_buyer_rate
        buyer_count = round(mau * mau_to_buyer_conversion_rate)

        retention_1m = _piecewise_month_value(
            month_number,
            month_1=0.26,
            month_6=0.42,
            month_12=0.58,
            month_36=0.72,
        )
        retention_3m = max(0.10, retention_1m - 0.13)
        retention_12m = _piecewise_month_value(
            month_number,
            month_1=0.08,
            month_6=0.20,
            month_12=0.32,
            month_36=0.46,
        )

        if previous_mau <= 0:
            acquired_users = mau
        else:
            acquired_users = max(0.0, mau - previous_mau * retention_1m)

        cac_usd = _piecewise_month_value(
            month_number,
            month_1=185.0,
            month_6=145.0,
            month_12=105.0,
            month_36=58.0,
        )
        marketing_spend_usd = acquired_users * cac_usd

        premium_rate = (
            0.030
            if phase == "phase_1_user_growth"
            else 0.024 if phase == "phase_2_marketplace_activation" else 0.020
        )
        premium_subscribers = round(mau * premium_rate)
        subscription_revenue_usd = premium_subscribers * premium_price_usd

        if not fee_switch_on:
            if mau >= fee_switch_mau_threshold and retention_3m >= fee_switch_retention_threshold:
                fee_switch_on = True

        gmv_usd = sales_projection.get(month, {}).get("gmv_usd", 0.0)
        marketplace_fee_revenue_usd = gmv_usd * take_rate if fee_switch_on else 0.0
        total_revenue_usd = subscription_revenue_usd + marketplace_fee_revenue_usd

        rows.append(
            {
                "month": month.isoformat(),
                "phase": phase,
                "growth_stage": _growth_stage_from_mau(mau),
                "product_feel": _product_feel(month_number),
                "chrono24_reference_visits": f"{visits:.0f}",
                "assumed_market_share": f"{(mau / max(1.0, visits)):.6f}",
                "mau": f"{mau:.0f}",
                "dau": f"{dau:.0f}",
                "dau_mau_ratio": f"{dau_ratio:.4f}",
                "avg_sessions_per_user_month": f"{avg_sessions_per_user_month:.2f}",
                "analytics_dashboard_view_rate": f"{analytics_dashboard_view_rate:.4f}",
                "listing_click_rate": f"{listing_click_rate:.4f}",
                "high_intent_user_rate": f"{high_intent_user_rate:.4f}",
                "repeat_user_rate": f"{repeat_user_rate:.4f}",
                "power_user_rate": f"{power_user_rate:.4f}",
                "twitter_x_share": f"{source_shares['twitter_x']:.4f}",
                "instagram_share": f"{source_shares['instagram']:.4f}",
                "direct_repeat_share": f"{source_shares['direct_repeat']:.4f}",
                "seo_share": f"{source_shares['seo']:.4f}",
                "referrals_share": f"{source_shares['referrals']:.4f}",
                "twitter_x_users": str(source_counts["twitter_x"]),
                "instagram_users": str(source_counts["instagram"]),
                "direct_repeat_users": str(source_counts["direct_repeat"]),
                "seo_users": str(source_counts["seo"]),
                "referrals_users": str(source_counts["referrals"]),
                "casual_enthusiasts_share": f"{segment_shares['casual_enthusiasts']:.4f}",
                "serious_collectors_share": f"{segment_shares['serious_collectors']:.4f}",
                "flippers_traders_share": f"{segment_shares['flippers_traders']:.4f}",
                "dealers_share": f"{segment_shares['dealers']:.4f}",
                "casual_enthusiasts_users": str(segment_counts["casual_enthusiasts"]),
                "serious_collectors_users": str(segment_counts["serious_collectors"]),
                "flippers_traders_users": str(segment_counts["flippers_traders"]),
                "dealers_users": str(segment_counts["dealers"]),
                "acquired_users": f"{acquired_users:.0f}",
                "cac_usd": f"{cac_usd:.2f}",
                "marketing_spend_usd": f"{marketing_spend_usd:.2f}",
                "visitor_to_signup_rate": f"{visitor_to_signup_rate:.4f}",
                "signup_to_buyer_rate": f"{signup_to_buyer_rate:.4f}",
                "mau_to_buyer_conversion_rate": f"{mau_to_buyer_conversion_rate:.5f}",
                "buyer_count": str(buyer_count),
                "retention_1m": f"{retention_1m:.4f}",
                "retention_3m": f"{retention_3m:.4f}",
                "retention_12m": f"{retention_12m:.4f}",
                "premium_subscriber_rate": f"{premium_rate:.4f}",
                "premium_subscribers": str(premium_subscribers),
                "premium_price_usd": f"{premium_price_usd:.2f}",
                "subscription_revenue_usd": f"{subscription_revenue_usd:.2f}",
                "marketplace_gmv_usd": f"{gmv_usd:.2f}",
                "fee_switch_on": "true" if fee_switch_on else "false",
                "take_rate": f"{take_rate:.4f}",
                "take_rate_assumption": f"{take_rate:.4f}",
                "marketplace_fee_revenue_usd": f"{marketplace_fee_revenue_usd:.2f}",
                "total_revenue_usd": f"{total_revenue_usd:.2f}",
            }
        )
        previous_mau = mau
    return rows


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8") as handle:
            handle.write("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    sales_input = MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_marketplace_fees_csv
    output = MARKETPLACE_FINANCE_DIR / DATA_PATHS.growth_projection_csv
    chrono24_reference_output = DATA_DIR / DATA_PATHS.traffic_reference_csv
    seasonality_input = DATA_DIR / DATA_PATHS.seasonality_factors_csv

    sales_projection = _read_sales_projection(sales_input)
    months = sorted(sales_projection.keys())
    observed_visits = _fetch_chrono24_visits_series(MAU_ASSUMPTIONS.semrush_chrono24_url)
    _write_reference_visits_csv(
        chrono24_reference_output,
        observed_visits,
        source_url=MAU_ASSUMPTIONS.semrush_chrono24_url,
    )

    seasonal_factors = _read_seasonality_factors(seasonality_input)
    chrono24_reference_visits = _project_chrono24_reference_visits(
        months=months,
        observed_points=observed_visits,
        seasonal_factors=seasonal_factors,
        benchmark_cagr=MAU_ASSUMPTIONS.benchmark_traffic_cagr,
    )
    projection_rows = _build_projection_rows(
        months=months,
        sales_projection=sales_projection,
        chrono24_reference_visits=chrono24_reference_visits,
        premium_price_usd=REVENUE_ASSUMPTIONS.subscription_price_usd,
        take_rate=REVENUE_ASSUMPTIONS.take_rate,
        fee_switch_mau_threshold=MAU_ASSUMPTIONS.fee_switch_mau_threshold,
        fee_switch_retention_threshold=MAU_ASSUMPTIONS.fee_switch_retention_threshold,
        year1_mau_scale=MAU_ASSUMPTIONS.year1_mau_scale,
        seed=REVENUE_ASSUMPTIONS.seed,
    )
    _write_csv(output, projection_rows)

    observed_mean = mean(point.visits for point in observed_visits)
    print(f"rows_written={len(projection_rows)}")
    print(f"output={output}")
    print(f"chrono24_observed_points={len(observed_visits)}")
    print(f"chrono24_observed_mean_visits={observed_mean:.0f}")
    print(f"chrono24_reference_output={chrono24_reference_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
