"""Input parsing for XLSX/CSV frequency-dependent hysteresis datasets."""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"main": NS_MAIN, "r": NS_REL, "pr": NS_PKG_REL}


def _col_letters_to_index(col_letters: str) -> int:
    n = 0
    for ch in col_letters.upper():
        if not ("A" <= ch <= "Z"):
            continue
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _cell_ref_to_col(cell_ref: str) -> int:
    m = re.match(r"([A-Z]+)", cell_ref.upper())
    return _col_letters_to_index(m.group(1)) if m else 0


def _parse_number(text: str):
    if text is None:
        return None
    s = str(text).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return s


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("main:si", NS):
        texts = [t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")]
        out.append("".join(texts))
    return out


def _xlsx_sheet_map(zf: zipfile.ZipFile) -> dict[str, str]:
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels = {}
    for rel in rel_root.findall("pr:Relationship", NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target
        rels[rid] = path
    result = {}
    sheets_el = wb_root.find("main:sheets", NS)
    if sheets_el is None:
        return result
    for sh in sheets_el.findall("main:sheet", NS):
        name = sh.attrib.get("name", "")
        rid = sh.attrib.get(f"{{{NS_REL}}}id")
        if name and rid in rels:
            result[name] = rels[rid]
    return result


def _read_xlsx_sheet(zf: zipfile.ZipFile, sheet_path: str, shared: list[str]) -> list[list]:
    root = ET.fromstring(zf.read(sheet_path))
    sheet_data = root.find("main:sheetData", NS)
    if sheet_data is None:
        return []

    rows = []
    for row_el in sheet_data.findall("main:row", NS):
        row = {}
        max_col = -1
        for c in row_el.findall("main:c", NS):
            ref = c.attrib.get("r", "")
            col = _cell_ref_to_col(ref)
            max_col = max(max_col, col)
            cell_type = c.attrib.get("t")
            value = ""

            if cell_type == "inlineStr":
                is_el = c.find("main:is", NS)
                if is_el is not None:
                    value = "".join(t.text or "" for t in is_el.iter(f"{{{NS_MAIN}}}t"))
            else:
                v_el = c.find("main:v", NS)
                raw = v_el.text if v_el is not None else ""
                if cell_type == "s":
                    try:
                        value = shared[int(raw)]
                    except Exception:
                        value = raw
                elif cell_type == "b":
                    value = bool(int(raw or 0))
                else:
                    value = _parse_number(raw)
            row[col] = value

        width = max_col + 1 if max_col >= 0 else 0
        values = [""] * width
        for col, value in row.items():
            values[col] = value
        rows.append(values)

    return rows


def read_xlsx(path: str) -> dict[str, list[list]]:
    with zipfile.ZipFile(path, "r") as zf:
        shared = _xlsx_shared_strings(zf)
        sheets = _xlsx_sheet_map(zf)
        return {name: _read_xlsx_sheet(zf, p, shared) for name, p in sheets.items()}


def read_csv(path: str) -> list[list]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(raw), dialect)]


# ---------------------------------------------------------------------------
# Data parsing
# ---------------------------------------------------------------------------

FREQ_RE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*(m?Hz|kHz|hz)", re.I)


def parse_frequency(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float, np.number)) and np.isfinite(value):
        f = float(value)
        return f if f > 0 else None
    s = str(value).strip().replace(",", ".")
    m = FREQ_RE.search(s)
    if not m:
        try:
            f = float(s)
            return f if f > 0 else None
        except ValueError:
            return None
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "mhz":
        return number / 1000.0
    if unit == "khz":
        return number * 1000.0
    return number


def normalize_header(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).strip().lower())


def find_header_index(headers: list, candidates: Iterable[str]) -> Optional[int]:
    normalized = [normalize_header(h) for h in headers]
    candidates_n = [normalize_header(c) for c in candidates]
    for cand in candidates_n:
        if cand in normalized:
            return normalized.index(cand)
    # fallback: substring matching
    for i, h in enumerate(normalized):
        if any(c in h or h in c for c in candidates_n if c):
            return i
    return None




@dataclass
class FrequencyDataset:
    """Measurements for one device, sorted by ascending frequency."""
    device: str
    frequency_hz: np.ndarray
    hyst_area: np.ndarray


def extract_datasets(sheets: dict[str, list[list]], input_config: dict | None = None) -> list[FrequencyDataset]:
    """Extract per-device datasets from workbook sheets or a parsed CSV.

    Column aliases and the preferred sheet name can be changed in config.json.
    Duplicate frequencies are merged using their median value.
    """
    cfg = input_config or {}
    preferred = normalize_header(cfg.get("preferred_sheet_name", "Analysis Results"))
    frequency_columns = cfg.get("frequency_columns", ["Frequency", "Freq", "Frequency (Hz)"])
    area_columns = cfg.get("hysteresis_area_columns", ["Hyst_Area", "Hyst Area", "Hysteresis Area", "HystArea"])
    device_columns = cfg.get("device_columns", ["Device", "Cell", "Sample", "Element"])
    candidate_sheet_names = sorted(sheets, key=lambda s: (0 if normalize_header(s) == preferred else 1, s.lower()))
    best_error = None
    for sheet_name in candidate_sheet_names:
        rows = sheets[sheet_name]
        if not rows:
            continue
        headers = rows[0]
        fi = find_header_index(headers, frequency_columns)
        hi = find_header_index(headers, area_columns)
        di = find_header_index(headers, device_columns)
        if fi is None or hi is None:
            continue
        by_device: dict[str, list[tuple[float, float]]] = {}
        for row in rows[1:]:
            try:
                f = parse_frequency(row[fi] if fi < len(row) else None)
                y_raw = row[hi] if hi < len(row) else None
                y = float(str(y_raw).replace(",", "."))
                if f is None or not np.isfinite(y):
                    continue
            except (TypeError, ValueError, IndexError):
                continue
            device = str(row[di]).strip() if di is not None and di < len(row) and str(row[di]).strip() else sheet_name
            by_device.setdefault(device, []).append((f, y))
        if by_device:
            datasets = []
            for dev, pairs in by_device.items():
                merged: dict[float, list[float]] = {}
                for f, y in pairs:
                    merged.setdefault(float(f), []).append(float(y))
                ff = np.array(sorted(merged), dtype=float)
                yy = np.array([float(np.median(merged[f])) for f in ff], dtype=float)
                if len(ff) >= 3:
                    datasets.append(FrequencyDataset(dev, ff, yy))
            if datasets:
                return sorted(datasets, key=lambda d: d.device)
        best_error = f"Sheet '{sheet_name}' contains the expected headers but not enough valid data."
    raise ValueError(
        "No valid data found. Expected columns corresponding to Device, Frequency, and Hyst_Area. "
        + (best_error or "Check the input file and column names.")
    )


def load_file(path: str | Path, input_config: dict | None = None) -> list[FrequencyDataset]:
    """Load datasets from an Excel workbook (.xlsx) or CSV/TXT file."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        sheets = read_xlsx(str(path))
    elif ext in {".csv", ".txt"}:
        sheets = {path.stem: read_csv(str(path))}
    else:
        raise ValueError("Supported input formats are .xlsx, .csv, and .txt")
    return extract_datasets(sheets, input_config)
