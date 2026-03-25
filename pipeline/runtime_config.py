from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final


def _env_first(keys: tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class DataPathConfig:
    raw_marketplace_transactions_csv: Path = Path("raw_marketplace_transactions.csv")
    raw_marketplace_daily_sales_csv: Path = Path("raw_marketplace_daily_sales.csv")
    generated_revenues_marketplace_fees_csv: Path = Path("generated_revenues_marketplace_fees.csv")
    generated_mau_csv: Path = Path("generated_mau.csv")
    generated_revenues_subscriptions_csv: Path = Path("generated_revenues_subscriptions.csv")
    generated_revenues_ads_csv: Path = Path("generated_revenues_ads.csv")
    data_generation_assumptions_md: Path = Path("data_generation_assumptions.md")
    charts_dir: Path = Path("charts")
    growth_projection_csv: Path = Path("synthetic_marketplace_growth_36m.csv")
    seasonality_factors_csv: Path = Path("reference/seasonality/luxury_watch_monthly_factors.csv")
    seasonality_sources_csv: Path = Path("reference/seasonality/luxury_watch_seasonality_sources.csv")
    fx_gbp_usd_csv: Path = Path("reference/fx/gbp_usd_daily.csv")
    traffic_reference_csv: Path = Path("reference/traffic/chrono24_semrush_visits_history.csv")
    revenue_chart_svg: str = "synthetic_revenue_projection.svg"
    transactions_chart_svg: str = "synthetic_transactions_projection.svg"
    audience_chart_svg: str = "synthetic_audience_projection.svg"
    charts_index_html: str = "index.html"


@dataclass(frozen=True)
class ExportApiConfig:
    analysis_api_base_url: str
    analysis_api_bearer_token: str
    analysis_api_timeout_seconds: float = 60.0
    analysis_api_page_size: int = 100
    sales_sources: str = "chrono24"
    min_sale_date: str = "2026-02-20T00:00:00Z"
    gbp_usd_fred_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXUSUK"
    skip_fx_fetch: bool = False


DATA_PATHS: Final[DataPathConfig] = DataPathConfig()
EXPORT_API_CONFIG: Final[ExportApiConfig] = ExportApiConfig(
    analysis_api_base_url=_env_first(
        ("ANALYSIS_API_BASE_URL", "ANALYSIS_API_BASE"),
        "https://api.cuckoo.market/v1/analysis",
    ),
    analysis_api_bearer_token=_env_first(
        ("ANALYSIS_API_BEARER_TOKEN", "VITE_ANALYSIS_BEARER_TOKEN"),
        "",
    ),
)
