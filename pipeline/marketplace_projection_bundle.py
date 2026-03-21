from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Sequence

try:
    from .assumptions import REVENUE_ASSUMPTIONS
    from .marketplace_projection_revenues import main as generate_revenue_projection
    from .runtime_config import DATA_PATHS
except ImportError:
    from pipeline.assumptions import REVENUE_ASSUMPTIONS
    from pipeline.marketplace_projection_revenues import main as generate_revenue_projection
    from pipeline.runtime_config import DATA_PATHS

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"
MARKETPLACE_FINANCE_DIR = DATA_DIR


def _write_assumptions_summary() -> None:
    # Revenue-focused assumption notes for educational modeling transparency.
    assumptions_output = MARKETPLACE_FINANCE_DIR / DATA_PATHS.data_generation_assumptions_md
    assumption_text = dedent(
        f"""
        # Revenue Projection Assumptions (36-Month Synthetic Model)

        This document justifies the assumptions used to generate projected revenue in:
        - `revenues_marketplace_fees` (marketplace fee revenue driver)
        - `revenues_subscriptions` (subscription revenue)
        - `revenues_ads` (advertising revenue)

        ## Source of Truth

        The canonical source of truth for data-generating assumptions is:
        - `export-csv/pipeline/assumptions.py`

        This markdown file is a human-readable snapshot of those assumptions at generation time.

        ## 1) Modeling Objective

        The goal is not point-forecast precision. It is to produce an educational, internally consistent revenue scenario with:
        - realistic seasonality,
        - conservative but positive medium-term growth,
        - and explicit levers that can be tuned for sensitivity analysis.

        ## 2) Revenue Identity

        Monthly total revenue is modeled as:

        `Total Revenue = Transaction Fee Revenue + Subscription Revenue + Ad Revenue`

        Each stream is modeled independently, then combined.

        ## 3) Transaction Fee Revenue Assumptions

        - Baseline month is anchored to observed marketplace data (`raw_marketplace_daily_sales.csv`), currently the latest observed month.
        - Year 1 transaction volume is set to `0` (pre-marketplace activation phase).
        - Year 2-3 transaction count is constrained to `{REVENUE_ASSUMPTIONS.year2_3_min_txns}` to `{REVENUE_ASSUMPTIONS.year2_3_max_txns}` per month.
        - GMV growth is driven by:
          - annual CAGR: `{REVENUE_ASSUMPTIONS.sales_cagr:.4f}`,
          - monthly seasonality factors (lookback `{REVENUE_ASSUMPTIONS.seasonality_lookback_years}` years),
          - small stochastic jitter (`std={REVENUE_ASSUMPTIONS.jitter_std:.4f}`).
        - Fee take-rate is fixed at `{REVENUE_ASSUMPTIONS.take_rate:.4f}`.

        Justification:
        - A low take-rate is conservative for early marketplace monetization.
        - A bounded transaction range prevents unrealistic scale-up against incumbents.
        - Modest CAGR + seasonality avoids overfitting one observed month.

        ## 4) Subscription Revenue Assumptions

        - Monthly subscription price: `${REVENUE_ASSUMPTIONS.subscription_price_usd:.2f}`.
        - The revenue generator uses a sigmoid MAU path and applies:
          - MAU range: `{REVENUE_ASSUMPTIONS.mau_start:.0f}` -> `{REVENUE_ASSUMPTIONS.mau_end:.0f}`,
          - conversion ramp: `{REVENUE_ASSUMPTIONS.subscription_conversion_start:.3f}` -> `{REVENUE_ASSUMPTIONS.subscription_conversion_end:.3f}`,
          - monthly retention ramp: `{REVENUE_ASSUMPTIONS.subscription_retention_start:.2f}` -> `{REVENUE_ASSUMPTIONS.subscription_retention_end:.2f}`.
        - Active subscribers are constrained by both retained subscribers and current-period conversion.

        Justification:
        - Pricing is accessible for analytics users while still monetizing high-intent cohorts.
        - Conversion/retention ramps represent product maturity over time.

        ## 5) Ad Revenue Assumptions (CPA Model)

        - Baseline ad action rate: `{REVENUE_ASSUMPTIONS.ad_action_rate:.3f}` per MAU (adjusted by retention and maturity).
        - CPA payout per action: `${REVENUE_ASSUMPTIONS.ad_cpa_usd:.2f}`.

        Justification:
        - CPA is straightforward for educational modeling.
        - Retention-adjusted ad actions reflect quality-adjusted audience monetization.

        ## 6) Seasonality Assumptions

        Seasonality is sourced from FRED monthly retail series:
        - https://fred.stlouisfed.org/series/MRTSSM44831USN
        - https://fred.stlouisfed.org/series/RSXFS

        ## 7) Conservatism and Reproducibility

        - Random seed: `{REVENUE_ASSUMPTIONS.seed}`
        """
    ).strip()
    assumptions_output.parent.mkdir(parents=True, exist_ok=True)
    assumptions_output.write_text(f"{assumption_text}\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    sales_exit = generate_revenue_projection(None)
    if sales_exit != 0:
        return int(sales_exit)

    _write_assumptions_summary()

    print(f"marketplace_fees_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_marketplace_fees_csv}")
    print(f"subscriptions_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_subscriptions_csv}")
    print(f"ad_revenue_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.generated_revenues_ads_csv}")
    print(f"seasonality_output={DATA_DIR / DATA_PATHS.seasonality_factors_csv}")
    print(f"seasonality_source_output={DATA_DIR / DATA_PATHS.seasonality_sources_csv}")
    print(f"assumptions_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.data_generation_assumptions_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
