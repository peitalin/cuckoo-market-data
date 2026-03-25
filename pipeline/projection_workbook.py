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

SHEET_ASSUMPTIONS = "Assumptions"
SHEET_SEASONALITY = "Seasonality"
SHEET_DRIVERS = "Drivers"
SHEET_MARKETPLACE_FEES = "MarketplaceFees"
SHEET_MAU = "MAU"
SHEET_SUBSCRIPTIONS = "Subscriptions"
SHEET_ADS = "Ads"

ASSUMPTION_REFS = {
    "projection_months": "B2",
    "projection_start_month": "B3",
    "seasonality_lookback_years": "B4",
    "sales_cagr": "B5",
    "jitter_std": "B6",
    "take_rate": "B7",
    "year2_3_min_txns": "B8",
    "year2_3_max_txns": "B9",
    "subscription_price_usd": "B10",
    "mau_start": "B11",
    "mau_end": "B12",
    "subscription_conversion_start": "B13",
    "subscription_conversion_end": "B14",
    "subscription_retention_start": "B15",
    "subscription_retention_end": "B16",
    "ad_action_rate": "B17",
    "ad_cpa_usd": "B18",
    "seed": "B19",
    "baseline_month": "B20",
    "baseline_month_gmv_usd": "B21",
    "baseline_month_transaction_count": "B22",
    "baseline_month_asp_usd": "B23",
    "baseline_month_factor": "B24",
    "mau_sigmoid_steepness": "B25",
    "mau_sigmoid_lower": "B26",
    "mau_sigmoid_upper": "B27",
}


def _assumption_ref(key: str) -> str:
    return f"'{SHEET_ASSUMPTIONS}'!${ASSUMPTION_REFS[key][0]}${ASSUMPTION_REFS[key][1:]}"


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
    mau_rows: list[dict[str, Any]],
    subscription_rows: list[dict[str, Any]],
    ad_rows: list[dict[str, Any]],
    market_driver_rows: list[dict[str, float]],
    mau_driver_rows: list[dict[str, float]],
    ad_driver_rows: list[dict[str, float]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_asp = baseline_gmv_usd / max(1, baseline_transaction_count)
    steepness = 7.5
    sigmoid_lower = 1.0 / (1.0 + pow(2.718281828459045, steepness / 2.0))
    sigmoid_upper = 1.0 / (1.0 + pow(2.718281828459045, -steepness / 2.0))

    assumptions_rows = [
        [Cell.string("name"), Cell.string("value")],
        [Cell.string("projection_months"), Cell.number(assumptions.projection_months)],
        [Cell.string("projection_start_month"), Cell.string(assumptions.projection_start_month)],
        [Cell.string("seasonality_lookback_years"), Cell.number(assumptions.seasonality_lookback_years)],
        [Cell.string("sales_cagr"), Cell.number(assumptions.sales_cagr)],
        [Cell.string("jitter_std"), Cell.number(assumptions.jitter_std)],
        [Cell.string("take_rate"), Cell.number(assumptions.take_rate)],
        [Cell.string("year2_3_min_txns"), Cell.number(assumptions.year2_3_min_txns)],
        [Cell.string("year2_3_max_txns"), Cell.number(assumptions.year2_3_max_txns)],
        [Cell.string("subscription_price_usd"), Cell.number(assumptions.subscription_price_usd)],
        [Cell.string("mau_start"), Cell.number(assumptions.mau_start)],
        [Cell.string("mau_end"), Cell.number(assumptions.mau_end)],
        [Cell.string("subscription_conversion_start"), Cell.number(assumptions.subscription_conversion_start)],
        [Cell.string("subscription_conversion_end"), Cell.number(assumptions.subscription_conversion_end)],
        [Cell.string("subscription_retention_start"), Cell.number(assumptions.subscription_retention_start)],
        [Cell.string("subscription_retention_end"), Cell.number(assumptions.subscription_retention_end)],
        [Cell.string("ad_action_rate"), Cell.number(assumptions.ad_action_rate)],
        [Cell.string("ad_cpa_usd"), Cell.number(assumptions.ad_cpa_usd)],
        [Cell.string("seed"), Cell.number(assumptions.seed)],
        [Cell.string("baseline_month"), Cell.string(baseline_month.isoformat())],
        [Cell.string("baseline_month_gmv_usd"), Cell.number(round(baseline_gmv_usd, 2))],
        [Cell.string("baseline_month_transaction_count"), Cell.number(baseline_transaction_count)],
        [Cell.string("baseline_month_asp_usd"), Cell.number(round(baseline_asp, 2))],
        [Cell.string("baseline_month_factor"), Cell.number(monthly_factors[baseline_month.month])],
        [Cell.string("mau_sigmoid_steepness"), Cell.number(steepness)],
        [Cell.string("mau_sigmoid_lower"), Cell.number(sigmoid_lower)],
        [Cell.string("mau_sigmoid_upper"), Cell.number(sigmoid_upper)],
    ]

    seasonality_rows = [[Cell.string("month"), Cell.string("blended_factor")]]
    for month in range(1, 13):
        seasonality_rows.append([Cell.number(month), Cell.number(monthly_factors[month])])

    drivers_rows = [[
        Cell.string("month"),
        Cell.string("market_year1_jitter_multiplier"),
        Cell.string("market_txn_noise"),
        Cell.string("market_asp_noise"),
        Cell.string("mau_noise"),
        Cell.string("ad_noise"),
    ]]
    for index, row in enumerate(marketplace_fee_rows):
        drivers_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(market_driver_rows[index]["year1_jitter_multiplier"]),
                Cell.number(market_driver_rows[index]["txn_noise"]),
                Cell.number(market_driver_rows[index]["asp_noise"]),
                Cell.number(mau_driver_rows[index]["mau_noise"]),
                Cell.number(ad_driver_rows[index]["ad_noise"]),
            ]
        )

    marketplace_rows = [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("seasonality_factor"),
        Cell.string("cagr_multiplier"),
        Cell.string("jitter_multiplier"),
        Cell.string("transaction_count"),
        Cell.string("gross_market_value_usd"),
        Cell.string("actual_sales_price_usd"),
        Cell.string("take_rate"),
        Cell.string("transaction_fee_revenue_usd"),
    ]]
    for index, row in enumerate(marketplace_fee_rows, start=2):
        year_ref = f"$B{index}"
        seasonality_ref = f"D{index}"
        cagr_ref = f"E{index}"
        txns_ref = f"G{index}"
        asp_ref = f"I{index}"
        gmv_ref = f"H{index}"
        take_rate_ref = f"J{index}"
        progress_offset = index - 2
        projection_offset = progress_offset - 12
        marketplace_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=f"INDEX('{SHEET_SEASONALITY}'!$B$2:$B$13,VALUE(MID($A{index},6,2)))",
                    cached_value=float(row["seasonality_factor"]),
                ),
                Cell.formula_number(
                    formula=f"IF({year_ref}=1,1,POWER(1+{_assumption_ref('sales_cagr')},{projection_offset}/12))",
                    cached_value=float(row["cagr_multiplier"]),
                ),
                Cell.formula_number(
                    formula=f"IF({year_ref}=1,'{SHEET_DRIVERS}'!$B{index},'{SHEET_DRIVERS}'!$C{index}*'{SHEET_DRIVERS}'!$D{index})",
                    cached_value=float(row["jitter_multiplier"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,0,"
                        f"MIN({_assumption_ref('year2_3_max_txns')},"
                        f"MAX({_assumption_ref('year2_3_min_txns')},"
                        f"ROUND(("
                        f"{_assumption_ref('year2_3_min_txns')}+"
                        f"({_assumption_ref('year2_3_max_txns')}-{_assumption_ref('year2_3_min_txns')})*({projection_offset}/23)"
                        f")*(0.85+0.15*({seasonality_ref}/{_assumption_ref('baseline_month_factor')}))*"
                        f"'{SHEET_DRIVERS}'!$C{index},0))))"
                    ),
                    cached_value=float(row["transaction_count"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND({txns_ref}*{asp_ref},2)",
                    cached_value=float(row["gross_market_value_usd"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"IF({year_ref}=1,0,"
                        f"ROUND({_assumption_ref('baseline_month_asp_usd')}*"
                        f"(0.9+0.1*({seasonality_ref}/{_assumption_ref('baseline_month_factor')}))*"
                        f"POWER(1+({_assumption_ref('sales_cagr')}*0.35),{projection_offset}/12)*"
                        f"'{SHEET_DRIVERS}'!$D{index},2))"
                    ),
                    cached_value=float(row["actual_sales_price_usd"]),
                ),
                Cell.formula_number(
                    formula=_assumption_ref("take_rate"),
                    cached_value=float(row["take_rate"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(IF({txns_ref}>0,{gmv_ref}*{take_rate_ref},0),2)",
                    cached_value=float(row["transaction_fee_revenue_usd"]),
                ),
            ]
        )

    mau_sheet_rows = [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("mau"),
        Cell.string("subscription_conversion_rate"),
        Cell.string("subscription_retention_rate"),
        Cell.string("new_subscribers"),
        Cell.string("churned_subscribers"),
        Cell.string("active_subscribers"),
    ]]
    for index, row in enumerate(mau_rows, start=2):
        progress = f"({index}-2)/({_assumption_ref('projection_months')}-1)"
        prior_active = f"IF(ROW()=2,0,I{index - 1})"
        retained = f"({prior_active}*F{index})"
        mau_formula = (
            f"ROUND(MAX(100,("
            f"{_assumption_ref('mau_start')}+({_assumption_ref('mau_end')}-{_assumption_ref('mau_start')})*"
            f"((1/(1+EXP(-{_assumption_ref('mau_sigmoid_steepness')}*({progress}-0.5)))-"
            f"{_assumption_ref('mau_sigmoid_lower')})/"
            f"({_assumption_ref('mau_sigmoid_upper')}-{_assumption_ref('mau_sigmoid_lower')})))"
            f"*(0.92+0.08*INDEX('{SHEET_SEASONALITY}'!$B$2:$B$13,VALUE(MID($A{index},6,2))))*"
            f"'{SHEET_DRIVERS}'!$E{index}),0)"
        )
        mau_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(mau_formula, float(row["mau"])),
                Cell.formula_number(
                    formula=(
                        f"{_assumption_ref('subscription_conversion_start')}+"
                        f"({_assumption_ref('subscription_conversion_end')}-{_assumption_ref('subscription_conversion_start')})*{progress}"
                    ),
                    cached_value=float(row["subscription_conversion_rate"]),
                ),
                Cell.formula_number(
                    formula=(
                        f"{_assumption_ref('subscription_retention_start')}+"
                        f"({_assumption_ref('subscription_retention_end')}-{_assumption_ref('subscription_retention_start')})*{progress}"
                    ),
                    cached_value=float(row["subscription_retention_rate"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX(0,I{index}-{retained}),0)",
                    cached_value=float(row["new_subscribers"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX(0,{prior_active}-{retained}),0)",
                    cached_value=float(row["churned_subscribers"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(MAX({retained},D{index}*E{index}),0)",
                    cached_value=float(row["active_subscribers"]),
                ),
            ]
        )

    subscription_sheet_rows = [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("subscription_price_usd"),
        Cell.string("subscription_revenue_usd"),
    ]]
    for index, row in enumerate(subscription_rows, start=2):
        subscription_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=_assumption_ref("subscription_price_usd"),
                    cached_value=float(row["subscription_price_usd"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND('{SHEET_MAU}'!$I{index}*D{index},2)",
                    cached_value=float(row["subscription_revenue_usd"]),
                ),
            ]
        )

    ad_sheet_rows = [[
        Cell.string("month"),
        Cell.string("year_index"),
        Cell.string("phase"),
        Cell.string("ad_action_rate"),
        Cell.string("ad_actions"),
        Cell.string("ad_cpa_usd"),
        Cell.string("ad_revenue_usd"),
    ]]
    for index, row in enumerate(ad_rows, start=2):
        progress = f"({index}-2)/({_assumption_ref('projection_months')}-1)"
        ad_sheet_rows.append(
            [
                Cell.string(str(row["month"])),
                Cell.number(int(row["year_index"])),
                Cell.string(str(row["phase"])),
                Cell.formula_number(
                    formula=(
                        f"{_assumption_ref('ad_action_rate')}*(0.75+0.5*'{SHEET_MAU}'!$F{index})*(0.95+0.1*{progress})"
                    ),
                    cached_value=float(row["ad_action_rate"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND('{SHEET_MAU}'!$D{index}*D{index}*'{SHEET_DRIVERS}'!$F{index},0)",
                    cached_value=float(row["ad_actions"]),
                ),
                Cell.formula_number(
                    formula=_assumption_ref("ad_cpa_usd"),
                    cached_value=float(row["ad_cpa_usd"]),
                ),
                Cell.formula_number(
                    formula=f"ROUND(E{index}*F{index},2)",
                    cached_value=float(row["ad_revenue_usd"]),
                ),
            ]
        )

    sheets = [
        Sheet(SHEET_ASSUMPTIONS, assumptions_rows),
        Sheet(SHEET_SEASONALITY, seasonality_rows),
        Sheet(SHEET_DRIVERS, drivers_rows),
        Sheet(SHEET_MARKETPLACE_FEES, marketplace_rows),
        Sheet(SHEET_MAU, mau_sheet_rows),
        Sheet(SHEET_SUBSCRIPTIONS, subscription_sheet_rows),
        Sheet(SHEET_ADS, ad_sheet_rows),
    ]

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("docProps/core.xml", _core_xml())
        archive.writestr("docProps/app.xml", _app_xml([sheet.name for sheet in sheets]))
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))


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

    header_cells = rows_by_index.get(1, {})
    headers = {
        column_index: value
        for column_index, value in header_cells.items()
        if value
    }
    output: list[dict[str, str]] = []
    for row_number in sorted(number for number in rows_by_index.keys() if number > 1):
        row_cells = rows_by_index[row_number]
        output.append(
            {
                header: row_cells.get(column_index, "")
                for column_index, header in headers.items()
            }
        )
    return output
