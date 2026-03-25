# Marketplace Finance Outputs

Source of truth for modeling assumptions:
- [data_generation_assumptions.md](./data_generation_assumptions.md)

## raw_marketplace_transactions.csv

One row per sold listing event from the raw export.

Columns:
- `date`: Daily sale bucket (`native_sale_at` when present, otherwise `sold_at`).
- `sold_at`: Sale timestamp used for the row.
- `source`: Marketplace/source name.
- `listing_id`: Source-native listing identifier.
- `seller_id`: Normalized seller identifier.
- `seller_type`: Normalized seller classification.
- `sale_mechanism`: Sale format (`listing`, `auction`, etc.).
- `brand`: Best-available brand.
- `model`: Best-available model.
- `reference`: Best-available reference number.
- `condition`: Best-available condition text.
- `currency`: Currency of `sale_price`.
- `sale_price`: Blended sale value (explicit transaction price when available, else final ask-price proxy).
- `days_to_sell`: Days from first observed listing to sold timestamp (when eligible).
- `sell_speed_eligible`: Whether row is valid for sell-speed analysis.
- `sold_inference`: Sold-state classification/inference label.

## raw_marketplace_daily_sales.csv

Daily aggregation of `raw_marketplace_transactions.csv`.

Columns:
- `date`: Daily bucket.
- `source`: Marketplace/source name.
- `currency`: Currency bucket.
- `sale_mechanism`: Sale mechanism bucket.
- `seller_type`: Seller classification bucket.
- `sold_count`: Number of sold listing rows in the bucket.
- `transaction_count`: Number of rows with populated `sale_price`.
- `transaction_gross_market_value`: Daily dollar transactions/sales seen on the platform (sum of `sale_price` in the bucket).
- `distinct_seller_count`: Distinct seller count in the bucket.

## synthetic_marketplace_projection_model.xlsx

Single workbook that contains the projection inputs, deterministic random drivers, and formula-driven output sheets.

Sheets:
- `MarketplaceFees`: 36-month marketplace fee projection with month-level seasonality factors and marketplace noise columns written directly into the sheet.
- `MAU`: 36-month audience rollup with cohort acquisition inputs, retention helpers, and the calendar-month contribution matrix on the same sheet.
- `Subscriptions`: 36-month subscription revenue projection derived from the `MAU` sheet.
- `Ads`: 36-month ad revenue projection derived from the `MAU` sheet, with local ad-noise formulas.

Workbook output columns:

### MarketplaceFees

- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `seasonality_factor`: Applied monthly seasonality multiplier.
- `noise_market_year1_jitter`: Year-1 marketplace randomness term.
- `noise_market_txn`: Transaction-count randomness term for Years 2-3.
- `noise_market_avg_sell_price`: Average-sale-price randomness term for Years 2-3.
- `cagr_multiplier`: Applied CAGR multiplier.
- `noise_market_combined`: Combined marketplace noise term applied across the projected transaction and price path.
- `transaction_count`: Projected monthly transactions.
- `avg_sell_price_growth`: Inflation-style growth multiplier applied to average sale price.
- `gross_market_value_usd`: Projected monthly GMV in USD.
- `avg_sell_price_usd`: Projected average sale price in USD.
- `take_rate`: Marketplace fee take rate.
- `transaction_fee_revenue_usd`: Projected monthly marketplace-fee revenue in USD.

### MAU

- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `new_users`: New users acquired in the month from the cohort inputs on the same row.
- `returning_users`: Active users carried over from prior cohorts.
- `mau`: Projected monthly active users.
- blank spacer column: Visual separator before the cohort helper section.
- `acquisition_growth_rate`: Monthly acquisition growth rate applied in the row's projection year.
- `base_new_users`: New-user volume before seasonality, holiday spike, and noise adjustments.
- `seasonality_factor`: Applied new-user seasonality multiplier, including the holiday spike in November and December.
- `noise_acquisition`: Random acquisition multiplier generated directly on the sheet.
- blank spacer column: Visual separator before the retention helper section.
- `user_retention_age`: Cohort age in months used for the helper retention curve lookup.
- `user_retained_share`: Share of a cohort still active at `user_retention_age`.
- Monthly contribution columns (`YYYY-MM-01` headers): Active users from the cohort that remain active in each calendar month.

### Subscriptions

- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `mau`: Projected monthly active users from the `MAU` sheet.
- `subscription_conversion_rate`: MAU-to-paid conversion rate.
- `subscription_retention_rate`: Monthly retention rate for subscribers.
- `retained_subscribers`: Paid subscribers retained from the prior month.
- `new_subscribers`: New subscribers in month.
- `churned_subscribers`: Subscribers churned in month.
- `active_subscribers`: Active subscribers in month.
- `subscription_price_usd`: Subscription price assumption (USD).
- `subscription_revenue_usd`: Projected monthly subscription revenue (USD).

### Ads

- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `sessions_per_mau`: Session assumption applied to each monthly active user.
- `pageviews_per_session`: Pageview assumption applied to each session.
- `sessions`: Projected monthly sessions derived from MAU.
- `pageviews`: Projected monthly pageviews derived from sessions.
- `ad_action_rate_per_pageview`: CPA-qualified action rate per pageview.
- `noise_ad`: Random ad-action multiplier generated directly on the sheet.
- `ad_actions`: Projected monthly ad actions.
- `ad_cpa_usd`: CPA payout assumption (USD per action).
- `ad_revenue_usd`: Projected monthly ad revenue (USD).
