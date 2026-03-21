# export-csv

CSV export and synthetic data generation for marketplace analysis.

## Commands

Run from this folder:

```bash
cd export-csv
python3 main.py export
python3 main.py bundle
python3 main.py plot
```

## Outputs

Raw export:
- `data/raw_marketplace_transactions.csv`
- `data/raw_marketplace_daily_sales.csv`

Synthetic revenue projections:
- `data/generated_revenues_marketplace_fees.csv`
- `data/generated_revenues_subscriptions.csv`
- `data/generated_revenues_ads.csv`

Assumptions:
- `pipeline/assumptions.py` (source of truth)
- `data/data_generation_assumptions.md` (snapshot)

Detailed CSV field definitions:
- `data/README.md`
