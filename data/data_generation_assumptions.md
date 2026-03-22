# Revenue Projection Assumptions (36-Month Synthetic Model)

This document outlines assumptions used in:
- `revenues_marketplace_fees` (marketplace fee revenue driver)
- `revenues_subscriptions` (subscription revenue)
- `revenues_ads` (advertising revenue)

Assumptions are configured in: `export-csv/pipeline/assumptions.py`

Monthly total revenue is modeled as:

`Total Revenue = Transaction Fee Revenue + Subscription Revenue + Ad Revenue`

Each stream is modeled independently, then combined.

## 1) Transaction Fee Revenue Assumptions

- Baseline month is anchored to observed marketplace data (`raw_marketplace_daily_sales.csv`), currently the latest observed month.
- Year 1 transaction volume is set to `0` (pre-marketplace activation phase).
- Year 2-3 transaction count is constrained to `10` to `400` per month (conservatively scaled to mirror Chrono24 observations).
- GMV growth assumptions: growth is driven by:
  - annual CAGR: `0.0300`,
  - monthly seasonality factors (lookback `10` years),
  - small stochastic jitter (`std=0.0500`).
- Fee take-rate is fixed at `0.0200`.

Justification:
- A zero take-rate is needed for bootstrapping early marketplace adoption.
- Fee switch is turn on after hitting critical threshold MAUs.
- Modest CAGR + seasonality avoids overfitting one observed month.

## 2) Subscription Revenue Assumptions

- Monthly subscription price: `$20.00`.
- The revenue generator is based on MAUs and applies:
  - MAU range: `800` -> `40000`,
  - conversion ramp: `0.008` -> `0.025`,
  - monthly retention ramp: `0.75` -> `0.90`.
- Active subscribers are constrained by both retained subscribers and current-period conversion.

Justification:
- Pricing is accessible for analytics users while still monetizing high-intent cohorts.
- Conversion/retention ramps represent product maturity over time.

## 3) Ad Revenue Assumptions (CPA Model)

- Baseline ad action rate: `0.015` per MAU (adjusted by retention and maturity).
- CPA payout per action: `$3.00`.

Justification:
- CPA is straightforward for educational modeling.
- Retention-adjusted ad actions reflect quality-adjusted audience monetization.

## 4) Seasonality Assumptions

Seasonality is sourced from FRED monthly retail series:
- https://fred.stlouisfed.org/series/MRTSSM44831USN
- https://fred.stlouisfed.org/series/RSXFS

