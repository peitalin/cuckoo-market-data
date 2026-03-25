from __future__ import annotations

import csv
import math
import random
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
    from .assumptions import PROJECTION_MONTHS
    from .assumptions import REVENUE_ASSUMPTIONS
    from .runtime_config import DATA_PATHS
except ImportError:
    from assumptions import PROJECTION_MONTHS
    from assumptions import REVENUE_ASSUMPTIONS
    from runtime_config import DATA_PATHS

FRED_SERIES = (
    (
        "MRTSSM44831USN",
        "US Census via FRED: Jewelry Stores Monthly Sales",
        0.7,
    ),
    (
        "RSXFS",
        "US Census via FRED: Retail and Food Services Sales Ex Autos",
        0.3,
    ),
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"
MARKETPLACE_FINANCE_DIR = DATA_DIR
SEASONALITY_DIR = DATA_DIR / "reference" / "seasonality"


@dataclass(frozen=True)
class BaselineMonth:
    month_start: date
    gmv_usd: float
    transaction_count: int


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _add_months(value: date, months: int) -> date:
    zero_based = value.month - 1 + months
    year = value.year + zero_based // 12
    month = zero_based % 12 + 1
    return date(year, month, 1)


def _sigmoid_progress(position: float, total: float, steepness: float = 8.0) -> float:
    if total <= 0:
        return 1.0
    x = max(0.0, min(1.0, position / total))
    lower = 1.0 / (1.0 + math.exp(steepness / 2.0))
    upper = 1.0 / (1.0 + math.exp(-steepness / 2.0))
    raw = 1.0 / (1.0 + math.exp(-steepness * (x - 0.5)))
    return (raw - lower) / (upper - lower)


def _read_daily_sales_monthly_baseline(
    input_csv: Path, baseline_month: str | None
) -> BaselineMonth:
    if not input_csv.exists():
        raise FileNotFoundError(f"input file not found: {input_csv}")

    gmv_by_month: dict[date, float] = {}
    txn_by_month: dict[date, int] = {}

    with input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_text = (row.get("date") or "").strip()
            if not date_text:
                continue
            day = date.fromisoformat(date_text)
            month_key = _month_start(day)

            gmv = float(
                (
                    row.get("transaction_gross_market_value")
                    or row.get("transaction_gmv")
                    or row.get("observed_sales_value")
                    or "0"
                ).strip()
                or "0"
            )
            observed_sale_count = int(
                float(
                    (
                        row.get("transaction_count")
                        or row.get("observed_sale_count")
                        or "0"
                    ).strip()
                    or "0"
                )
            )
            sold_count = int(float((row.get("sold_count") or "0").strip() or "0"))
            txn_count = observed_sale_count if observed_sale_count > 0 else sold_count

            gmv_by_month[month_key] = gmv_by_month.get(month_key, 0.0) + gmv
            txn_by_month[month_key] = txn_by_month.get(month_key, 0) + txn_count

    if not gmv_by_month:
        raise ValueError("no valid rows found in marketplace_daily_sales input")

    baseline_key = date.fromisoformat(f"{baseline_month}-01") if baseline_month else max(gmv_by_month.keys())
    gmv_usd = gmv_by_month.get(baseline_key, 0.0)
    transaction_count = txn_by_month.get(baseline_key, 0)
    if gmv_usd <= 0:
        raise ValueError(
            f"baseline month {baseline_key.isoformat()} has no transaction_gross_market_value/transaction_gmv/observed_sales_value > 0"
        )
    if transaction_count <= 0:
        raise ValueError(
            f"baseline month {baseline_key.isoformat()} has no transaction_count/observed_sale_count/sold_count > 0"
        )

    return BaselineMonth(
        month_start=baseline_key,
        gmv_usd=gmv_usd,
        transaction_count=transaction_count,
    )


def _fetch_fred_series(series_id: str) -> list[tuple[date, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    raw_csv = ""
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                raw_csv = response.read().decode("utf-8")
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
                    raw_csv = fallback.stdout
                    break
                raise
            time.sleep(attempt * 1.5)

    rows: list[tuple[date, float]] = []
    reader = csv.DictReader(raw_csv.splitlines())
    for row in reader:
        raw_date = (row.get("observation_date") or "").strip()
        raw_value = (row.get(series_id) or "").strip()
        if not raw_date or not raw_value or raw_value == ".":
            continue
        try:
            observed_at = date.fromisoformat(raw_date)
            value = float(raw_value)
        except ValueError:
            continue
        rows.append((observed_at, value))
    if not rows:
        raise ValueError(f"no usable rows fetched from FRED series {series_id}")
    return rows


def _compute_monthly_factor(rows: list[tuple[date, float]], lookback_years: int) -> dict[int, float]:
    max_year = max(day.year for day, _ in rows)
    min_year = max_year - lookback_years + 1
    filtered = [(day, value) for day, value in rows if day.year >= min_year] or rows

    month_buckets: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    for day, value in filtered:
        month_buckets[day.month].append(value)

    month_means = {
        month: (mean(values) if values else 1.0)
        for month, values in month_buckets.items()
    }
    overall = mean(month_means.values())
    if overall <= 0:
        return {month: 1.0 for month in range(1, 13)}
    return {month: month_means[month] / overall for month in range(1, 13)}


def _blended_monthly_factors(
    lookback_years: int,
) -> tuple[dict[int, float], list[dict[str, str]], list[dict[str, str]]]:
    weighted_sum = {month: 0.0 for month in range(1, 13)}
    total_weight = 0.0
    source_rows: list[dict[str, str]] = []

    for series_id, source_label, weight in FRED_SERIES:
        rows = _fetch_fred_series(series_id)
        factors = _compute_monthly_factor(rows, lookback_years)
        total_weight += weight
        for month in range(1, 13):
            weighted_sum[month] += factors[month] * weight
            source_rows.append(
                {
                    "series_id": series_id,
                    "series_source": source_label,
                    "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
                    "month": str(month),
                    "series_factor": f"{factors[month]:.8f}",
                    "series_weight": f"{weight:.4f}",
                }
            )

    blended = {month: weighted_sum[month] / total_weight for month in range(1, 13)}
    blended_mean = mean(blended.values())
    normalized = {month: blended[month] / blended_mean for month in range(1, 13)}
    blended_rows = [
        {"month": str(month), "blended_factor": f"{normalized[month]:.8f}"}
        for month in range(1, 13)
    ]
    return normalized, blended_rows, source_rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_transactions_rows(
    baseline: BaselineMonth,
    projection_start: date,
    monthly_factors: dict[int, float],
    cagr: float,
    jitter_std: float,
    take_rate: float,
    year2_3_min_txns: int,
    year2_3_max_txns: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    baseline_factor = monthly_factors[baseline.month_start.month]
    baseline_asp = baseline.gmv_usd / max(1, baseline.transaction_count)

    rows: list[dict[str, Any]] = []
    for index in range(PROJECTION_MONTHS):
        month_start = _add_months(projection_start, index)
        year_index = 1 if index < 12 else 2 if index < 24 else 3
        phase = (
            "phase_1_user_growth"
            if year_index == 1
            else "phase_2_marketplace_activation"
            if year_index == 2
            else "phase_3_projection"
        )
        seasonality_factor = monthly_factors[month_start.month]
        seasonality_ratio = seasonality_factor / baseline_factor

        if year_index == 1:
            # Assumption: pre-marketplace period focuses on user growth, so transactions are zero.
            txns = 0
            asp = 0.0
            gmv = 0.0
            cagr_multiplier = 1.0
            jitter_multiplier = max(0.70, 1 + rng.gauss(0.0, jitter_std * 0.5))
        else:
            projection_offset = index - 12
            cagr_multiplier = math.pow(1 + cagr, projection_offset / 12)
            ramp_progress = projection_offset / 23

            # Assumption: stay a fraction of Chrono24 (~500/month), capped at 400 monthly transactions.
            trend_txns = year2_3_min_txns + (year2_3_max_txns - year2_3_min_txns) * ramp_progress
            txn_seasonality = 0.85 + 0.15 * seasonality_ratio
            txn_noise = max(0.85, 1 + rng.gauss(0.0, jitter_std * 0.4))
            txns = int(round(trend_txns * txn_seasonality * txn_noise))
            txns = min(year2_3_max_txns, max(year2_3_min_txns, txns))

            asp_seasonality = 0.90 + 0.10 * seasonality_ratio
            asp_growth = math.pow(1 + (cagr * 0.35), projection_offset / 12)
            asp_noise = max(0.75, 1 + rng.gauss(0.0, jitter_std * 0.35))
            asp = baseline_asp * asp_seasonality * asp_growth * asp_noise
            gmv = txns * asp
            jitter_multiplier = txn_noise * asp_noise

        fee_revenue = gmv * take_rate if txns > 0 else 0.0
        rows.append(
            {
                "month": str(month_start),
                "year_index": year_index,
                "phase": phase,
                "seasonality_factor": round(seasonality_factor, 6),
                "cagr_multiplier": round(cagr_multiplier, 6),
                "jitter_multiplier": round(jitter_multiplier, 6),
                "transaction_count": txns,
                "gross_market_value_usd": round(gmv, 2),
                "actual_sales_price_usd": round(asp, 2),
                "take_rate": round(take_rate, 4),
                "transaction_fee_revenue_usd": round(fee_revenue, 2),
            }
        )
    return rows


def _build_audience_rows(
    transactions_rows: list[dict[str, Any]],
    monthly_factors: dict[int, float],
    mau_start: float,
    mau_end: float,
    conversion_start: float,
    conversion_end: float,
    retention_start: float,
    retention_end: float,
    jitter_std: float,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed + 101)
    rows: list[dict[str, Any]] = []
    active_subscribers_prev = 0.0

    for index, tx_row in enumerate(transactions_rows):
        month_text = str(tx_row["month"])
        month_key = date.fromisoformat(month_text)
        progress = index / max(1, len(transactions_rows) - 1)
        growth_curve = _sigmoid_progress(index, len(transactions_rows) - 1, steepness=7.5)

        mau_baseline = mau_start + (mau_end - mau_start) * growth_curve
        seasonality = 0.92 + 0.08 * monthly_factors[month_key.month]
        mau_noise = max(0.85, 1 + rng.gauss(0.0, jitter_std * 0.35))
        mau = max(100.0, mau_baseline * seasonality * mau_noise)

        conversion_rate = conversion_start + (conversion_end - conversion_start) * progress
        retention_rate = retention_start + (retention_end - retention_start) * progress

        retained = active_subscribers_prev * retention_rate
        target_subscribers = mau * conversion_rate
        active_subscribers = max(retained, target_subscribers)
        new_subscribers = max(0.0, active_subscribers - retained)
        churned_subscribers = max(0.0, active_subscribers_prev - retained)
        rows.append(
            {
                "month": month_text,
                "year_index": tx_row["year_index"],
                "phase": tx_row["phase"],
                "mau": int(round(mau)),
                "subscription_conversion_rate": round(conversion_rate, 4),
                "subscription_retention_rate": round(retention_rate, 4),
                "new_subscribers": int(round(new_subscribers)),
                "churned_subscribers": int(round(churned_subscribers)),
                "active_subscribers": int(round(active_subscribers)),
            }
        )
        active_subscribers_prev = active_subscribers
    return rows


def _build_ad_rows(
    audience_rows: list[dict[str, Any]],
    ad_action_rate: float,
    ad_cpa_usd: float,
    jitter_std: float,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed + 202)
    rows: list[dict[str, Any]] = []

    for index, audience_row in enumerate(audience_rows):
        progress = index / max(1, len(audience_rows) - 1)
        mau = float(audience_row["mau"])
        retention_rate = float(audience_row["subscription_retention_rate"])

        # Assumption: ad actions increase with MAU and are moderately boosted by retention quality.
        effective_action_rate = ad_action_rate * (0.75 + 0.5 * retention_rate) * (0.95 + 0.1 * progress)
        noise = max(0.80, 1 + rng.gauss(0.0, jitter_std * 0.3))
        ad_actions = mau * effective_action_rate * noise
        ad_revenue = ad_actions * ad_cpa_usd

        rows.append(
            {
                "month": audience_row["month"],
                "year_index": audience_row["year_index"],
                "phase": audience_row["phase"],
                "ad_action_rate": round(effective_action_rate, 5),
                "ad_actions": int(round(ad_actions)),
                "ad_cpa_usd": round(ad_cpa_usd, 2),
                "ad_revenue_usd": round(ad_revenue, 2),
            }
        )
    return rows


def _build_subscription_rows(
    audience_rows: list[dict[str, Any]],
    subscription_price_usd: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for audience_row in audience_rows:
        active_subscribers = float(audience_row["active_subscribers"])
        revenue = active_subscribers * subscription_price_usd
        rows.append(
            {
                "month": audience_row["month"],
                "year_index": audience_row["year_index"],
                "phase": audience_row["phase"],
                "subscription_price_usd": round(subscription_price_usd, 2),
                "subscription_revenue_usd": round(revenue, 2),
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    if REVENUE_ASSUMPTIONS.year2_3_min_txns < 0:
        raise ValueError("REVENUE_ASSUMPTIONS.year2_3_min_txns must be >= 0")
    if REVENUE_ASSUMPTIONS.year2_3_max_txns < REVENUE_ASSUMPTIONS.year2_3_min_txns:
        raise ValueError(
            "REVENUE_ASSUMPTIONS.year2_3_max_txns must be >= year2_3_min_txns"
        )

    input_csv = MARKETPLACE_FINANCE_DIR / DATA_PATHS.raw_marketplace_daily_sales_csv
    marketplace_fees_output = (
        MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_marketplace_fees_csv
    )
    audience_output = MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_mau_csv
    subscriptions_output = (
        MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_subscriptions_csv
    )
    ad_revenue_output = MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_ads_csv
    seasonality_output = DATA_DIR / DATA_PATHS.seasonality_factors_csv
    seasonality_source_output = DATA_DIR / DATA_PATHS.seasonality_sources_csv

    baseline = _read_daily_sales_monthly_baseline(
        input_csv,
        REVENUE_ASSUMPTIONS.baseline_month,
    )
    projection_start = date.fromisoformat(f"{REVENUE_ASSUMPTIONS.projection_start_month}-01")
    monthly_factors, blended_rows, source_rows = _blended_monthly_factors(
        lookback_years=REVENUE_ASSUMPTIONS.seasonality_lookback_years
    )

    transactions_rows = _build_transactions_rows(
        baseline=baseline,
        projection_start=projection_start,
        monthly_factors=monthly_factors,
        cagr=REVENUE_ASSUMPTIONS.sales_cagr,
        jitter_std=REVENUE_ASSUMPTIONS.jitter_std,
        take_rate=REVENUE_ASSUMPTIONS.take_rate,
        year2_3_min_txns=REVENUE_ASSUMPTIONS.year2_3_min_txns,
        year2_3_max_txns=REVENUE_ASSUMPTIONS.year2_3_max_txns,
        seed=REVENUE_ASSUMPTIONS.seed,
    )
    audience_rows = _build_audience_rows(
        transactions_rows=transactions_rows,
        monthly_factors=monthly_factors,
        mau_start=REVENUE_ASSUMPTIONS.mau_start,
        mau_end=REVENUE_ASSUMPTIONS.mau_end,
        conversion_start=REVENUE_ASSUMPTIONS.subscription_conversion_start,
        conversion_end=REVENUE_ASSUMPTIONS.subscription_conversion_end,
        retention_start=REVENUE_ASSUMPTIONS.subscription_retention_start,
        retention_end=REVENUE_ASSUMPTIONS.subscription_retention_end,
        jitter_std=REVENUE_ASSUMPTIONS.jitter_std,
        seed=REVENUE_ASSUMPTIONS.seed,
    )
    subscriptions_rows = _build_subscription_rows(
        audience_rows=audience_rows,
        subscription_price_usd=REVENUE_ASSUMPTIONS.subscription_price_usd,
    )
    ad_rows = _build_ad_rows(
        audience_rows=audience_rows,
        ad_action_rate=REVENUE_ASSUMPTIONS.ad_action_rate,
        ad_cpa_usd=REVENUE_ASSUMPTIONS.ad_cpa_usd,
        jitter_std=REVENUE_ASSUMPTIONS.jitter_std,
        seed=REVENUE_ASSUMPTIONS.seed,
    )

    _write_csv(marketplace_fees_output, transactions_rows)
    _write_csv(audience_output, audience_rows)
    _write_csv(subscriptions_output, subscriptions_rows)
    _write_csv(ad_revenue_output, ad_rows)
    _write_csv(seasonality_output, blended_rows)
    _write_csv(seasonality_source_output, source_rows)

    print(f"baseline_month={baseline.month_start.isoformat()}")
    print(f"projection_start_month={projection_start.isoformat()}")
    print(f"baseline_month_gmv_usd={baseline.gmv_usd:.2f}")
    print(f"baseline_month_transaction_count={baseline.transaction_count}")
    print(f"transactions_rows={len(transactions_rows)}")
    print(f"audience_rows={len(audience_rows)}")
    print(f"subscriptions_rows={len(subscriptions_rows)}")
    print(f"ad_rows={len(ad_rows)}")
    print(f"marketplace_fees_output={marketplace_fees_output}")
    print(f"audience_output={audience_output}")
    print(f"subscriptions_output={subscriptions_output}")
    print(f"ad_revenue_output={ad_revenue_output}")
    print(f"seasonality_output={seasonality_output}")
    print(f"seasonality_source_output={seasonality_source_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
