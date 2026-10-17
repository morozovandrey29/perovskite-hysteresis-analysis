"""Minimal XLSX export helpers (no pandas/openpyxl dependency)."""
from __future__ import annotations

import zipfile
import numpy as np

# Minimal dependency-free XLSX writer for result export
# ---------------------------------------------------------------------------


def _xlsx_col_name(n: int) -> str:
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _xml_escape(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _xlsx_cell(ref: str, value, style: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return ""
        return f'<c r="{ref}" s="{style}"><v>{float(value):.15g}</v></c>'
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{int(value)}</v></c>'
    if isinstance(value, bool):
        return f'<c r="{ref}" s="{style}" t="b"><v>{1 if value else 0}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(value)}</t></is></c>'


def _xlsx_sheet_xml(rows: list[list], freeze_header: bool = True) -> str:
    max_cols = max((len(row) for row in rows), default=1)
    max_rows = max(len(rows), 1)
    cols = []
    for c in range(max_cols):
        vals = [str(row[c]) for row in rows if c < len(row) and row[c] not in (None, "")]
        width = min(max(11, max((len(v) for v in vals), default=11) + 2), 34)
        cols.append(f'<col min="{c+1}" max="{c+1}" width="{width}" customWidth="1"/>')

    row_xml = []
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, value in enumerate(row):
            if value is None or value == "":
                continue
            cells.append(_xlsx_cell(f"{_xlsx_col_name(c_idx)}{r_idx}", value, 1 if r_idx == 1 else 0))
        row_xml.append(f'<row r="{r_idx}">' + "".join(cells) + '</row>')

    views = '<sheetViews><sheetView workbookViewId="0">'
    if freeze_header:
        views += '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
    views += '</sheetView></sheetViews>'
    auto_filter = f'<autoFilter ref="A1:{_xlsx_col_name(max_cols-1)}{max_rows}"/>' if max_rows > 1 else ''
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{_xlsx_col_name(max_cols-1)}{max_rows}"/>'
        + views + '<cols>' + "".join(cols) + '</cols>'
        + '<sheetData>' + "".join(row_xml) + '</sheetData>' + auto_filter
        + '</worksheet>'
    )


def write_simple_xlsx(path: str, sheets: dict[str, list[list]]):
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for i in range(1, len(sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append('</Types>')

    sheet_nodes, rel_nodes = [], []
    for i, name in enumerate(sheets, 1):
        sheet_nodes.append(f'<sheet name="{_xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
        rel_nodes.append(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )
    rel_nodes.append(
        f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>' + "".join(sheet_nodes) + '</sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rel_nodes) + '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAF7"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyFont="1" applyFill="1"/></cellXfs>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', "".join(content_types))
        zf.writestr('_rels/.rels', root_rels)
        zf.writestr('xl/workbook.xml', workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        zf.writestr('xl/styles.xml', styles_xml)
        for i, rows in enumerate(sheets.values(), 1):
            zf.writestr(f'xl/worksheets/sheet{i}.xml', _xlsx_sheet_xml(rows))


