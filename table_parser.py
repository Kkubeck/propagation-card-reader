"""Parser for tabular card-back propagation data.

Duplex card backs often contain a hand-drawn table with columns:
    OTHER | # OF SEED | SOWN | TREATMENT | GERM | QTY

This module parses VLM-transcribed table text into structured row dicts.
Handles pipe-delimited, whitespace-aligned, and free-form row layouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence


KNOWN_HEADERS = {
    "other", "accession", "acc", "acc.",
    "qty", "quantity", "#", "# of seed", "seed", "no.",
    "sown", "sowing", "date sown", "down",
    "treatment", "trt", "trt.",
    "germ", "germination", "germ.", "g.",
    "location", "loc", "loc.",
}

COLUMN_ALIASES = {
    "other": "accession",
    "acc": "accession",
    "acc.": "accession",
    "accession": "accession",
    "#": "qty_sown",
    "# of seed": "qty_sown",
    "seed": "qty_sown",
    "no.": "qty_sown",
    "qty": "qty",
    "quantity": "qty",
    "sown": "date_sown",
    "sowing": "date_sown",
    "date sown": "date_sown",
    "down": "date_sown",
    "treatment": "treatment",
    "trt": "treatment",
    "trt.": "treatment",
    "germ": "date_germ",
    "germination": "date_germ",
    "germ.": "date_germ",
    "g.": "date_germ",
    "location": "location",
    "loc": "location",
    "loc.": "location",
}


ACCESSION_RE = re.compile(
    r"(?:\d{4,6}[-/]\d{2,4}[-/]\d{2,4})"
    r"|(?:(?:19|20)\d{2}[-/]\d{4,5})"
    r"|(?:\d{4,6}[-/]\d{3,4})"
)

DATE_RE = re.compile(
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    r"|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}[,.]?\s*\d{2,4})"
    r"|(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*[,.]?\s*\d{2,4})"
    r"|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})"
    r"|(?:(?:Spring|Summer|Fall|Autumn|Winter)\s+\d{4})",
    re.IGNORECASE,
)


@dataclass
class TableRow:
    """One row from a card-back propagation table."""
    accession: Optional[str] = None
    qty_sown: Optional[str] = None
    date_sown: Optional[str] = None
    treatment: Optional[str] = None
    date_germ: Optional[str] = None
    qty_germ: Optional[str] = None
    location: Optional[str] = None
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def has_data(self) -> bool:
        return any([self.accession, self.date_sown, self.date_germ,
                     self.treatment, self.qty_sown, self.qty_germ])


@dataclass
class ParseResult:
    """Result of parsing a card-back table."""
    rows: list[TableRow] = field(default_factory=list)
    headers_detected: list[str] = field(default_factory=list)
    format: str = "unknown"
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "headers_detected": self.headers_detected,
            "format": self.format,
            "row_count": len(self.rows),
        }


def _is_header_line(line: str) -> bool:
    """Check if a line looks like column headers."""
    lower = line.lower().strip()
    if not lower:
        return False
    tokens = re.split(r'\s*\|\s*', lower) if '|' in lower else re.split(r'\s{2,}', lower)
    tokens = [t.strip() for t in tokens if t.strip()]
    if len(tokens) < 2:
        return False
    header_count = sum(1 for t in tokens if t in KNOWN_HEADERS)
    return header_count >= 2


def _detect_column_map(header_line: str) -> dict[int, str]:
    """Map column positions to field names from a header line."""
    if '|' in header_line:
        tokens = re.split(r'\s*\|\s*', header_line)
    else:
        tokens = re.split(r'\s{2,}', header_line)

    col_map = {}
    qty_seen = False
    for i, token in enumerate(tokens):
        key = token.strip().lower()
        if key in COLUMN_ALIASES:
            mapped = COLUMN_ALIASES[key]
            if mapped == "qty":
                if not qty_seen:
                    col_map[i] = "qty_sown"
                    qty_seen = True
                else:
                    col_map[i] = "qty_germ"
            else:
                col_map[i] = mapped
    return col_map


def _split_row_cells(line: str, use_pipes: bool) -> list[str]:
    """Split a data row into cells."""
    if use_pipes:
        return [c.strip() for c in re.split(r'\s*\|\s*', line)]
    return [c.strip() for c in re.split(r'\s{2,}', line)]


def _guess_field(value: str) -> Optional[str]:
    """Guess what field a cell value represents based on content."""
    v = value.strip()
    if not v:
        return None
    if ACCESSION_RE.fullmatch(v):
        return "accession"
    if DATE_RE.search(v) and len(v) < 30:
        return "date"
    if re.fullmatch(r'\d{1,4}', v):
        return "qty"
    return "text"


def _build_row_from_cells(cells: list[str], col_map: dict[int, str]) -> TableRow:
    """Build a TableRow from cells using the column map."""
    row = TableRow(raw_text=" | ".join(cells))
    for i, cell in enumerate(cells):
        cell = cell.strip()
        if not cell:
            continue
        field_name = col_map.get(i)
        if field_name == "accession":
            row.accession = cell
        elif field_name == "qty_sown":
            row.qty_sown = cell
        elif field_name == "qty_germ":
            row.qty_germ = cell
        elif field_name == "date_sown":
            row.date_sown = cell
        elif field_name == "treatment":
            row.treatment = cell
        elif field_name == "date_germ":
            row.date_germ = cell
        elif field_name == "location":
            row.location = cell
    return row


def _build_row_heuristic(cells: list[str]) -> TableRow:
    """Build a TableRow by guessing field types from cell content."""
    row = TableRow(raw_text=" | ".join(cells))
    dates_found = []
    qtys_found = []

    for cell in cells:
        cell = cell.strip()
        if not cell:
            continue
        if ACCESSION_RE.search(cell) and row.accession is None:
            row.accession = cell
        elif DATE_RE.search(cell) and len(cell) < 30:
            dates_found.append(cell)
        elif re.fullmatch(r'\d{1,4}', cell):
            qtys_found.append(cell)
        elif len(cell) > 5 and row.treatment is None:
            row.treatment = cell
        elif row.location is None and cell.upper() in (
            "PSH", "PHS", "PHN", "GH", "GREENHOUSE", "COLDFRAME",
            "COLD FRAME", "FRIDGE", "MIST", "POLY SHADEHOUSE",
        ):
            row.location = cell

    if len(dates_found) >= 1:
        row.date_sown = dates_found[0]
    if len(dates_found) >= 2:
        row.date_germ = dates_found[1]
    if len(qtys_found) >= 1:
        row.qty_sown = qtys_found[0]
    if len(qtys_found) >= 2:
        row.qty_germ = qtys_found[1]

    return row


def parse_table_text(text: str) -> ParseResult:
    """Parse VLM-transcribed table text into structured rows.

    Handles three formats:
    1. Pipe-delimited (OTHER | QTY | SOWN | ...)
    2. Whitespace-aligned (columns separated by 2+ spaces)
    3. Free-form rows (one row per line, field detection by content)
    """
    if not text or not text.strip():
        return ParseResult(raw_text=text or "")

    lines = [l for l in text.strip().split('\n') if l.strip()]
    if not lines:
        return ParseResult(raw_text=text)

    use_pipes = any('|' in l for l in lines)
    has_headers = _is_header_line(lines[0])
    col_map: dict[int, str] = {}
    data_lines = lines
    headers_detected: list[str] = []

    if has_headers:
        col_map = _detect_column_map(lines[0])
        headers_detected = list(col_map.values())
        data_lines = lines[1:]
        fmt = "pipe_delimited" if use_pipes else "space_aligned"
    elif use_pipes:
        fmt = "pipe_delimited_no_header"
    else:
        fmt = "freeform"

    rows: list[TableRow] = []

    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_header_line(stripped):
            continue
        if re.fullmatch(r'[-=|+\s]+', stripped):
            continue

        cells = _split_row_cells(stripped, use_pipes)

        if col_map:
            row = _build_row_from_cells(cells, col_map)
        else:
            row = _build_row_heuristic(cells)

        if row.has_data():
            rows.append(row)

    return ParseResult(
        rows=rows,
        headers_detected=headers_detected,
        format=fmt,
        raw_text=text,
    )


def is_table_text(text: str) -> bool:
    """Quick check whether text looks like a tabular card back."""
    if not text:
        return False
    lines = text.strip().split('\n')
    if len(lines) < 2:
        return False
    pipe_lines = sum(1 for l in lines if '|' in l)
    if pipe_lines >= 2:
        return True
    if _is_header_line(lines[0]):
        return True
    multi_space_lines = sum(1 for l in lines if re.search(r'\S\s{2,}\S', l))
    return multi_space_lines >= 2
