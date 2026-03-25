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
    # Audience and revenue assumption notes for educational modeling transparency.
    assumptions_output = MARKETPLACE_FINANCE_DIR / DATA_PATHS.data_generation_assumptions_md
    assumption_text = dedent(
        f"""
        # Audience, Revenue, and Expense Projection Assumptions (36-Month Synthetic Model)

        This document justifies the assumptions used to generate the workbook:
        - `synthetic_marketplace_projection_model.xlsx`

        Workbook sheets:
        - `Summary` (36-month income-statement style rollup)
- `Marketplace Revenue` (marketplace fee revenue driver)
        - `MAU & Operating Metrics` (MAU rollup with embedded cohort acquisition and retention matrix)
        - `Subscriptions` (subscription revenue)
        - `Advertising` (advertising revenue)
        - `OpEx` (cloud, marketing, and G&A costs)

        ## Source of Truth

        The canonical source of truth for data-generating assumptions is:
        - `pipeline/assumptions.py`

        This markdown file is a human-readable snapshot of those assumptions at generation time.

        ## 1) Modeling Objective

        The goal is not point-forecast precision. It is to produce an educational, internally consistent revenue and expense scenario with:
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
        - Average selling price grows at `{REVENUE_ASSUMPTIONS.avg_sell_price_annual_growth:.2%}` per year on a linear inflation-style ramp.
        - GMV growth is driven by:
          - annual CAGR: `{REVENUE_ASSUMPTIONS.sales_cagr:.4f}`,
          - monthly seasonality factors (lookback `{REVENUE_ASSUMPTIONS.seasonality_lookback_years}` years),
          - small stochastic jitter (`std={REVENUE_ASSUMPTIONS.jitter_std:.4f}`).
        - Fee take-rate is fixed at `{REVENUE_ASSUMPTIONS.take_rate:.4f}`.

        Justification:
        - A low take-rate is conservative for early marketplace monetization.
        - A bounded transaction range prevents unrealistic scale-up against incumbents.
        - Modest CAGR + seasonality avoids overfitting one observed month.

        ## 4) Audience and Subscription Revenue Assumptions

        - Monthly subscription price: `${REVENUE_ASSUMPTIONS.subscription_price_usd:.2f}`.
        - The audience generator uses monthly acquisition cohorts:
          - first cohort new users: `{REVENUE_ASSUMPTIONS.new_users_start:.0f}`,
          - monthly new-user growth: `{REVENUE_ASSUMPTIONS.new_users_monthly_growth_year1:.3f}` in Year 1, `{REVENUE_ASSUMPTIONS.new_users_monthly_growth_year2:.3f}` in Year 2, `{REVENUE_ASSUMPTIONS.new_users_monthly_growth_year3:.3f}` in Year 3,
          - holiday acquisition spike: `{REVENUE_ASSUMPTIONS.new_user_holiday_spike_multiplier:.2f}x` in November and December,
          - cohort retention curve: Month 1 `{REVENUE_ASSUMPTIONS.user_retention_month_1:.2f}`, Month 2 `{REVENUE_ASSUMPTIONS.user_retention_month_2:.2f}`, Month 3 `{REVENUE_ASSUMPTIONS.user_retention_month_3:.2f}`, then decay `{REVENUE_ASSUMPTIONS.user_retention_decay:.2f}` per month.
        - Subscriber monetization then applies:
          - conversion starts at `{REVENUE_ASSUMPTIONS.subscription_conversion_start:.3f}` and closes `{REVENUE_ASSUMPTIONS.subscription_conversion_monthly_improvement_rate:.1%}` of the remaining gap to the `{REVENUE_ASSUMPTIONS.subscription_conversion_end:.3f}` target each month,
          - subscriber retention starts at `{REVENUE_ASSUMPTIONS.subscription_retention_start:.2f}` and closes `{REVENUE_ASSUMPTIONS.subscription_retention_monthly_improvement_rate:.1%}` of the remaining gap to the `{REVENUE_ASSUMPTIONS.subscription_retention_end:.2f}` target each month.
        - Active subscribers are constrained by both retained subscribers and current-period conversion.
        - Subscription revenue is derived from active subscribers and the fixed monthly price.

        Fields in workbook sheet `MAU & Operating Metrics`:
        - `month`: month bucket for the projection row.
        - `year_index`: whether the row falls in projection year 1, 2, or 3.
        - `phase`: coarse growth stage label for the scenario.
        - `new_users`: cohort acquisitions landing in the month.
        - `returning_users`: active users retained from prior cohorts.
        - `mau`: projected monthly active users for the month.
        - cohort helper columns on the right side: acquisition growth, seasonality, acquisition noise, retained-share helpers, and the full cohort contribution matrix.

        Fields in workbook sheet `Subscriptions`:
        - `month`: month bucket for the projection row.
        - `year_index`: whether the row falls in projection year 1, 2, or 3.
        - `phase`: coarse growth stage label for the scenario.
        - `mau`: projected monthly active users from the MAU & Operating Metrics sheet.
        - `subscription_conversion_rate`: modeled MAU-to-paid conversion rate.
        - `subscription_retention_rate`: modeled monthly subscriber retention rate.
        - `retained_subscribers`: subscribers retained from the prior month.
        - `new_subscribers`: subscribers added after conversion in the month.
        - `churned_subscribers`: subscribers lost from the prior month.
        - `active_subscribers`: ending active subscriber count for the month.

        Justification:
        - Pricing is accessible for analytics users while still monetizing high-intent cohorts.
        - A cohort model makes MAU retention explicit instead of hiding it in a top-down curve.
        - Gap-closing improvement rates represent product maturity without tying the rate path to the arbitrary projection length.

        ## 5) Ad Revenue Assumptions (CPA Model)

        - Sessions per MAU: `{REVENUE_ASSUMPTIONS.sessions_per_mau:.2f}`.
        - Pageviews per session: `{REVENUE_ASSUMPTIONS.pageviews_per_session:.2f}`.
        - CPA action rate per pageview: `{REVENUE_ASSUMPTIONS.ad_action_rate_per_pageview:.4f}`.
        - CPA payout per action: `${REVENUE_ASSUMPTIONS.ad_cpa_usd:.2f}`.

        Justification:
        - CPA is straightforward for educational modeling.
        - A session and pageview build makes ad revenue easier to diligence from MAU than a hidden maturity multiplier.

        ## 6) Expense Assumptions

        - Cloud and infrastructure costs are modeled from `MAU & Operating Metrics.mau`, `MAU & Operating Metrics.new_users`, and `Advertising.pageviews` instead of as flat hand-entered totals.
        - R2 storage scales from `{REVENUE_ASSUMPTIONS.r2_storage_start_gb:.0f}` GB to `{REVENUE_ASSUMPTIONS.r2_storage_target_end_gb:.0f}` GB over the full model horizon based on cumulative new users.
        - Managed Postgres is simplified to one primary instance plus an optional read-only replica that only activates above `{REVENUE_ASSUMPTIONS.postgres_read_replica_mau_threshold}` MAU.
        - Cloudflare costs are modeled as a single hosting plus Workers bucket, with Workers scaling from backend requests and CPU time implied by pageviews and new-user onboarding requests.
        - Transactional email cost is simplified to a flat `${REVENUE_ASSUMPTIONS.transactional_email_monthly_usd:.2f}` monthly SaaS fee.
        - Sales and marketing are modeled as explicit holiday-flight budgets by channel, active only in November and December, not as opaque CAC math.
        - G&A is intentionally simplified in the PE style: no payroll line, just team size for software-seat sizing plus one-time incorporation cost.

        Justification:
        - A PE-style model usually keeps high-signal, controllable cost buckets and avoids false precision on immaterial line items.
        - Payroll belongs in a fuller operating model, but if the goal is a quick market model, cloud + paid marketing + light G&A is easier to diligence.

        Current simplified G&A assumptions:
        - team size: `{REVENUE_ASSUMPTIONS.team_size_year1}` in Year 1, `{REVENUE_ASSUMPTIONS.team_size_year2}` in Year 2, `{REVENUE_ASSUMPTIONS.team_size_year3}` in Year 3
        - software tools per team member: `${REVENUE_ASSUMPTIONS.software_tools_per_team_member_monthly_usd:.2f}` / month
        - incorporation setup: `${REVENUE_ASSUMPTIONS.incorporation_setup_usd:.2f}` one-time

        ## 7) Seasonality Assumptions

        Seasonality is sourced from FRED monthly retail series:
        - https://fred.stlouisfed.org/series/MRTSSM44831USN
        - https://fred.stlouisfed.org/series/RSXFS

        ## 8) Conservatism and Reproducibility

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

    print(f"workbook_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.projection_workbook_xlsx}")
    print(f"seasonality_output={DATA_DIR / DATA_PATHS.seasonality_factors_csv}")
    print(f"seasonality_source_output={DATA_DIR / DATA_PATHS.seasonality_sources_csv}")
    print(f"assumptions_output={MARKETPLACE_FINANCE_DIR / DATA_PATHS.data_generation_assumptions_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
