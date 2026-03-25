# Audience and Revenue Projection Assumptions (36-Month Synthetic Model)

This document justifies the assumptions used to generate projected audience and revenue in:
- `generated_mau.csv` (MAU and subscriber state)
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

Marketplace fees formula:
- Year 1 (`t < 12`):
  - `txns=0`, `asp=0`, `gmv=0`, `fee=0`
- Years 2-3 (`t >= 12`):
  - `gmv_t = txns_t * asp_t`, `fee_t = gmv_t * take_rate`

Where:
- `gmv_t`: projected gross merchandise value in month t (total dollar value sold), computed as gmv_t = txns_t * asp_t.
- `txns_t`: projected number of marketplace transactions in month t.
- `asp_t`: projected average sale price in month t (USD per transaction).

See:
```
txns_t = min(max_txns, max(min_txns, round(base_txns_t * txn_seasonality_t * txn_noise_t)))
base_txns_t = min_txns + (max_txns - min_txns) * ((t - 12) / 23)
txn_seasonality_t = 0.85 + 0.15 * R_t
asp_t = baseline_asp * asp_seasonality_t * asp_growth_t * asp_noise_t
asp_seasonality_t = 0.90 + 0.10 * R_t, asp_growth_t = (1 + 0.35 * cagr)^((t - 12) / 12)
txn_noise_t and asp_noise_t are bounded random multipliers.

Where:
- R_t = seasonality_factor_t / seasonality_factor_baseline.
```



## 4) Subscription Revenue Assumptions

- Monthly subscription price: `$20.00`.
- The audience generator uses a sigmoid MAU path and applies:
  - MAU range: `800` -> `40000`,
  - conversion ramp: `0.008` -> `0.025`,
  - monthly retention ramp: `0.75` -> `0.90`.
- Active subscribers are constrained by both retained subscribers and current-period conversion.
- Subscription revenue is derived from active subscribers and the fixed monthly price.

Fields in `generated_mau.csv`:
- `month`: month bucket for the projection row.
- `year_index`: whether the row falls in projection year 1, 2, or 3.
- `phase`: coarse growth stage label for the scenario.
- `mau`: projected monthly active users for the month.
- `subscription_conversion_rate`: modeled MAU-to-paid conversion rate.
- `subscription_retention_rate`: modeled monthly subscriber retention rate.
- `new_subscribers`: subscribers added after conversion in the month.
- `churned_subscribers`: subscribers lost from the prior month.
- `active_subscribers`: ending active subscriber count for the month.

Subscriptions Revenue Formula:
- `retained_t = active_(t-1) * retention_t`
- `target_t = mau_t * conversion_t`
- `active_t = max(retained_t, target_t)`
- `subscription_revenue_t = active_t * subscription_price_usd`

## 5) Ad Revenue Assumptions (CPA Model)

- Baseline ad action rate: `0.015` per MAU (adjusted by retention and maturity).
- CPA payout per action: `$3.00`.

Ads:
- `effective_rate_t = ad_action_rate * (0.75 + 0.5*retention_t) * (0.95 + 0.1*progress_t)`
- `ad_actions_t = mau_t * effective_rate_t * ad_noise_t`
- `ad_revenue_t = ad_actions_t * ad_cpa_usd`

## 6) Seasonality Assumptions

Seasonality is sourced from FRED monthly retail series:
- https://fred.stlouisfed.org/series/MRTSSM44831USN
- https://fred.stlouisfed.org/series/RSXFS

