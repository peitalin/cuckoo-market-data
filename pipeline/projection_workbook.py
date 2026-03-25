from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED
from zipfile import ZipFile

try:
    from .assumptions import RevenueProjectionAssumptions
except ImportError:
    from assumptions import RevenueProjectionAssumptions

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"

SHEET_SUMMARY = "Summary"
SHEET_MARKETPLACE_FEES = "Marketplace Revenue"
SHEET_MAU = "MAU & Operating Metrics"
SHEET_SUBSCRIPTIONS = "Subscriptions"
SHEET_ADS = "Advertising"
SHEET_EXPENSES = "OpEx"


def _col_name(index: int) -> str:
    value = index
    output = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        output = chr(65 + remainder) + output
    return output


def _cell_ref(col_index: int, row_index: int) -> str:
    return f"{_col_name(col_index)}{row_index}"


def _column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - 64)
    return value


def _xml_text(value: Any) -> str:
    return escape(str(value))


def _number_text(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.15g}"
    return str(value)


@dataclass(frozen=True)
class Cell:
    kind: str
    value: str | float | int
    formula: str | None = None

    @staticmethod
    def string(value: str) -> Cell:
        return Cell(kind="string", value=value)

    @staticmethod
    def number(value: float | int) -> Cell:
        return Cell(kind="number", value=value)

    @staticmethod
    def formula_number(formula: str, cached_value: float | int) -> Cell:
        return Cell(kind="formula_number", value=cached_value, formula=formula)


@dataclass(frozen=True)
class Sheet:
    name: str
    rows: list[list[Cell]]
    state: str = "visible"


def _cell_xml(cell_ref: str, cell: Cell) -> str:
    if cell.kind == "string":
        return (
            f'<c r="{cell_ref}" t="inlineStr">'
            f"<is><t>{_xml_text(cell.value)}</t></is>"
            "</c>"
        )
    if cell.kind == "number":
        return f'<c r="{cell_ref}"><v>{_number_text(cell.value)}</v></c>'
    if cell.kind == "formula_number":
        return (
            f'<c r="{cell_ref}">'
            f"<f>{_xml_text(cell.formula or '')}</f>"
            f"<v>{_number_text(cell.value)}</v>"
            "</c>"
        )
    raise ValueError(f"unsupported cell kind: {cell.kind}")


def _sheet_xml(sheet: Sheet) -> str:
    max_cols = max((len(row) for row in sheet.rows), default=1)
    max_rows = max(1, len(sheet.rows))
    dimension = f"A1:{_cell_ref(max_cols, max_rows)}"
    row_xml: list[str] = []
    for row_index, row in enumerate(sheet.rows, start=1):
        cells = "".join(
            _cell_xml(_cell_ref(col_index, row_index), cell)
            for col_index, cell in enumerate(row, start=1)
        )
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    return (
        f'<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        "<sheetFormatPr defaultRowHeight=\"15\"/>"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        "</worksheet>"
    )


def _workbook_xml(sheets: list[Sheet]) -> str:
    sheet_xml = "".join(
        (
            f'<sheet name="{_xml_text(sheet.name)}" sheetId="{index}" '
            f'state="{sheet.state}" r:id="rId{index}"/>'
        )
        for index, sheet in enumerate(sheets, start=1)
    )
    return (
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">'
        "<bookViews><workbookView xWindow=\"0\" yWindow=\"0\" windowWidth=\"28800\" windowHeight=\"17280\"/></bookViews>"
        f"<sheets>{sheet_xml}</sheets>"
        '<calcPr calcId="181029" calcMode="auto" fullCalcOnLoad="1"/>'
        "</workbook>"
    )


def _content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    overrides.extend(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}"
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PACKAGE}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PACKAGE}">{rels}</Relationships>'
    )


def _core_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>Synthetic Marketplace Projection Model</dc:title>"
        "<dc:creator>Codex</dc:creator>"
        "</cp:coreProperties>"
    )


def _app_xml(sheet_names: list[str]) -> str:
    heading_pairs = '<vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant><vt:i4>{}</vt:i4></vt:variant></vt:vector>'.format(
        len(sheet_names)
    )
    titles = "".join(f"<vt:lpstr>{_xml_text(name)}</vt:lpstr>" for name in sheet_names)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Codex</Application>"
        f"<HeadingPairs>{heading_pairs}</HeadingPairs>"
        f'<TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector></TitlesOfParts>'
        "</Properties>"
    )


def write_projection_workbook(
    output_path: Path,
    *,
    assumptions: RevenueProjectionAssumptions,
    baseline_month: date,
    baseline_gmv_usd: float,
    baseline_transaction_count: int,
    monthly_factors: dict[int, float],
    marketplace_fee_rows: list[dict[str, Any]],
    user_cohort_rows: list[dict[str, Any]],
    user_cohort_matrix: list[list[int]],
    mau_rows: list[dict[str, Any]],
    subscription_rows: list[dict[str, Any]],
    ad_rows: list[dict[str, Any]],
    market_driver_rows: list[dict[str, float]],
    ad_driver_rows: list[dict[str, float]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_avg_sell_price = baseline_gmv_usd / max(1, baseline_transaction_count)
    raw_baseline_month_factor = monthly_factors[baseline_month.month]
    normalized_monthly_factors = {
        month: factor / raw_baseline_month_factor
        for month, factor in monthly_factors.items()
    }
    projection_months = assumptions.projection_months

    def _assumption_row(name: str, value: str | float | int, details: str) -> list[Cell]:
        value_cell = Cell.string(value) if isinstance(value, str) else Cell.number(value)
        return [Cell.string(name), value_cell, Cell.string(details)]

    def _section_row(title: str, details: str) -> list[Cell]:
        return [Cell.string(f"[{title}]"), Cell.string(""), Cell.string(details)]

    def _blank_row() -> list[Cell]:
        return [Cell.string(""), Cell.string(""), Cell.string("")]

    def _sheet_assumption_block(
        title: str,
        details: str,
        spec_rows: list[tuple[str, str | float | int, str]],
    ) -> tuple[list[list[Cell]], dict[str, str]]:
        rows = [
            _section_row(title, details),
            [Cell.string("name"), Cell.string("value"), Cell.string("details")],
        ]
        refs: dict[str, str] = {}
        for offset, (name, value, row_details) in enumerate(spec_rows, start=3):
            rows.append(_assumption_row(name, value, row_details))
            refs[name] = f"$B${offset}"
        rows.append(_blank_row())
        return rows, refs

    def _section_assumption_block_at(
        start_row: int,
        title: str,
        details: str,
        spec_rows: list[tuple[str, str | float | int, str]],
    ) -> tuple[list[list[Cell]], dict[str, str]]:
        rows = [
            _section_row(title, details),
            [Cell.string("name"), Cell.string("value"), Cell.string("details")],
        ]
        refs: dict[str, str] = {}
        for offset, (name, value, row_details) in enumerate(spec_rows, start=2):
            rows.append(_assumption_row(name, value, row_details))
            refs[name] = f"$B${start_row + offset}"
        rows.append(_blank_row())
        return rows, refs

    def _retained_share_value(age: int) -> float:
        if age <= 0:
            return 1.0
        if age == 1:
            return assumptions.user_retention_month_1
        if age == 2:
            return assumptions.user_retention_month_2
        if age == 3:
            return assumptions.user_retention_month_3
        return assumptions.user_retention_month_3 * pow(
            assumptions.user_retention_decay,
            age - 3,
        )

    marketplace_preamble, marketplace_refs = _sheet_assumption_block(
        "Marketplace Revenue Assumptions",
        "Inputs used by the marketplace fee projection below.",
        [
            ("projection_start_month", assumptions.projection_start_month, "First month of the synthetic projection in YYYY-MM format."),
            ("seasonality_lookback_years", assumptions.seasonality_lookback_years, "Historical lookback window used to build month-level seasonality factors."),
            ("baseline_month", baseline_month.isoformat(), "Observed marketplace month used to anchor GMV and average selling price."),
            ("baseline_month_gmv_usd", round(baseline_gmv_usd, 2), "Observed GMV for the baseline month from raw daily sales data."),
            ("baseline_month_transaction_count", baseline_transaction_count, "Observed transaction count for the baseline month from raw daily sales data."),
            ("baseline_month_avg_sell_price_usd", round(baseline_avg_sell_price, 2), "Derived average selling price for the baseline month."),
            ("sales_cagr", assumptions.sales_cagr, "Annual growth rate applied to marketplace sales in Years 2 and 3."),
            ("avg_sell_price_annual_growth", assumptions.avg_sell_price_annual_growth, "Annual inflation-style growth rate applied to average selling price."),
            ("take_rate", assumptions.take_rate, "Marketplace fee rate applied to projected GMV."),
            ("year2_3_min_txns", assumptions.year2_3_min_txns, "Lower bound for projected monthly transaction count after Year 1."),
            ("year2_3_max_txns", assumptions.year2_3_max_txns, "Upper bound for projected monthly transaction count after Year 1."),
            ("jitter_std", assumptions.jitter_std, "Standard deviation used by the random-driver formulas."),
        ],
    )
    mau_preamble, mau_refs = _sheet_assumption_block(
        "MAU & Operating Metrics Assumptions",
        "Inputs used by the MAU rollup and cohort acquisition/retention model below.",
        [
            ("projection_months", assumptions.projection_months, "Number of projected monthly rows in the workbook model."),
            ("projection_start_month", assumptions.projection_start_month, "First month of the synthetic projection in YYYY-MM format."),
            ("new_users_start", assumptions.new_users_start, "New users acquired in the first projected cohort month."),
            ("new_users_monthly_growth_year1", assumptions.new_users_monthly_growth_year1, "Monthly new-user growth rate applied in Year 1."),
            ("new_users_monthly_growth_year2", assumptions.new_users_monthly_growth_year2, "Monthly new-user growth rate applied in Year 2."),
            ("new_users_monthly_growth_year3", assumptions.new_users_monthly_growth_year3, "Monthly new-user growth rate applied in Year 3."),
            ("new_user_holiday_spike_multiplier", assumptions.new_user_holiday_spike_multiplier, "Extra acquisition multiplier applied in November and December."),
            (
                "base_new_users_rule",
                "Month 0 = start; later months = prior month * (1 + current growth rate)",
                "Human-readable formula for the base_new_users column before seasonality, holiday spike, and noise are applied.",
            ),
            ("user_retention_month_1", assumptions.user_retention_month_1, "Share of a cohort still active one month after signup."),
            ("user_retention_month_2", assumptions.user_retention_month_2, "Share of a cohort still active two months after signup."),
            ("user_retention_month_3", assumptions.user_retention_month_3, "Share of a cohort still active three months after signup."),
            ("user_retention_decay", assumptions.user_retention_decay, "Monthly decay applied to cohort retention after Month 3."),
            ("jitter_std", assumptions.jitter_std, "Standard deviation used by cohort acquisition noise."),
            ("dependency", "MAU cohort matrix on this sheet", "MAU is derived by summing active cohort contributions from the cohort matrix on this sheet."),
        ],
    )
    subscriptions_preamble, subscriptions_refs = _sheet_assumption_block(
        "Subscriptions Assumptions",
        "Inputs used by the subscription revenue projection below.",
        [
            ("projection_months", assumptions.projection_months, "Number of projected monthly rows in the workbook model."),
            ("projection_start_month", assumptions.projection_start_month, "First month of the synthetic projection in YYYY-MM format."),
            ("subscription_conversion_start", assumptions.subscription_conversion_start, "Initial MAU-to-paid conversion rate."),
            ("subscription_conversion_end", assumptions.subscription_conversion_end, "Target MAU-to-paid conversion rate approached over time."),
            ("subscription_conversion_monthly_improvement_rate", assumptions.subscription_conversion_monthly_improvement_rate, "Share of the remaining conversion-rate gap closed each month."),
            ("subscription_retention_start", assumptions.subscription_retention_start, "Initial monthly subscriber retention rate."),
            ("subscription_retention_end", assumptions.subscription_retention_end, "Target monthly subscriber retention rate approached over time."),
            ("subscription_retention_monthly_improvement_rate", assumptions.subscription_retention_monthly_improvement_rate, "Share of the remaining retention-rate gap closed each month."),
            ("subscription_price_usd", assumptions.subscription_price_usd, "Monthly subscription price used by the Subscriptions sheet."),
            ("dependency", "MAU & Operating Metrics.mau", "Subscriber-state and subscription revenue are derived from the MAU & Operating Metrics sheet's audience base."),
        ],
    )
    ads_preamble, ads_refs = _sheet_assumption_block(
        "Advertising Assumptions",
        "Inputs used by the ad revenue projection below.",
        [
            ("projection_months", assumptions.projection_months, "Number of projected monthly rows in the workbook model."),
            ("projection_start_month", assumptions.projection_start_month, "First month of the synthetic projection in YYYY-MM format."),
            ("sessions_per_mau", assumptions.sessions_per_mau, "Monthly sessions generated by each monthly active user."),
            ("pageviews_per_session", assumptions.pageviews_per_session, "Average pageviews generated in each session."),
            ("ad_action_rate_per_pageview", assumptions.ad_action_rate_per_pageview, "Share of pageviews that convert into a CPA-qualified action."),
            ("ad_cpa_usd", assumptions.ad_cpa_usd, "CPA payout in USD for each modeled ad action."),
            ("jitter_std", assumptions.jitter_std, "Standard deviation used by the random-driver formulas."),
            ("dependency", "MAU & Operating Metrics.mau", "Ad calculations are derived from MAU & Operating Metrics, sessions, and pageviews."),
        ],
    )
    expenses_preamble, expenses_refs = _sheet_assumption_block(
        "OpEx Assumptions",
        "Inputs used by the top-line expense model below.",
        [
            ("projection_months", assumptions.projection_months, "Number of projected monthly rows in the workbook model."),
            ("projection_start_month", assumptions.projection_start_month, "First month of the synthetic projection in YYYY-MM format."),
            ("dependency", "MAU & Operating Metrics.mau / MAU & Operating Metrics.new_users / Advertising.pageviews", "The finance-facing expense table uses audience and traffic plus the cloud-cost helper section below."),
            ("instagram_marketing_monthly_year1", assumptions.instagram_marketing_monthly_year1, "Monthly Instagram paid-marketing budget in Year 1."),
            ("instagram_marketing_monthly_year2", assumptions.instagram_marketing_monthly_year2, "Monthly Instagram paid-marketing budget in Year 2."),
            ("instagram_marketing_monthly_year3", assumptions.instagram_marketing_monthly_year3, "Monthly Instagram paid-marketing budget in Year 3."),
            ("twitter_marketing_monthly_year1", assumptions.twitter_marketing_monthly_year1, "Monthly Twitter/X paid-marketing budget in Year 1."),
            ("twitter_marketing_monthly_year2", assumptions.twitter_marketing_monthly_year2, "Monthly Twitter/X paid-marketing budget in Year 2."),
            ("twitter_marketing_monthly_year3", assumptions.twitter_marketing_monthly_year3, "Monthly Twitter/X paid-marketing budget in Year 3."),
            ("facebook_marketing_monthly_year1", assumptions.facebook_marketing_monthly_year1, "Monthly Facebook paid-marketing budget in Year 1."),
            ("facebook_marketing_monthly_year2", assumptions.facebook_marketing_monthly_year2, "Monthly Facebook paid-marketing budget in Year 2."),
            ("facebook_marketing_monthly_year3", assumptions.facebook_marketing_monthly_year3, "Monthly Facebook paid-marketing budget in Year 3."),
            ("content_creation_monthly_year1", assumptions.content_creation_monthly_year1, "Monthly content-creation and graphics budget in Year 1."),
            ("content_creation_monthly_year2", assumptions.content_creation_monthly_year2, "Monthly content-creation and graphics budget in Year 2."),
            ("content_creation_monthly_year3", assumptions.content_creation_monthly_year3, "Monthly content-creation and graphics budget in Year 3."),
            ("team_size_year1", assumptions.team_size_year1, "Team size in Year 1, used only to size software tools."),
            ("team_size_year2", assumptions.team_size_year2, "Team size in Year 2, used only to size software tools."),
            ("team_size_year3", assumptions.team_size_year3, "Team size in Year 3, used only to size software tools."),
            ("software_tools_per_team_member_monthly_usd", assumptions.software_tools_per_team_member_monthly_usd, "Combined Google Workspace and Slack cost per team member per month in USD."),
            ("incorporation_setup_usd", assumptions.incorporation_setup_usd, "One-time incorporation and setup cost in USD, applied in the first projected month."),
        ],
    )
    expenses_cloud_specs = [
        ("r2_storage_start_gb", assumptions.r2_storage_start_gb, "Opening R2 storage footprint in GB."),
        ("r2_storage_target_end_gb", assumptions.r2_storage_target_end_gb, "Target R2 storage footprint by the end of the model in GB."),
        ("r2_storage_price_per_gb_month", assumptions.r2_storage_price_per_gb_month, "Cloudflare R2 storage price in USD per GB-month."),
        ("r2_storage_free_gb", assumptions.r2_storage_free_gb, "Free R2 storage included each month in GB."),
        ("r2_class_a_ops_per_new_user", assumptions.r2_class_a_ops_per_new_user, "Estimated write/list operations generated by each new user."),
        ("r2_class_a_price_per_million", assumptions.r2_class_a_price_per_million, "Cloudflare R2 Class A request price in USD per million operations."),
        ("r2_class_b_ops_per_pageview", assumptions.r2_class_b_ops_per_pageview, "Estimated read/get operations generated by each pageview."),
        ("r2_class_b_price_per_million", assumptions.r2_class_b_price_per_million, "Cloudflare R2 Class B request price in USD per million operations."),
        ("postgres_base_plan_monthly_usd", assumptions.postgres_base_plan_monthly_usd, "Managed Postgres platform plan cost in USD per month."),
        ("postgres_micro_compute_monthly_usd", assumptions.postgres_micro_compute_monthly_usd, "Managed Postgres micro compute cost in USD per month."),
        ("postgres_small_compute_monthly_usd", assumptions.postgres_small_compute_monthly_usd, "Managed Postgres small compute cost in USD per month."),
        ("postgres_medium_compute_monthly_usd", assumptions.postgres_medium_compute_monthly_usd, "Managed Postgres medium compute cost in USD per month."),
        ("postgres_small_mau_threshold", assumptions.postgres_small_mau_threshold, "MAU threshold for scaling Postgres from micro to small compute."),
        ("postgres_medium_mau_threshold", assumptions.postgres_medium_mau_threshold, "MAU threshold for scaling Postgres from small to medium compute."),
        ("postgres_read_replica_mau_threshold", assumptions.postgres_read_replica_mau_threshold, "MAU threshold for enabling one read-only replica. Defaults high enough that no replica is used in the current scenario."),
        ("postgres_disk_base_gb", assumptions.postgres_disk_base_gb, "Included Postgres disk before overage pricing in GB."),
        ("postgres_disk_gb_per_1000_cumulative_new_users", assumptions.postgres_disk_gb_per_1000_cumulative_new_users, "Estimated Postgres disk growth per 1,000 cumulative new users in GB."),
        ("postgres_disk_price_per_gb_month", assumptions.postgres_disk_price_per_gb_month, "Managed Postgres disk overage price in USD per GB-month."),
        ("cloudflare_pages_monthly_usd", assumptions.cloudflare_pages_monthly_usd, "Monthly Cloudflare Pages hosting cost in USD."),
        ("workers_base_monthly_usd", assumptions.workers_base_monthly_usd, "Base Cloudflare Workers paid-plan cost in USD per month."),
        ("workers_included_requests_millions", assumptions.workers_included_requests_millions, "Workers request allowance included each month in millions."),
        ("workers_request_price_per_million", assumptions.workers_request_price_per_million, "Workers request overage price in USD per million requests."),
        ("workers_included_cpu_million_ms", assumptions.workers_included_cpu_million_ms, "Workers CPU allowance included each month in million milliseconds."),
        ("workers_cpu_price_per_million_ms", assumptions.workers_cpu_price_per_million_ms, "Workers CPU overage price in USD per million milliseconds."),
        ("workers_requests_per_pageview", assumptions.workers_requests_per_pageview, "Estimated backend requests generated by each pageview."),
        ("workers_requests_per_new_user", assumptions.workers_requests_per_new_user, "Estimated backend requests generated by each new user."),
        ("workers_avg_cpu_ms_per_request", assumptions.workers_avg_cpu_ms_per_request, "Average CPU time consumed per backend request in milliseconds."),
        ("transactional_email_monthly_usd", assumptions.transactional_email_monthly_usd, "Flat monthly transactional email SaaS cost in USD."),
        ("scraper_proxy_monthly_usd", assumptions.scraper_proxy_monthly_usd, "Monthly static residential/ISP proxy budget in USD."),
    ]

    marketplace_data_start = len(marketplace_preamble) + 2
    mau_data_start = len(mau_preamble) + 2
    subscriptions_data_start = len(subscriptions_preamble) + 2
    ads_data_start = len(ads_preamble) + 2
    expenses_data_start = len(expenses_preamble) + 2

    marketplace_rows = marketplace_preamble + [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("transaction_count"),
        Cell.string("avg_sell_price_growth"),
        Cell.string("avg_sell_price_usd"),
        Cell.string("gross_market_value_usd"),
        Cell.string("take_rate"),
        Cell.string("transaction_fee_revenue_usd"),
    ]]
    marketplace_main_data_start = marketplace_data_start
    marketplace_main_last_row = marketplace_main_data_start + projection_months - 1
    marketplace_helper_title_row = marketplace_main_last_row + 2
    marketplace_helper_header_row = marketplace_helper_title_row + 1
    marketplace_helper_data_start = marketplace_helper_header_row + 1
    for offset, row in enumerate(marketplace_fee_rows):
        index = marketplace_main_data_start + offset
        helper_index = marketplace_helper_data_start + offset
        year_ref = f"$B{index}"
        helper_txn_noise_ref = f"F{helper_index}"
        helper_avg_sell_price_noise_ref = f"G{helper_index}"
        helper_txns_base_ref = f"J{helper_index}"
        helper_txns_seasonality_ref = f"K{helper_index}"
        txns_ref = f"D{index}"
        avg_sell_price_growth_ref = f"E{index}"
        avg_sell_price_ref = f"F{index}"
        gmv_ref = f"G{index}"
        take_rate_ref = f"H{index}"
        projection_offset = offset - 12
        year_index = int(row["year_index"])
        avg_sell_price_growth = (
            0.0
            if year_index == 1
            else 1 + (assumptions.avg_sell_price_annual_growth * projection_offset / 12)
        )
        marketplace_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(year_index),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,0,"
                        f"MIN({marketplace_refs['year2_3_max_txns']},"
                        f"MAX({marketplace_refs['year2_3_min_txns']},"
                        f"ROUND({helper_txns_base_ref}*{helper_txns_seasonality_ref}*{helper_txn_noise_ref},0))))"
                    ),
                    cached_value=float(row["transaction_count"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,0,"
                        f"1+({marketplace_refs['avg_sell_price_annual_growth']}*{projection_offset}/12))"
                    ),
                    cached_value=avg_sell_price_growth,
                ),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,0,"
                        f"ROUND({marketplace_refs['baseline_month_avg_sell_price_usd']}*"
                        f"{avg_sell_price_growth_ref}*"
                        f"{helper_avg_sell_price_noise_ref},2))"
                    ),
                    cached_value=float(row["avg_sell_price_usd"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND({txns_ref}*{avg_sell_price_ref},2)",
                    cached_value=float(row["gross_market_value_usd"]),
                ),
                Cell.formula_number(
                    formula=marketplace_refs["take_rate"],
                    cached_value=float(row["take_rate"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(IF({txns_ref}>0,{gmv_ref}*{take_rate_ref},0),2)",
                    cached_value=float(row["transaction_fee_revenue_usd"]),
                ),
            ]
        )
    marketplace_rows.append([Cell.string("") for _ in range(11)])
    marketplace_rows.append([
        Cell.string("[Implementation Factors]"),
        Cell.string(""),
        Cell.string("Seasonality and noise factors used by the finance-facing table above."),
    ])
    marketplace_rows.append([
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("seasonality_factor"),
        Cell.string("noise_market_year1_jitter"),
        Cell.string("noise_market_txn"),
        Cell.string("noise_market_avg_sell_price"),
        Cell.string("cagr_multiplier"),
        Cell.string("noise_market_combined"),
        Cell.string("txn_trend_base"),
        Cell.string("txn_seasonality_multiplier"),
    ])
    for offset, row in enumerate(marketplace_fee_rows):
        helper_index = marketplace_helper_data_start + offset
        helper_year_ref = f"$B{helper_index}"
        helper_seasonality_ref = f"D{helper_index}"
        helper_year1_jitter_ref = f"E{helper_index}"
        helper_txn_noise_ref = f"F{helper_index}"
        helper_avg_sell_price_noise_ref = f"G{helper_index}"
        month_text = str(row["month"])
        month_number = int(month_text[5:7])
        year_index = int(row["year_index"])
        seasonality_factor = normalized_monthly_factors[month_number]
        projection_offset = offset - 12
        if year_index == 1:
            txn_trend_base = 0.0
            txn_seasonality_multiplier = 0.0
        else:
            ramp_progress = projection_offset / 23
            txn_trend_base = assumptions.year2_3_min_txns + (
                assumptions.year2_3_max_txns - assumptions.year2_3_min_txns
            ) * ramp_progress
            txn_seasonality_multiplier = 0.85 + 0.15 * seasonality_factor
        marketplace_rows.append(
            [
                Cell.string(month_text),
                Cell.number(year_index),
                Cell.string(str(row["phase"])),
                Cell.number(seasonality_factor),
                Cell.formula_number(
                    formula=f"MAX(0.7,1+_xlfn.NORM.INV(RAND(),0,{marketplace_refs['jitter_std']}*0.5))",
                    cached_value=market_driver_rows[offset]["noise_market_year1_jitter"],
                ),
                Cell.formula_number(
                    formula=f"MAX(0.85,1+_xlfn.NORM.INV(RAND(),0,{marketplace_refs['jitter_std']}*0.4))",
                    cached_value=market_driver_rows[offset]["noise_market_txn"],
                ),
                Cell.formula_number(
                    formula=f"MAX(0.75,1+_xlfn.NORM.INV(RAND(),0,{marketplace_refs['jitter_std']}*0.35))",
                    cached_value=market_driver_rows[offset]["noise_market_avg_sell_price"],
                ),
                Cell.formula_number(
                    formula=f"IF({helper_year_ref}=1,1,POWER(1+{marketplace_refs['sales_cagr']},{projection_offset}/12))",
                    cached_value=float(row["cagr_multiplier"]),
                ),
                Cell.formula_number(
                    formula=f"IF({helper_year_ref}=1,{helper_year1_jitter_ref},{helper_txn_noise_ref}*{helper_avg_sell_price_noise_ref})",
                    cached_value=float(row["noise_market_combined"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"IF({helper_year_ref}=1,0,"
                        f"{marketplace_refs['year2_3_min_txns']}+"
                        f"({marketplace_refs['year2_3_max_txns']}-{marketplace_refs['year2_3_min_txns']})*({projection_offset}/23))"
                    ),
                    cached_value=txn_trend_base,
                ),
                Cell.formula_number(
                    formula=f"IF({helper_year_ref}=1,0,0.85+0.15*{helper_seasonality_ref})",
                    cached_value=txn_seasonality_multiplier,
                ),
            ]
        )

    spacer_col = 7
    cohort_growth_col = 8
    base_new_users_col = 9
    cohort_seasonality_col = 10
    noise_acquisition_col = 11
    second_spacer_col = 12
    retention_age_col = 13
    retained_share_col = 14
    first_contribution_col = 15
    last_contribution_col = first_contribution_col + projection_months - 1
    retained_share_range = (
        f"${_col_name(retained_share_col)}${mau_data_start}:"
        f"${_col_name(retained_share_col)}${mau_data_start + projection_months - 1}"
    )
    mau_sheet_rows = mau_preamble + [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("new_users"),
        Cell.string("returning_users"),
        Cell.string("mau"),
        Cell.string(""),
        Cell.string("acquisition_growth_rate"),
        Cell.string("base_new_users"),
        Cell.string("seasonality_factor"),
        Cell.string("noise_acquisition"),
        Cell.string(""),
        Cell.string("user_retention_age"),
        Cell.string("user_retained_share"),
        *[Cell.string(str(row["month"])) for row in user_cohort_rows],
    ]]
    for offset, row in enumerate(mau_rows):
        index = mau_data_start + offset
        year_ref = f"$B{index}"
        growth_rate_ref = f"{_col_name(cohort_growth_col)}{index}"
        base_new_users_ref = f"{_col_name(base_new_users_col)}{index}"
        seasonality_ref = f"{_col_name(cohort_seasonality_col)}{index}"
        noise_acquisition_ref = f"{_col_name(noise_acquisition_col)}{index}"
        new_users_ref = f"D{index}"
        contribution_col = _col_name(first_contribution_col + offset)
        mau_ref = f"F{index}"
        contributions: list[Cell] = []
        for month_offset in range(projection_months):
            if month_offset < offset:
                contributions.append(Cell.string(""))
                continue
            contributions.append(
                Cell.formula_number(
                    formula=f"ROUND({new_users_ref}*INDEX({retained_share_range},{1 + month_offset - offset}),0)",
                    cached_value=user_cohort_matrix[offset][month_offset],
                )
            )
        seasonality_value = float(user_cohort_rows[offset]["seasonality_factor"])
        mau_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=(
                        f"ROUND(MAX(100,{base_new_users_ref}*"
                        f"{seasonality_ref}*"
                        f"{noise_acquisition_ref}),0)"
                    ),
                    cached_value=float(row["new_users"]),
                ),
                Cell.formula_number(
                    formula=f"MAX(0,{mau_ref}-{new_users_ref})",
                    cached_value=float(row["returning_users"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND(SUM(${contribution_col}${mau_data_start}:"
                        f"${contribution_col}${mau_data_start + projection_months - 1}),0)"
                    ),
                    cached_value=float(row["mau"]),
                ),
                Cell.string(""),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,{mau_refs['new_users_monthly_growth_year1']},"
                        f"IF({year_ref}=2,{mau_refs['new_users_monthly_growth_year2']},"
                        f"{mau_refs['new_users_monthly_growth_year3']}))"
                    ),
                    cached_value=float(user_cohort_rows[offset]["acquisition_growth_rate"]),
                ),
                Cell.formula_number(
                    formula=(
                        mau_refs["new_users_start"]
                        if offset == 0
                        else f"{_col_name(base_new_users_col)}{index - 1}*(1+{growth_rate_ref})"
                    ),
                    cached_value=float(user_cohort_rows[offset]["base_new_users"]),
                ),
                Cell.number(seasonality_value),
                Cell.formula_number(
                    formula=f"MAX(0.85,1+_xlfn.NORM.INV(RAND(),0,{mau_refs['jitter_std']}*0.35))",
                    cached_value=float(user_cohort_rows[offset]["noise_acquisition"]),
                ),
                Cell.string(""),
                Cell.number(offset),
                Cell.formula_number(
                    formula=(
                        f"IF(${_col_name(retention_age_col)}{index}=0,1,"
                        f"IF(${_col_name(retention_age_col)}{index}=1,{mau_refs['user_retention_month_1']},"
                        f"IF(${_col_name(retention_age_col)}{index}=2,{mau_refs['user_retention_month_2']},"
                        f"IF(${_col_name(retention_age_col)}{index}=3,{mau_refs['user_retention_month_3']},"
                        f"{mau_refs['user_retention_month_3']}*POWER({mau_refs['user_retention_decay']},${_col_name(retention_age_col)}{index}-3)))))"
                    ),
                    cached_value=_retained_share_value(offset),
                ),
                *contributions,
            ]
        )

    subscription_sheet_rows = subscriptions_preamble + [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("mau"),
        Cell.string("subscription_conversion_rate"),
        Cell.string("subscription_retention_rate"),
        Cell.string("retained_subscribers"),
        Cell.string("new_subscribers"),
        Cell.string("churned_subscribers"),
        Cell.string("active_subscribers"),
        Cell.string("subscription_price_usd"),
        Cell.string("subscription_revenue_usd"),
    ]]
    for offset, row in enumerate(subscription_rows):
        index = subscriptions_data_start + offset
        mau_row = mau_data_start + offset
        mau_ref = f"D{index}"
        conversion_ref = f"E{index}"
        retention_ref = f"F{index}"
        retained_ref = f"G{index}"
        prior_active_ref = f"IF(ROW()={subscriptions_data_start},0,J{index - 1})"
        subscription_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=f"'{SHEET_MAU}'!$F{mau_row}",
                    cached_value=float(row["mau"]),
                ),
                Cell.formula_number(
                    formula=(
                        subscriptions_refs["subscription_conversion_start"]
                        if offset == 0
                        else (
                            f"E{index - 1}+"
                            f"({subscriptions_refs['subscription_conversion_end']}-E{index - 1})*"
                            f"{subscriptions_refs['subscription_conversion_monthly_improvement_rate']}"
                        )
                    ),
                    cached_value=float(row["subscription_conversion_rate"]),
                ),
                Cell.formula_number(
                    formula=(
                        subscriptions_refs["subscription_retention_start"]
                        if offset == 0
                        else (
                            f"F{index - 1}+"
                            f"({subscriptions_refs['subscription_retention_end']}-F{index - 1})*"
                            f"{subscriptions_refs['subscription_retention_monthly_improvement_rate']}"
                        )
                    ),
                    cached_value=float(row["subscription_retention_rate"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND({prior_active_ref}*{retention_ref},0)",
                    cached_value=float(row["retained_subscribers"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX(0,J{index}-{retained_ref}),0)",
                    cached_value=float(row["new_subscribers"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX(0,{prior_active_ref}-{retained_ref}),0)",
                    cached_value=float(row["churned_subscribers"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX({retained_ref},{mau_ref}*{conversion_ref}),0)",
                    cached_value=float(row["active_subscribers"]),
                ),
                Cell.formula_number(
                    formula=subscriptions_refs["subscription_price_usd"],
                    cached_value=float(row["subscription_price_usd"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(J{index}*K{index},2)",
                    cached_value=float(row["subscription_revenue_usd"]),
                ),
            ]
        )

    ad_sheet_rows = ads_preamble + [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("sessions_per_mau"),
        Cell.string("pageviews_per_session"),
        Cell.string("sessions"),
        Cell.string("pageviews"),
        Cell.string("ad_action_rate_per_pageview"),
        Cell.string("noise_ad"),
        Cell.string("ad_actions"),
        Cell.string("ad_cpa_usd"),
        Cell.string("ad_revenue_usd"),
    ]]
    for offset, row in enumerate(ad_rows):
        index = ads_data_start + offset
        mau_row = mau_data_start + offset
        sessions_per_mau_ref = f"D{index}"
        pageviews_per_session_ref = f"E{index}"
        sessions_ref = f"F{index}"
        pageviews_ref = f"G{index}"
        ad_action_rate_ref = f"H{index}"
        noise_ad_ref = f"I{index}"
        ad_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=ads_refs["sessions_per_mau"],
                    cached_value=float(row["sessions_per_mau"]),
                ),
                Cell.formula_number(
                    formula=ads_refs["pageviews_per_session"],
                    cached_value=float(row["pageviews_per_session"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND('{SHEET_MAU}'!$F{mau_row}*{sessions_per_mau_ref},0)",
                    cached_value=float(row["sessions"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND({sessions_ref}*{pageviews_per_session_ref},0)",
                    cached_value=float(row["pageviews"]),
                ),
                Cell.formula_number(
                    formula=ads_refs["ad_action_rate_per_pageview"],
                    cached_value=float(row["ad_action_rate_per_pageview"]),
                ),
                Cell.formula_number(
                    formula=f"MAX(0.8,1+_xlfn.NORM.INV(RAND(),0,{ads_refs['jitter_std']}*0.3))",
                    cached_value=float(ad_driver_rows[offset]["noise_ad"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND({pageviews_ref}*{ad_action_rate_ref}*{noise_ad_ref},0)",
                    cached_value=float(row["ad_actions"]),
                ),
                Cell.formula_number(
                    formula=ads_refs["ad_cpa_usd"],
                    cached_value=float(row["ad_cpa_usd"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(J{index}*K{index},2)",
                    cached_value=float(row["ad_revenue_usd"]),
                ),
            ]
        )

    expense_total_new_users = max(1.0, sum(float(row["new_users"]) for row in mau_rows))
    expense_summary_header = [
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("technology_and_infrastructure_opex_usd"),
        Cell.string("sales_and_marketing_opex_usd"),
        Cell.string("general_and_administrative_opex_usd"),
        Cell.string("total_operating_expenses_usd"),
    ]
    expense_detail_header = [
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("total_cloud_costs"),
        Cell.string("sales_marketing_cost_usd"),
        Cell.string("software_tools_usd"),
        Cell.string("non_payroll_overhead_cost_usd"),
        Cell.string("total_expenses_usd"),
    ]
    expenses_summary_data_start = expenses_data_start
    expenses_summary_last_row = expenses_summary_data_start + projection_months - 1
    expenses_detail_title_row = expenses_summary_last_row + 2
    expenses_detail_header_row = expenses_detail_title_row + 1
    expenses_detail_data_start = expenses_detail_header_row + 1
    expenses_detail_last_row = expenses_detail_data_start + projection_months - 1
    expenses_cloud_assumptions_start = expenses_detail_last_row + 2
    expenses_cloud_preamble, expenses_cloud_refs = _section_assumption_block_at(
        expenses_cloud_assumptions_start,
        "Cloud Cost Assumptions",
        "Inputs used by the lower expense-detail and cloud-cost tables. The cloud-cost breakdown is implementation detail and is not needed in finance reports.",
        expenses_cloud_specs,
    )
    expenses_helper_title_row = expenses_cloud_assumptions_start + len(expenses_cloud_preamble)
    expenses_helper_header_row = expenses_helper_title_row + 1
    expenses_helper_data_start = expenses_helper_header_row + 1
    expense_summary_rows: list[list[Cell]] = []
    expense_detail_rows: list[list[Cell]] = []
    technology_opex_values: list[float] = []
    sales_marketing_opex_values: list[float] = []
    g_and_a_opex_values: list[float] = []
    total_opex_values: list[float] = []
    cumulative_new_users = 0.0
    for offset, row in enumerate(mau_rows):
        detail_index = expenses_detail_data_start + offset
        helper_index = expenses_helper_data_start + offset
        month_text = str(row["month"])
        month_number = int(month_text[5:7])
        holiday_marketing_active = month_number in (11, 12)
        year_index = int(row["year_index"])
        mau = float(row["mau"])
        new_users = float(row["new_users"])
        pageviews = float(ad_rows[offset]["pageviews"])
        cumulative_new_users += new_users
        if mau >= assumptions.postgres_medium_mau_threshold:
            primary_compute_cost = assumptions.postgres_medium_compute_monthly_usd
        elif mau >= assumptions.postgres_small_mau_threshold:
            primary_compute_cost = assumptions.postgres_small_compute_monthly_usd
        else:
            primary_compute_cost = assumptions.postgres_micro_compute_monthly_usd
        replica_compute_cost = (
            primary_compute_cost
            if mau >= assumptions.postgres_read_replica_mau_threshold
            else 0.0
        )
        r2_storage_gb = assumptions.r2_storage_start_gb + cumulative_new_users * (
            (assumptions.r2_storage_target_end_gb - assumptions.r2_storage_start_gb)
            / expense_total_new_users
        )
        r2_storage_cost = round(
            max(0.0, r2_storage_gb - assumptions.r2_storage_free_gb)
            * assumptions.r2_storage_price_per_gb_month,
            2,
        )
        r2_operation_cost = round(
            (new_users * assumptions.r2_class_a_ops_per_new_user / 1_000_000)
            * assumptions.r2_class_a_price_per_million
            + (pageviews * assumptions.r2_class_b_ops_per_pageview / 1_000_000)
            * assumptions.r2_class_b_price_per_million,
            2,
        )
        postgres_compute_cost = round(
            assumptions.postgres_base_plan_monthly_usd + primary_compute_cost,
            2,
        )
        postgres_disk_gb = assumptions.postgres_disk_base_gb + (
            cumulative_new_users / 1000
        ) * assumptions.postgres_disk_gb_per_1000_cumulative_new_users
        postgres_disk_cost = round(
            max(0.0, postgres_disk_gb - assumptions.postgres_disk_base_gb)
            * assumptions.postgres_disk_price_per_gb_month,
            2,
        )
        postgres_cost = round(
            postgres_compute_cost + postgres_disk_cost + replica_compute_cost,
            2,
        )
        workers_requests_millions = round(
            (
                pageviews * assumptions.workers_requests_per_pageview
                + new_users * assumptions.workers_requests_per_new_user
            )
            / 1_000_000,
            4,
        )
        workers_cpu_million_ms = round(
            workers_requests_millions * assumptions.workers_avg_cpu_ms_per_request,
            4,
        )
        workers_cost = round(
            assumptions.workers_base_monthly_usd
            + max(
                0.0,
                workers_requests_millions
                - assumptions.workers_included_requests_millions,
            )
            * assumptions.workers_request_price_per_million
            + max(
                0.0,
                workers_cpu_million_ms - assumptions.workers_included_cpu_million_ms,
            )
            * assumptions.workers_cpu_price_per_million_ms,
            2,
        )
        cloudflare_cost = round(
            assumptions.cloudflare_pages_monthly_usd + workers_cost,
            2,
        )
        transactional_email_cost = round(
            assumptions.transactional_email_monthly_usd,
            2,
        )
        object_storage_cost = round(r2_storage_cost + r2_operation_cost, 2)
        database_cost = round(postgres_cost, 2)
        cloud_storage_cost = round(r2_storage_cost + postgres_disk_cost, 2)
        cloud_compute_cost = round(
            r2_operation_cost
            + postgres_compute_cost
            + replica_compute_cost
            + cloudflare_cost
            + assumptions.scraper_proxy_monthly_usd
            + transactional_email_cost,
            2,
        )
        total_cloud_cost = round(cloud_compute_cost + cloud_storage_cost, 2)
        if year_index == 1:
            instagram_marketing = assumptions.instagram_marketing_monthly_year1 if holiday_marketing_active else 0.0
            twitter_marketing = assumptions.twitter_marketing_monthly_year1 if holiday_marketing_active else 0.0
            facebook_marketing = assumptions.facebook_marketing_monthly_year1 if holiday_marketing_active else 0.0
            content_creation = assumptions.content_creation_monthly_year1 if holiday_marketing_active else 0.0
            team_size = assumptions.team_size_year1
        elif year_index == 2:
            instagram_marketing = assumptions.instagram_marketing_monthly_year2 if holiday_marketing_active else 0.0
            twitter_marketing = assumptions.twitter_marketing_monthly_year2 if holiday_marketing_active else 0.0
            facebook_marketing = assumptions.facebook_marketing_monthly_year2 if holiday_marketing_active else 0.0
            content_creation = assumptions.content_creation_monthly_year2 if holiday_marketing_active else 0.0
            team_size = assumptions.team_size_year2
        else:
            instagram_marketing = assumptions.instagram_marketing_monthly_year3 if holiday_marketing_active else 0.0
            twitter_marketing = assumptions.twitter_marketing_monthly_year3 if holiday_marketing_active else 0.0
            facebook_marketing = assumptions.facebook_marketing_monthly_year3 if holiday_marketing_active else 0.0
            content_creation = assumptions.content_creation_monthly_year3 if holiday_marketing_active else 0.0
            team_size = assumptions.team_size_year3
        sales_marketing_cost = round(
            instagram_marketing
            + twitter_marketing
            + facebook_marketing
            + content_creation,
            2,
        )
        software_tools_cost = round(
            team_size * assumptions.software_tools_per_team_member_monthly_usd,
            2,
        )
        incorporation_cost = assumptions.incorporation_setup_usd if offset == 0 else 0.0
        non_payroll_overhead_cost = round(
            software_tools_cost + incorporation_cost,
            2,
        )
        total_expenses = round(
            total_cloud_cost + sales_marketing_cost + non_payroll_overhead_cost,
            2,
        )
        helper_total_cloud_ref = f"K{helper_index}"
        technology_opex_values.append(total_cloud_cost)
        sales_marketing_opex_values.append(sales_marketing_cost)
        g_and_a_opex_values.append(non_payroll_overhead_cost)
        total_opex_values.append(total_expenses)
        expense_summary_rows.append(
            [
                Cell.string(month_text),
                Cell.number(year_index),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=f"D{detail_index}",
                    cached_value=total_cloud_cost,
                ),
                Cell.formula_number(
                    formula=f"E{detail_index}",
                    cached_value=sales_marketing_cost,
                ),
                Cell.formula_number(
                    formula=f"G{detail_index}",
                    cached_value=non_payroll_overhead_cost,
                ),
                Cell.formula_number(
                    formula=f"H{detail_index}",
                    cached_value=total_expenses,
                ),
            ]
        )
        expense_detail_rows.append(
            [
                Cell.string(month_text),
                Cell.number(year_index),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=helper_total_cloud_ref,
                    cached_value=total_cloud_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"IF(OR(MID($A{detail_index},6,2)=\"11\",MID($A{detail_index},6,2)=\"12\"),"
                        f"IF(B{detail_index}=1,{expenses_refs['instagram_marketing_monthly_year1']},"
                        f"IF(B{detail_index}=2,{expenses_refs['instagram_marketing_monthly_year2']},"
                        f"{expenses_refs['instagram_marketing_monthly_year3']})),0)+"
                        f"IF(OR(MID($A{detail_index},6,2)=\"11\",MID($A{detail_index},6,2)=\"12\"),"
                        f"IF(B{detail_index}=1,{expenses_refs['twitter_marketing_monthly_year1']},"
                        f"IF(B{detail_index}=2,{expenses_refs['twitter_marketing_monthly_year2']},"
                        f"{expenses_refs['twitter_marketing_monthly_year3']})),0)+"
                        f"IF(OR(MID($A{detail_index},6,2)=\"11\",MID($A{detail_index},6,2)=\"12\"),"
                        f"IF(B{detail_index}=1,{expenses_refs['facebook_marketing_monthly_year1']},"
                        f"IF(B{detail_index}=2,{expenses_refs['facebook_marketing_monthly_year2']},"
                        f"{expenses_refs['facebook_marketing_monthly_year3']})),0)+"
                        f"IF(OR(MID($A{detail_index},6,2)=\"11\",MID($A{detail_index},6,2)=\"12\"),"
                        f"IF(B{detail_index}=1,{expenses_refs['content_creation_monthly_year1']},"
                        f"IF(B{detail_index}=2,{expenses_refs['content_creation_monthly_year2']},"
                        f"{expenses_refs['content_creation_monthly_year3']})),0)"
                    ),
                    cached_value=sales_marketing_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND((IF(B{detail_index}=1,{expenses_refs['team_size_year1']},"
                        f"IF(B{detail_index}=2,{expenses_refs['team_size_year2']},"
                        f"{expenses_refs['team_size_year3']})))*"
                        f"{expenses_refs['software_tools_per_team_member_monthly_usd']},2)"
                    ),
                    cached_value=software_tools_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND(F{detail_index}+{expenses_refs['incorporation_setup_usd']},2)"
                        if offset == 0
                        else f"ROUND(F{detail_index},2)"
                    ),
                    cached_value=non_payroll_overhead_cost,
                ),
                Cell.formula_number(
                    formula=f"ROUND(D{detail_index}+E{detail_index}+G{detail_index},2)",
                    cached_value=total_expenses,
                ),
            ]
        )

    expense_sheet_rows = expenses_preamble + [expense_summary_header]
    expense_sheet_rows.extend(expense_summary_rows)
    expense_sheet_rows.append([Cell.string("") for _ in range(7)])
    expense_sheet_rows.append([
        Cell.string("[Expense Detail]"),
        Cell.string(""),
        Cell.string("Underlying operating-expense detail that rolls up into the PE-style summary table above."),
    ])
    expense_sheet_rows.append(expense_detail_header)
    expense_sheet_rows.extend(expense_detail_rows)
    expense_sheet_rows.append([Cell.string("") for _ in range(8)])
    expense_sheet_rows.extend(expenses_cloud_preamble)
    expense_sheet_rows.append([
        Cell.string("[Cloud Cost Factors]"),
        Cell.string(""),
        Cell.string("Extra cloud-cost breakdown used for model transparency. It is implementation detail and is not needed in finance reports."),
    ])
    expense_sheet_rows.append([
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("object_storage_costs"),
        Cell.string("database_costs"),
        Cell.string("cloudflare_costs"),
        Cell.string("scraper_proxy_cost_usd"),
        Cell.string("transactional_email_cost_usd"),
        Cell.string("cloud_compute_costs"),
        Cell.string("cloud_storage_costs"),
        Cell.string("total_cloud_costs"),
    ])
    cumulative_new_users = 0.0
    for offset, row in enumerate(mau_rows):
        helper_index = expenses_helper_data_start + offset
        month_text = str(row["month"])
        year_index = int(row["year_index"])
        mau = float(row["mau"])
        new_users = float(row["new_users"])
        pageviews = float(ad_rows[offset]["pageviews"])
        cumulative_new_users += new_users
        if mau >= assumptions.postgres_medium_mau_threshold:
            primary_compute_cost = assumptions.postgres_medium_compute_monthly_usd
        elif mau >= assumptions.postgres_small_mau_threshold:
            primary_compute_cost = assumptions.postgres_small_compute_monthly_usd
        else:
            primary_compute_cost = assumptions.postgres_micro_compute_monthly_usd
        replica_compute_cost = (
            primary_compute_cost
            if mau >= assumptions.postgres_read_replica_mau_threshold
            else 0.0
        )
        r2_storage_gb = assumptions.r2_storage_start_gb + cumulative_new_users * (
            (assumptions.r2_storage_target_end_gb - assumptions.r2_storage_start_gb)
            / expense_total_new_users
        )
        r2_storage_cost = round(
            max(0.0, r2_storage_gb - assumptions.r2_storage_free_gb)
            * assumptions.r2_storage_price_per_gb_month,
            2,
        )
        r2_operation_cost = round(
            (new_users * assumptions.r2_class_a_ops_per_new_user / 1_000_000)
            * assumptions.r2_class_a_price_per_million
            + (pageviews * assumptions.r2_class_b_ops_per_pageview / 1_000_000)
            * assumptions.r2_class_b_price_per_million,
            2,
        )
        postgres_compute_cost = round(
            assumptions.postgres_base_plan_monthly_usd + primary_compute_cost,
            2,
        )
        postgres_disk_gb = assumptions.postgres_disk_base_gb + (
            cumulative_new_users / 1000
        ) * assumptions.postgres_disk_gb_per_1000_cumulative_new_users
        postgres_disk_cost = round(
            max(0.0, postgres_disk_gb - assumptions.postgres_disk_base_gb)
            * assumptions.postgres_disk_price_per_gb_month,
            2,
        )
        postgres_cost = round(
            postgres_compute_cost + postgres_disk_cost + replica_compute_cost,
            2,
        )
        workers_requests_millions = round(
            (
                pageviews * assumptions.workers_requests_per_pageview
                + new_users * assumptions.workers_requests_per_new_user
            )
            / 1_000_000,
            4,
        )
        workers_cpu_million_ms = round(
            workers_requests_millions * assumptions.workers_avg_cpu_ms_per_request,
            4,
        )
        workers_cost = round(
            assumptions.workers_base_monthly_usd
            + max(
                0.0,
                workers_requests_millions
                - assumptions.workers_included_requests_millions,
            )
            * assumptions.workers_request_price_per_million
            + max(
                0.0,
                workers_cpu_million_ms - assumptions.workers_included_cpu_million_ms,
            )
            * assumptions.workers_cpu_price_per_million_ms,
            2,
        )
        cloudflare_cost = round(
            assumptions.cloudflare_pages_monthly_usd + workers_cost,
            2,
        )
        transactional_email_cost = round(
            assumptions.transactional_email_monthly_usd,
            2,
        )
        object_storage_cost = round(r2_storage_cost + r2_operation_cost, 2)
        database_cost = round(postgres_cost, 2)
        cloud_storage_cost = round(r2_storage_cost + postgres_disk_cost, 2)
        cloud_compute_cost = round(
            r2_operation_cost
            + postgres_compute_cost
            + replica_compute_cost
            + cloudflare_cost
            + assumptions.scraper_proxy_monthly_usd
            + transactional_email_cost,
            2,
        )
        total_cloud_cost = round(cloud_compute_cost + cloud_storage_cost, 2)
        expense_sheet_rows.append(
            [
                Cell.string(month_text),
                Cell.number(year_index),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=(
                        f"ROUND(MAX(0,("
                        f"{expenses_cloud_refs['r2_storage_start_gb']}+"
                        f"SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + offset})*"
                        f"(({expenses_cloud_refs['r2_storage_target_end_gb']}-{expenses_cloud_refs['r2_storage_start_gb']})/"
                        f"MAX(1,SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + projection_months - 1})))"
                        f")-{expenses_cloud_refs['r2_storage_free_gb']})*{expenses_cloud_refs['r2_storage_price_per_gb_month']}+"
                        f"('{SHEET_MAU}'!$D${mau_data_start + offset}*{expenses_cloud_refs['r2_class_a_ops_per_new_user']}/1000000)*{expenses_cloud_refs['r2_class_a_price_per_million']}+"
                        f"('{SHEET_ADS}'!$G${ads_data_start + offset}*{expenses_cloud_refs['r2_class_b_ops_per_pageview']}/1000000)*{expenses_cloud_refs['r2_class_b_price_per_million']},2)"
                    ),
                    cached_value=object_storage_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND(("
                        f"{expenses_cloud_refs['postgres_base_plan_monthly_usd']}+"
                        f"IF('{SHEET_MAU}'!$F${mau_data_start + offset}>={expenses_cloud_refs['postgres_medium_mau_threshold']},"
                        f"{expenses_cloud_refs['postgres_medium_compute_monthly_usd']},"
                        f"IF('{SHEET_MAU}'!$F${mau_data_start + offset}>={expenses_cloud_refs['postgres_small_mau_threshold']},"
                        f"{expenses_cloud_refs['postgres_small_compute_monthly_usd']},"
                        f"{expenses_cloud_refs['postgres_micro_compute_monthly_usd']})))+"
                        f"MAX(0,("
                        f"{expenses_cloud_refs['postgres_disk_base_gb']}+"
                        f"SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + offset})/1000*{expenses_cloud_refs['postgres_disk_gb_per_1000_cumulative_new_users']}"
                        f")-{expenses_cloud_refs['postgres_disk_base_gb']})*{expenses_cloud_refs['postgres_disk_price_per_gb_month']}+"
                        f"IF('{SHEET_MAU}'!$F${mau_data_start + offset}>={expenses_cloud_refs['postgres_read_replica_mau_threshold']},"
                        f"IF('{SHEET_MAU}'!$F${mau_data_start + offset}>={expenses_cloud_refs['postgres_medium_mau_threshold']},"
                        f"{expenses_cloud_refs['postgres_medium_compute_monthly_usd']},"
                        f"IF('{SHEET_MAU}'!$F${mau_data_start + offset}>={expenses_cloud_refs['postgres_small_mau_threshold']},"
                        f"{expenses_cloud_refs['postgres_small_compute_monthly_usd']},"
                        f"{expenses_cloud_refs['postgres_micro_compute_monthly_usd']})),0),2)"
                    ),
                    cached_value=database_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND({expenses_cloud_refs['cloudflare_pages_monthly_usd']}+"
                        f"ROUND({expenses_cloud_refs['workers_base_monthly_usd']}+"
                        f"MAX(0,(('{SHEET_ADS}'!$G${ads_data_start + offset}*{expenses_cloud_refs['workers_requests_per_pageview']}+"
                        f"'{SHEET_MAU}'!$D${mau_data_start + offset}*{expenses_cloud_refs['workers_requests_per_new_user']})/1000000)-{expenses_cloud_refs['workers_included_requests_millions']})*"
                        f"{expenses_cloud_refs['workers_request_price_per_million']}+"
                        f"MAX(0,(((('{SHEET_ADS}'!$G${ads_data_start + offset}*{expenses_cloud_refs['workers_requests_per_pageview']}+"
                        f"'{SHEET_MAU}'!$D${mau_data_start + offset}*{expenses_cloud_refs['workers_requests_per_new_user']})/1000000)*{expenses_cloud_refs['workers_avg_cpu_ms_per_request']})-"
                        f"{expenses_cloud_refs['workers_included_cpu_million_ms']}))*{expenses_cloud_refs['workers_cpu_price_per_million_ms']},2),2)"
                    ),
                    cached_value=cloudflare_cost,
                ),
                Cell.formula_number(
                    formula=expenses_cloud_refs["scraper_proxy_monthly_usd"],
                    cached_value=float(assumptions.scraper_proxy_monthly_usd),
                ),
                Cell.formula_number(
                    formula=expenses_cloud_refs["transactional_email_monthly_usd"],
                    cached_value=transactional_email_cost,
                ),
                Cell.formula_number(
                    formula=f"ROUND(D{helper_index}+E{helper_index}+F{helper_index}+G{helper_index}+H{helper_index}-J{helper_index},2)",
                    cached_value=cloud_compute_cost,
                ),
                Cell.formula_number(
                    formula=(
                        f"ROUND(MAX(0,("
                        f"{expenses_cloud_refs['r2_storage_start_gb']}+"
                        f"SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + offset})*"
                        f"(({expenses_cloud_refs['r2_storage_target_end_gb']}-{expenses_cloud_refs['r2_storage_start_gb']})/"
                        f"MAX(1,SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + projection_months - 1})))"
                        f")-{expenses_cloud_refs['r2_storage_free_gb']})*{expenses_cloud_refs['r2_storage_price_per_gb_month']}+"
                        f"MAX(0,("
                        f"{expenses_cloud_refs['postgres_disk_base_gb']}+"
                        f"SUM('{SHEET_MAU}'!$D${mau_data_start}:'{SHEET_MAU}'!$D${mau_data_start + offset})/1000*{expenses_cloud_refs['postgres_disk_gb_per_1000_cumulative_new_users']}"
                        f")-{expenses_cloud_refs['postgres_disk_base_gb']})*{expenses_cloud_refs['postgres_disk_price_per_gb_month']},2)"
                    ),
                    cached_value=cloud_storage_cost,
                ),
                Cell.formula_number(
                    formula=f"ROUND(I{helper_index}+J{helper_index},2)",
                    cached_value=total_cloud_cost,
                ),
            ]
        )
    summary_month_dates = [date.fromisoformat(str(row["month"])) for row in marketplace_fee_rows]
    summary_year_labels: list[Cell] = [Cell.string("")]
    prior_year: int | None = None
    for month_date in summary_month_dates:
        year_label = str(month_date.year) if month_date.year != prior_year else ""
        summary_year_labels.append(Cell.string(year_label))
        prior_year = month_date.year
    summary_month_labels = [Cell.string("month")] + [Cell.number(month_date.month) for month_date in summary_month_dates]
    marketplace_revenue_values = [float(row["transaction_fee_revenue_usd"]) for row in marketplace_fee_rows]
    subscription_revenue_values = [float(row["subscription_revenue_usd"]) for row in subscription_rows]
    advertising_revenue_values = [float(row["ad_revenue_usd"]) for row in ad_rows]
    total_revenue_values = [
        round(marketplace_revenue_values[i] + subscription_revenue_values[i] + advertising_revenue_values[i], 2)
        for i in range(projection_months)
    ]
    operating_profit_values = [
        round(total_revenue_values[i] - total_opex_values[i], 2)
        for i in range(projection_months)
    ]

    summary_rows: list[list[Cell]] = [
        [
            Cell.string("[Summary]"),
            Cell.string(""),
            Cell.string("36-month income statement style summary driven by the detailed revenue and OpEx tabs."),
        ],
        [Cell.string("")],
        summary_year_labels,
        summary_month_labels,
    ]
    summary_marketplace_row = 5
    summary_subscription_row = 6
    summary_advertising_row = 7
    summary_total_revenue_row = 8
    summary_technology_opex_row = 10
    summary_sales_marketing_opex_row = 11
    summary_g_and_a_opex_row = 12
    summary_total_opex_row = 13
    summary_operating_profit_row = 14

    def _summary_formula_row(
        label: str,
        row_number: int,
        formulas: list[str],
        cached_values: list[float],
    ) -> list[Cell]:
        row_cells: list[Cell] = [Cell.string(label)]
        for formula, cached_value in zip(formulas, cached_values):
            row_cells.append(Cell.formula_number(formula=formula, cached_value=cached_value))
        return row_cells

    marketplace_formulas = [
        f"'{SHEET_MARKETPLACE_FEES}'!$I${marketplace_data_start + offset}"
        for offset in range(projection_months)
    ]
    subscription_formulas = [
        f"'{SHEET_SUBSCRIPTIONS}'!$L${subscriptions_data_start + offset}"
        for offset in range(projection_months)
    ]
    advertising_formulas = [
        f"'{SHEET_ADS}'!$L${ads_data_start + offset}"
        for offset in range(projection_months)
    ]
    technology_opex_formulas = [
        f"'{SHEET_EXPENSES}'!$D${expenses_summary_data_start + offset}"
        for offset in range(projection_months)
    ]
    sales_marketing_opex_formulas = [
        f"'{SHEET_EXPENSES}'!$E${expenses_summary_data_start + offset}"
        for offset in range(projection_months)
    ]
    g_and_a_opex_formulas = [
        f"'{SHEET_EXPENSES}'!$F${expenses_summary_data_start + offset}"
        for offset in range(projection_months)
    ]
    total_opex_formulas = [
        f"'{SHEET_EXPENSES}'!$G${expenses_summary_data_start + offset}"
        for offset in range(projection_months)
    ]
    total_revenue_formulas = [
        f"ROUND(SUM({_cell_ref(month_col, summary_marketplace_row)}:{_cell_ref(month_col, summary_advertising_row)}),2)"
        for month_col in range(2, projection_months + 2)
    ]
    operating_profit_formulas = [
        f"ROUND({_cell_ref(month_col, summary_total_revenue_row)}-{_cell_ref(month_col, summary_total_opex_row)},2)"
        for month_col in range(2, projection_months + 2)
    ]

    summary_rows.append(_summary_formula_row("Marketplace Revenue", summary_marketplace_row, marketplace_formulas, marketplace_revenue_values))
    summary_rows.append(_summary_formula_row("Subscription Revenue", summary_subscription_row, subscription_formulas, subscription_revenue_values))
    summary_rows.append(_summary_formula_row("Advertising Revenue", summary_advertising_row, advertising_formulas, advertising_revenue_values))
    summary_rows.append(_summary_formula_row("Total Revenue", summary_total_revenue_row, total_revenue_formulas, total_revenue_values))
    summary_rows.append([Cell.string("")])
    summary_rows.append(_summary_formula_row("Technology & Infrastructure OpEx", summary_technology_opex_row, technology_opex_formulas, technology_opex_values))
    summary_rows.append(_summary_formula_row("Sales & Marketing OpEx", summary_sales_marketing_opex_row, sales_marketing_opex_formulas, sales_marketing_opex_values))
    summary_rows.append(_summary_formula_row("G&A OpEx", summary_g_and_a_opex_row, g_and_a_opex_formulas, g_and_a_opex_values))
    summary_rows.append(_summary_formula_row("Total Operating Expenses", summary_total_opex_row, total_opex_formulas, total_opex_values))
    summary_rows.append(_summary_formula_row("Operating Profit / (Loss)", summary_operating_profit_row, operating_profit_formulas, operating_profit_values))

    sheets = [
        Sheet(SHEET_SUMMARY, summary_rows),
        Sheet(SHEET_MARKETPLACE_FEES, marketplace_rows),
        Sheet(SHEET_MAU, mau_sheet_rows),
        Sheet(SHEET_SUBSCRIPTIONS, subscription_sheet_rows),
        Sheet(SHEET_ADS, ad_sheet_rows),
        Sheet(SHEET_EXPENSES, expense_sheet_rows),
    ]

    temp_output_path = output_path.with_name(f".{output_path.name}.tmp")
    if temp_output_path.exists():
        temp_output_path.unlink()

    with ZipFile(temp_output_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("docProps/core.xml", _core_xml())
        archive.writestr("docProps/app.xml", _app_xml([sheet.name for sheet in sheets]))
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))

    temp_output_path.replace(output_path)


def read_projection_sheet_rows(path: Path, sheet_name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"projection workbook not found: {path}")

    with ZipFile(path, "r") as archive:
        workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
        workbook_rels_xml = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in workbook_rels_xml.findall(f"{{{NS_PACKAGE}}}Relationship")
        }

        worksheet_target = None
        for sheet in workbook_xml.findall(f"{{{NS_MAIN}}}sheets/{{{NS_MAIN}}}sheet"):
            if sheet.attrib.get("name") == sheet_name:
                rel_id = sheet.attrib.get(f"{{{NS_REL}}}id")
                worksheet_target = rel_targets.get(rel_id or "")
                break
        if not worksheet_target:
            raise ValueError(f"sheet not found in workbook: {sheet_name}")

        worksheet_xml = ET.fromstring(archive.read(f"xl/{worksheet_target}"))

    rows_by_index: dict[int, dict[int, str]] = {}
    for row in worksheet_xml.findall(f"{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row"):
        row_number = int(row.attrib["r"])
        cell_map: dict[int, str] = {}
        for cell in row.findall(f"{{{NS_MAIN}}}c"):
            ref = cell.attrib.get("r", "")
            column_index = _column_index(ref)
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "inlineStr":
                text_node = cell.find(f"{{{NS_MAIN}}}is/{{{NS_MAIN}}}t")
                value = text_node.text if text_node is not None and text_node.text is not None else ""
            else:
                value_node = cell.find(f"{{{NS_MAIN}}}v")
                value = value_node.text if value_node is not None and value_node.text is not None else ""
            cell_map[column_index] = value
        rows_by_index[row_number] = cell_map

    header_row_number = next(
        (
            row_number
            for row_number in sorted(rows_by_index.keys())
            if rows_by_index[row_number].get(1, "") == "month"
        ),
        1,
    )
    header_cells = rows_by_index.get(header_row_number, {})
    headers = {
        column_index: value
        for column_index, value in header_cells.items()
        if value
    }
    output: list[dict[str, str]] = []
    for row_number in sorted(number for number in rows_by_index.keys() if number > header_row_number):
        row_cells = rows_by_index[row_number]
        record = {
            header: row_cells.get(column_index, "")
            for column_index, header in headers.items()
        }
        if not any(value != "" for value in record.values()):
            if output:
                break
            continue
        if row_cells.get(1, "") == "month":
            break
        output.append(record)
    return output
