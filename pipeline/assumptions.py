from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class RevenueProjectionAssumptions:
    # Number of monthly rows to generate for synthetic projections.
    projection_months: int = 36
    # Optional YYYY-MM override for baseline month from observed daily sales.
    # If None, the latest month in observed data is used.
    baseline_month: str | None = None
    # Calendar month to start synthetic output (YYYY-MM).
    projection_start_month: str = "2026-03"
    # Number of historical years used when computing monthly seasonality factors.
    seasonality_lookback_years: int = 10
    # Annual CAGR applied to marketplace sales trajectory (Year 2-3).
    sales_cagr: float = 0.03
    # Standard deviation for monthly random noise in synthetic generation.
    jitter_std: float = 0.05
    # Marketplace fee rate applied to GMV.
    take_rate: float = 0.02
    # Lower bound for monthly transaction count in Year 2-3.
    year2_3_min_txns: int = 10
    # Upper bound for monthly transaction count in Year 2-3.
    year2_3_max_txns: int = 400
    # Monthly USD price for paid subscriptions.
    subscription_price_usd: float = 20.0
    # Starting MAU level used in subscription/ad revenue modeling.
    mau_start: float = 800.0
    # Ending MAU level used in subscription/ad revenue modeling.
    mau_end: float = 40000.0
    # Initial MAU->paid conversion rate.
    subscription_conversion_start: float = 0.008
    # Final MAU->paid conversion rate at end of projection.
    subscription_conversion_end: float = 0.025
    # Initial monthly paid-subscriber retention rate.
    subscription_retention_start: float = 0.75
    # Final monthly paid-subscriber retention rate.
    subscription_retention_end: float = 0.90
    # Baseline ad-action rate per MAU for CPA monetization.
    ad_action_rate: float = 0.015
    # USD payout per ad action.
    ad_cpa_usd: float = 3.0
    # Random seed for deterministic synthetic output.
    seed: int = 42


@dataclass(frozen=True)
class MauProjectionAssumptions:
    # External reference URL for Chrono24 monthly traffic series.
    semrush_chrono24_url: str = "https://www.semrush.com/website/chrono24.com/overview/"
    # Year-1 target MAU trajectory (12 monthly anchor points).
    year1_mau_trajectory: tuple[int, ...] = (
        300,
        800,
        1500,
        2200,
        3500,
        5000,
        7500,
        10000,
        13000,
        17000,
        22000,
        28000,
    )
    # Scalar applied to the Year-1 MAU trajectory for conservative/aggressive cases.
    year1_mau_scale: float = 0.80
    # Annual CAGR used for benchmark traffic extrapolation.
    benchmark_traffic_cagr: float = 0.02
    # MAU threshold to activate marketplace fee switch in growth model.
    fee_switch_mau_threshold: float = 12000.0
    # 3-month retention threshold to activate marketplace fee switch.
    fee_switch_retention_threshold: float = 0.38


# Primary editable assumption objects used by projection scripts.
REVENUE_ASSUMPTIONS: Final[RevenueProjectionAssumptions] = RevenueProjectionAssumptions()
MAU_ASSUMPTIONS: Final[MauProjectionAssumptions] = MauProjectionAssumptions()

# Convenience aliases.
PROJECTION_MONTHS: Final[int] = REVENUE_ASSUMPTIONS.projection_months
DEFAULT_RANDOM_SEED: Final[int] = REVENUE_ASSUMPTIONS.seed
