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
        - Year 2-3 transaction count is constrained to `10` to `400` per month.
        - Average selling price grows at `3.00%` per year on a linear inflation-style ramp.
        - GMV growth is driven by:
          - annual CAGR: `0.0300`,
          - monthly seasonality factors (lookback `10` years),
          - small stochastic jitter (`std=0.0500`).
        - Fee take-rate is fixed at `0.0200`.

        Justification:
        - A low take-rate is conservative for early marketplace monetization.
        - A bounded transaction range prevents unrealistic scale-up against incumbents.
        - Modest CAGR + seasonality avoids overfitting one observed month.

        ## 4) Audience and Subscription Revenue Assumptions

        - Monthly subscription price: `$20.00`.
        - The audience generator uses monthly acquisition cohorts:
          - first cohort new users: `700`,
          - monthly new-user growth: `0.100` in Year 1, `0.050` in Year 2, `0.030` in Year 3,
          - holiday acquisition spike: `1.30x` in November and December,
          - cohort retention curve: Month 1 `0.25`, Month 2 `0.12`, Month 3 `0.05`, then decay `0.97` per month.
        - Subscriber monetization then applies:
          - conversion starts at `0.008` and closes `8.0%` of the remaining gap to the `0.025` target each month,
          - subscriber retention starts at `0.30` and closes `6.0%` of the remaining gap to the `0.60` target each month.
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

        - Sessions per MAU: `3.00`.
        - Pageviews per session: `5.00`.
        - CPA action rate per pageview: `0.0030`.
        - CPA payout per action: `$3.00`.

        Justification:
        - CPA is straightforward for educational modeling.
        - A session and pageview build makes ad revenue easier to diligence from MAU than a hidden maturity multiplier.

        ## 6) Expense Assumptions

        - Cloud and infrastructure costs are modeled from `MAU & Operating Metrics.mau`, `MAU & Operating Metrics.new_users`, and `Advertising.pageviews` instead of as flat hand-entered totals.
        - R2 storage scales from `100` GB to `5000` GB over the full model horizon based on cumulative new users.
        - Managed Postgres is simplified to one primary instance plus an optional read-only replica that only activates above `150000` MAU.
        - Cloudflare costs are modeled as a single hosting plus Workers bucket, with Workers scaling from backend requests and CPU time implied by pageviews and new-user onboarding requests.
        - Transactional email cost is simplified to a flat `$30.00` monthly SaaS fee.
        - Sales and marketing are modeled as explicit holiday-flight budgets by channel, active only in November and December, not as opaque CAC math.
        - G&A is intentionally simplified in the PE style: no payroll line, just team size for software-seat sizing plus one-time incorporation cost.

        Justification:
        - A PE-style model usually keeps high-signal, controllable cost buckets and avoids false precision on immaterial line items.
        - Payroll belongs in a fuller operating model, but if the goal is a quick market model, cloud + paid marketing + light G&A is easier to diligence.

        Current simplified G&A assumptions:
        - team size: `2` in Year 1, `2` in Year 2, `3` in Year 3
        - software tools per team member: `$15.75` / month
        - incorporation setup: `$500.00` one-time

        ## 7) Seasonality Assumptions

        Seasonality is sourced from FRED monthly retail series:
        - https://fred.stlouisfed.org/series/MRTSSM44831USN
        - https://fred.stlouisfed.org/series/RSXFS

        ## 8) Conservatism and Reproducibility

        - Random seed: `42`
