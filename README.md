# export-csv

Synthetic data generation for marketplace analysis.

## Commands

Run from this folder:

```bash
python3 main.py export
python3 main.py bundle
python3 main.py plot
```

You can edit modelling assumptions in `pipeline/assumptions.py` for different audience, revenue, and expense figures

## Outputs

Raw marketplace data from Chrono24:
- `data/raw_marketplace_transactions.csv`
- `data/raw_marketplace_daily_sales.csv`

Synthetic projection workbook based on Chrono24 data:
- `data/synthetic_marketplace_projection_model.xlsx`

Assumptions for revenue projections:
- `pipeline/assumptions.py` (source of truth)
- `data/data_generation_assumptions.md` (snapshot)

Workbook sheet definitions:
- `data/README.md`
