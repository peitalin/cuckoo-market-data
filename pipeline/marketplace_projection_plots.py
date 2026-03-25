from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Sequence

try:
    from .projection_workbook import read_projection_sheet_rows
    from .projection_workbook import SHEET_ADS
    from .projection_workbook import SHEET_MARKETPLACE_FEES
    from .projection_workbook import SHEET_MAU
    from .projection_workbook import SHEET_SUBSCRIPTIONS
    from .runtime_config import DATA_PATHS
except ImportError:
    from projection_workbook import read_projection_sheet_rows
    from projection_workbook import SHEET_ADS
    from projection_workbook import SHEET_MARKETPLACE_FEES
    from projection_workbook import SHEET_MAU
    from projection_workbook import SHEET_SUBSCRIPTIONS
    from runtime_config import DATA_PATHS

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"
MARKETPLACE_FINANCE_DIR = DATA_DIR


@dataclass(frozen=True)
class Series:
    name: str
    color: str
    values: list[float]


def _line_path(
    values: list[float],
    plot_x: float,
    plot_y: float,
    plot_w: float,
    plot_h: float,
    y_max: float,
) -> str:
    if len(values) == 1:
        x = plot_x
        y = plot_y + plot_h - (values[0] / y_max) * plot_h
        return f"M {x:.2f} {y:.2f}"

    parts: list[str] = []
    for idx, value in enumerate(values):
        x = plot_x + (idx / (len(values) - 1)) * plot_w
        y = plot_y + plot_h - (value / y_max) * plot_h
        command = "M" if idx == 0 else "L"
        parts.append(f"{command} {x:.2f} {y:.2f}")
    return " ".join(parts)


def _format_usd(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def _format_count(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def _render_line_chart_svg(
    *,
    title: str,
    subtitle: str,
    y_label: str,
    y_formatter: str,
    months: list[str],
    series: list[Series],
    output_path: Path,
) -> None:
    width = 1280
    height = 720
    margin_left = 110
    margin_right = 40
    margin_top = 100
    margin_bottom = 120
    plot_x = margin_left
    plot_y = margin_top
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    max_value = max(max(item.values) for item in series)
    y_max = max(max_value * 1.1, 1.0)

    if y_formatter == "usd":
        y_tick_formatter = _format_usd
    else:
        y_tick_formatter = _format_count

    y_tick_lines: list[str] = []
    y_tick_count = 6
    for i in range(y_tick_count + 1):
        tick_value = (i / y_tick_count) * y_max
        y = plot_y + plot_h - (i / y_tick_count) * plot_h
        label = y_tick_formatter(tick_value)
        y_tick_lines.append(
            (
                f'<line x1="{plot_x:.2f}" y1="{y:.2f}" x2="{plot_x + plot_w:.2f}" y2="{y:.2f}" '
                'stroke="#E5E7EB" stroke-width="1" />'
            )
        )
        y_tick_lines.append(
            f'<text x="{plot_x - 14:.2f}" y="{y + 5:.2f}" text-anchor="end" '
            'font-size="14" fill="#6B7280">{}</text>'.format(escape(label))
        )

    x_tick_lines: list[str] = []
    tick_step = 3
    for idx, month in enumerate(months):
        if idx % tick_step != 0 and idx != len(months) - 1:
            continue
        x = plot_x + (idx / (len(months) - 1)) * plot_w
        x_tick_lines.append(
            f'<line x1="{x:.2f}" y1="{plot_y + plot_h:.2f}" x2="{x:.2f}" y2="{plot_y + plot_h + 8:.2f}" '
            'stroke="#9CA3AF" stroke-width="1" />'
        )
        x_tick_lines.append(
            f'<text x="{x:.2f}" y="{plot_y + plot_h + 30:.2f}" text-anchor="middle" '
            'font-size="13" fill="#6B7280">{}</text>'.format(escape(month[:7]))
        )

    line_paths: list[str] = []
    legend_items: list[str] = []
    legend_x = plot_x
    legend_y = 60
    for idx, item in enumerate(series):
        path = _line_path(item.values, plot_x, plot_y, plot_w, plot_h, y_max)
        line_paths.append(
            f'<path d="{path}" fill="none" stroke="{item.color}" stroke-width="3" '
            'stroke-linecap="round" stroke-linejoin="round" />'
        )
        item_x = legend_x + idx * 300
        legend_items.append(
            f'<line x1="{item_x:.2f}" y1="{legend_y:.2f}" x2="{item_x + 28:.2f}" y2="{legend_y:.2f}" '
            f'stroke="{item.color}" stroke-width="4" />'
        )
        legend_items.append(
            f'<text x="{item_x + 36:.2f}" y="{legend_y + 5:.2f}" font-size="15" fill="#111827">{escape(item.name)}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#FFFFFF" />
  <text x="{plot_x}" y="36" font-size="30" font-weight="700" fill="#111827">{escape(title)}</text>
  <text x="{plot_x}" y="88" font-size="16" fill="#4B5563">{escape(subtitle)}</text>
  <text x="32" y="{plot_y - 18}" font-size="14" fill="#6B7280">{escape(y_label)}</text>
  <rect x="{plot_x:.2f}" y="{plot_y:.2f}" width="{plot_w:.2f}" height="{plot_h:.2f}" fill="#FFFFFF" stroke="#D1D5DB" />
  {''.join(y_tick_lines)}
  <line x1="{plot_x:.2f}" y1="{plot_y + plot_h:.2f}" x2="{plot_x + plot_w:.2f}" y2="{plot_y + plot_h:.2f}" stroke="#6B7280" stroke-width="1.5" />
  <line x1="{plot_x:.2f}" y1="{plot_y:.2f}" x2="{plot_x:.2f}" y2="{plot_y + plot_h:.2f}" stroke="#6B7280" stroke-width="1.5" />
  {''.join(x_tick_lines)}
  {''.join(line_paths)}
  {''.join(legend_items)}
</svg>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")


def _write_index_html(
    output_path: Path,
    revenue_svg: Path,
    transactions_svg: Path,
    audience_svg: Path,
) -> None:
    revenue_name = revenue_svg.name
    transactions_name = transactions_svg.name
    audience_name = audience_svg.name
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Synthetic Marketplace Projection Charts</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #111827; }}
    h1 {{ margin: 0 0 6px 0; }}
    p {{ margin: 0 0 20px 0; color: #4B5563; }}
    .chart {{ margin: 20px 0 32px 0; border: 1px solid #E5E7EB; border-radius: 10px; overflow: hidden; }}
    img {{ width: 100%; height: auto; display: block; }}
  </style>
</head>
<body>
  <h1>Synthetic Marketplace Projections</h1>
  <p>Charts generated from the synthetic 36-month projection workbook.</p>
  <div class="chart"><img src="{escape(revenue_name)}" alt="Revenue projection chart" /></div>
  <div class="chart"><img src="{escape(transactions_name)}" alt="Transaction projection chart" /></div>
  <div class="chart"><img src="{escape(audience_name)}" alt="Audience projection chart" /></div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    workbook_input = MARKETPLACE_FINANCE_DIR / DATA_PATHS.projection_workbook_xlsx
    output_dir = MARKETPLACE_FINANCE_DIR / DATA_PATHS.charts_dir

    marketplace_fee_rows = read_projection_sheet_rows(workbook_input, SHEET_MARKETPLACE_FEES)
    audience_rows = read_projection_sheet_rows(workbook_input, SHEET_MAU)
    subscriptions_rows = read_projection_sheet_rows(workbook_input, SHEET_SUBSCRIPTIONS)
    ad_rows = read_projection_sheet_rows(workbook_input, SHEET_ADS)

    audience_by_month = {row["month"]: row for row in audience_rows}
    subscriptions_by_month = {row["month"]: row for row in subscriptions_rows}
    ad_by_month = {row["month"]: row for row in ad_rows}

    months: list[str] = []
    total_revenue: list[float] = []
    marketplace_fee_revenue: list[float] = []
    subscription_revenue: list[float] = []
    ad_revenue: list[float] = []
    transaction_count: list[float] = []
    mau: list[float] = []
    active_subscribers: list[float] = []

    for row in marketplace_fee_rows:
        month = row.get("month") or ""
        if not month:
            continue
        audience_row = audience_by_month.get(month, {})
        sub_row = subscriptions_by_month.get(month, {})
        ad_row = ad_by_month.get(month, {})

        fee = float(row.get("transaction_fee_revenue_usd") or 0.0)
        subscriptions = float(sub_row.get("subscription_revenue_usd") or 0.0)
        ads = float(ad_row.get("ad_revenue_usd") or 0.0)

        months.append(month)
        marketplace_fee_revenue.append(fee)
        subscription_revenue.append(subscriptions)
        ad_revenue.append(ads)
        total_revenue.append(fee + subscriptions + ads)
        transaction_count.append(float(row.get("transaction_count") or 0.0))
        mau.append(float(audience_row.get("mau") or 0.0))
        active_subscribers.append(float(sub_row.get("active_subscribers") or 0.0))

    revenue_svg = output_dir / DATA_PATHS.revenue_chart_svg
    transactions_svg = output_dir / DATA_PATHS.transactions_chart_svg
    audience_svg = output_dir / DATA_PATHS.audience_chart_svg
    index_html = output_dir / DATA_PATHS.charts_index_html

    _render_line_chart_svg(
        title="Synthetic Revenue Projection (36 Months)",
        subtitle="Total revenue with marketplace fee, subscription, and ad components",
        y_label="Revenue (USD)",
        y_formatter="usd",
        months=months,
        series=[
            Series("Total Revenue", "#2563EB", total_revenue),
            Series("Marketplace Fee Revenue", "#DC2626", marketplace_fee_revenue),
            Series("Subscription Revenue", "#059669", subscription_revenue),
            Series("Ad Revenue", "#7C3AED", ad_revenue),
        ],
        output_path=revenue_svg,
    )
    _render_line_chart_svg(
        title="Synthetic Transaction Projection (36 Months)",
        subtitle="Monthly transaction counts from workbook sheet MarketplaceFees",
        y_label="Transactions",
        y_formatter="count",
        months=months,
        series=[
            Series("Transaction Count", "#EA580C", transaction_count),
        ],
        output_path=transactions_svg,
    )
    _render_line_chart_svg(
        title="Synthetic Audience Projection (36 Months)",
        subtitle="MAU from workbook sheet MAU and active subscribers from workbook sheet Subscriptions",
        y_label="Users",
        y_formatter="count",
        months=months,
        series=[
            Series("MAU", "#2563EB", mau),
            Series("Active Subscribers", "#059669", active_subscribers),
        ],
        output_path=audience_svg,
    )
    _write_index_html(
        index_html,
        revenue_svg=revenue_svg,
        transactions_svg=transactions_svg,
        audience_svg=audience_svg,
    )

    print(f"workbook_input={workbook_input}")
    print(f"revenue_chart={revenue_svg}")
    print(f"transactions_chart={transactions_svg}")
    print(f"audience_chart={audience_svg}")
    print(f"chart_index={index_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
