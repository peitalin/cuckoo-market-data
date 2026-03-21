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
- Year 2-3 transaction count is constrained to `10` to `400` per month.
- GMV growth is driven by:
  - annual CAGR: `0.0300`,
  - monthly seasonality factors (lookback `10` years),
  - small stochastic jitter (`std=0.0500`).
- Fee take-rate is fixed at `0.0200`.

Justification:
- A low take-rate is conservative for early marketplace monetization.
- A bounded transaction range prevents unrealistic scale-up against incumbents.
- Modest CAGR + seasonality avoids overfitting one observed month.

## 4) Subscription Revenue Assumptions

- Monthly subscription price: `$20.00`.
- The revenue generator uses a sigmoid MAU path and applies:
  - MAU range: `800` -> `40000`,
  - conversion ramp: `0.008` -> `0.025`,
  - monthly retention ramp: `0.75` -> `0.90`.
- Active subscribers are constrained by both retained subscribers and current-period conversion.

Justification:
- Pricing is accessible for analytics users while still monetizing high-intent cohorts.
- Conversion/retention ramps represent product maturity over time.

## 5) Ad Revenue Assumptions (CPA Model)

- Baseline ad action rate: `0.015` per MAU (adjusted by retention and maturity).
- CPA payout per action: `$3.00`.

Justification:
- CPA is straightforward for educational modeling.
- Retention-adjusted ad actions reflect quality-adjusted audience monetization.

## 6) Seasonality Assumptions

Seasonality is sourced from FRED monthly retail series:
- https://fred.stlouisfed.org/series/MRTSSM44831USN
- https://fred.stlouisfed.org/series/RSXFS

## 7) Conservatism and Reproducibility

- Random seed: `42`
