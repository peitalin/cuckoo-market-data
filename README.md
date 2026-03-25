# export-csv

CSV export and synthetic data generation for marketplace analysis.

## Commands

Run from this folder:

```bash
python3 main.py export
python3 main.py bundle
python3 main.py plot
```

You can edit modelling assumptions in `pipeline/assumptions.py` for different audience and revenue figures

## Outputs

Raw marketplace data from Chrono24:
- `data/raw_marketplace_transactions.csv`
- `data/raw_marketplace_daily_sales.csv`

Synthetic revenue projections based on Chrono24 data:
- `data/generated_revenues_marketplace_fees.csv`
- `data/generated_mau.csv`
- `data/generated_revenues_subscriptions.csv`
- `data/generated_revenues_ads.csv`

Assumptions for revenue projections:
- `pipeline/assumptions.py` (source of truth)
- `data/data_generation_assumptions.md` (snapshot)

Detailed CSV field definitions:
- `data/README.md`
