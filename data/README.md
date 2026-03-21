# Marketplace Finance CSVs

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

## generated_revenues_marketplace_fees.csv

Synthetic 36-month marketplace-fee revenue projection.

Columns:
- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `seasonality_factor`: Applied monthly seasonality multiplier.
- `cagr_multiplier`: Applied CAGR multiplier.
- `jitter_multiplier`: Applied random jitter multiplier.
- `transaction_count`: Projected monthly transactions.
- `gross_market_value_usd`: Projected monthly GMV in USD.
- `actual_sales_price_usd`: Projected average sale price in USD.
- `take_rate`: Marketplace fee take rate.
- `transaction_fee_revenue_usd`: Projected monthly marketplace-fee revenue in USD.

## generated_revenues_subscriptions.csv

Synthetic 36-month subscription revenue projection.

Columns:
- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `mau`: Projected monthly active users.
- `subscription_conversion_rate`: MAU-to-paid conversion rate.
- `subscription_retention_rate`: Monthly retention rate for subscribers.
- `new_subscribers`: New subscribers in month.
- `churned_subscribers`: Subscribers churned in month.
- `active_subscribers`: Active subscribers in month.
- `subscription_price_usd`: Subscription price assumption (USD).
- `subscription_revenue_usd`: Projected monthly subscription revenue (USD).

## generated_revenues_ads.csv

Synthetic 36-month ad revenue projection.

Columns:
- `month`: Month bucket (`YYYY-MM-01`).
- `year_index`: Projection year bucket (`1`, `2`, `3`).
- `phase`: Growth phase label.
- `mau`: Projected monthly active users.
- `ad_action_rate`: Effective ad-action rate per MAU.
- `ad_actions`: Projected monthly ad actions.
- `ad_cpa_usd`: CPA payout assumption (USD per action).
- `ad_revenue_usd`: Projected monthly ad revenue (USD).
