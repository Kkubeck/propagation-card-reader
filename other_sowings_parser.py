"""Parser for multi-sowing table sections on propagation card fronts.

Many older cards have an "OTHER SOWINGS" or "OTHER / SOWN / GERM" section
listing additional sowing trials for the same taxon, each with a different
accession. These are sparse records: accession, qty, sow date, location,
treatment, germ date, germ qty — whatever the card writer fit on the line.

Two VLM output formats:
1. Pipe-delimited (newer VLM transcription): "OTHER | QTY | SOWN | ..."
2. Freeform inline (older cards): "OTHER SOWN GERM\n accession date loc ..."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional, Sequence


# --- Section detection ---

OTHER_HEADER_RE = re.compile(
    r'(?:^|\n)\s*'
    r'(?:OTHER\s+SOWINGS|OTHER\s*\||other\s+sown|Other\s+#|Other\s+Qty|OTHER\s+(?:#\s+OF\s+SEED\s+)?SOWN)',
    re.IGNORECASE | re.MULTILINE,
)

# --- Field patterns ---

ACCESSION_RE = re.compile(
    r'(?:\d{4,6}[-/]\d{2,4}[-/]\d{2,4})'
    r'|(?:(?:19|20)\d{2}[-/]\d{4,5})'
)

DATE_RE = re.compile(
    r'(?:[A-Z][a-z]{2,8}\.?\s*\d{1,2}[-,.]?\s*\d{2,4})'
    r'|(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
    r'|(?:[A-Z][a-z]{2,8}\.?\s+\d{4})'
    r"|(?:[A-Z][a-z]{2,8}\.?\s+'\d{2})",
    re.IGNORECASE,
)

QTY_PAREN_RE = re.compile(r'\((\d+)\)')

LOCATION_TERMS = {
    'PSH', 'PHS', 'PHN', 'PSHT', 'PSA', 'PSF',
    'GH', 'GHSE', 'GLHSE', 'GLSHSE', 'GREENHOUSE', 'GRASSHOUSE',
    'COLDFRAME', 'COLDFRM', 'CLDFRM', 'COLD FRAME',
    'FRIDGE', 'INSIDE', 'MIST',
}

LOCATION_RE = re.compile(
    r'\b(' + '|'.join(sorted(LOCATION_TERMS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

OUTCOME_RE = re.compile(
    r'(?:FAIL(?:ED)?\s+TO\s+GERM(?:INATE)?|DISCARDED|DAMPED?\s+OFF|DIED)',
    re.IGNORECASE,
)

PIPE_HEADER_RE = re.compile(
    r'OTHER\s*\|.*(?:SOWN|QTY|GERM)',
    re.IGNORECASE,
)

SEPARATOR_RE = re.compile(r'^[-=|+\s]+$')


@dataclass
class SowingRecord:
    """One sowing trial from the OTHER section."""
    accession: Optional[str] = None
    qty_sown: Optional[str] = None
    date_sown: Optional[str] = None
    location: Optional[str] = None
    treatment: Optional[str] = None
    date_germ: Optional[str] = None
    qty_germ: Optional[str] = None
    outcome: Optional[str] = None
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def has_data(self) -> bool:
        return any([self.accession, self.date_sown, self.date_germ, self.outcome])


@dataclass
class OtherSowingsResult:
    """Result of parsing an OTHER SOWINGS section."""
    records: list[SowingRecord] = None
    format: str = "unknown"
    raw_section: str = ""

    def __post_init__(self):
        if self.records is None:
            self.records = []

    def to_dict(self) -> dict:
        return {
            "records": [r.to_dict() for r in self.records],
            "format": self.format,
            "record_count": len(self.records),
        }


def has_other_sowings(text: str) -> bool:
    """Quick check for an OTHER SOWINGS section."""
    if not text:
        return False
    return bool(OTHER_HEADER_RE.search(text))


def _extract_other_section(text: str) -> str:
    """Extract the OTHER section from full propagation text."""
    m = OTHER_HEADER_RE.search(text)
    if not m:
        return ""
    return text[m.start():].strip()


def _parse_pipe_table(section: str) -> OtherSowingsResult:
    """Parse pipe-delimited OTHER table."""
    lines = [l.strip() for l in section.split('\n') if l.strip()]
    if not lines:
        return OtherSowingsResult(raw_section=section)

    # Parse header to build column map
    header = lines[0]
    header_cells = [c.strip().lower() for c in header.split('|')]
    col_map = {}
    qty_seen = False
    for i, cell in enumerate(header_cells):
        cell = cell.strip()
        if cell in ('other', 'accession', 'acc', 'acc.'):
            col_map[i] = 'accession'
        elif cell in ('qty', 'qty.', 'quantity', '#', '# of seed', '# of seeds', 'no.'):
            if not qty_seen:
                col_map[i] = 'qty_sown'
                qty_seen = True
            else:
                col_map[i] = 'qty_germ'
        elif cell in ('sown', 'date sown', 'sowing', 'down'):
            col_map[i] = 'date_sown'
        elif cell in ('treatment', 'treatments', 'trt', 'where'):
            col_map[i] = 'treatment'
        elif cell in ('germ', 'germ.', 'germination', 'g.'):
            col_map[i] = 'date_germ'

    records = []
    for line in lines[1:]:
        if SEPARATOR_RE.fullmatch(line):
            continue
        cells = [c.strip() for c in line.split('|')]
        rec = SowingRecord(raw_text=line)
        for i, cell in enumerate(cells):
            if not cell:
                continue
            field = col_map.get(i)
            if field == 'accession':
                rec.accession = cell
            elif field == 'qty_sown':
                rec.qty_sown = cell
            elif field == 'qty_germ':
                rec.qty_germ = cell
            elif field == 'date_sown':
                rec.date_sown = cell
            elif field == 'treatment':
                rec.treatment = cell
            elif field == 'date_germ':
                rec.date_germ = cell

        # Detect outcome in any cell
        full = ' '.join(cells)
        om = OUTCOME_RE.search(full)
        if om:
            rec.outcome = om.group(0).strip()

        if rec.has_data():
            records.append(rec)

    return OtherSowingsResult(records=records, format="pipe_delimited", raw_section=section)


def _parse_freeform_row(line: str) -> SowingRecord:
    """Parse a single freeform row from the OTHER section."""
    rec = SowingRecord(raw_text=line)

    # Extract accession first (anchors the row)
    acc_match = ACCESSION_RE.search(line)
    if acc_match:
        rec.accession = acc_match.group(0)

    # Extract outcome
    om = OUTCOME_RE.search(line)
    if om:
        rec.outcome = om.group(0).strip()

    # Extract location
    loc = LOCATION_RE.search(line)
    if loc:
        rec.location = loc.group(1).upper()

    # Extract dates — first is sow, second is germ
    dates = DATE_RE.findall(line)
    if dates:
        rec.date_sown = dates[0]
    if len(dates) >= 2:
        rec.date_germ = dates[1]

    # Extract quantities in parentheses
    qtys = QTY_PAREN_RE.findall(line)
    if qtys:
        rec.qty_sown = qtys[0]
    if len(qtys) >= 2:
        rec.qty_germ = qtys[1]

    # Bare trailing number as germ qty (e.g., "... APR 6-90 3")
    if not rec.qty_germ:
        trailing = re.search(r'\s(\d{1,3})\s*$', line)
        if trailing and not DATE_RE.search(trailing.group(0)):
            rec.qty_germ = trailing.group(1)

    return rec


def _parse_freeform(section: str) -> OtherSowingsResult:
    """Parse freeform OTHER section (no pipes)."""
    # Strip the header line
    lines = section.split('\n')
    header_line = lines[0] if lines else ''
    data_text = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ''

    # If header and data are on the same line (common for single-row tables)
    if not data_text:
        # Everything after the header keywords is the data
        m = re.search(
            r'(?:OTHER\s+SOWINGS\s+SOWN|OTHER\s+SOWN\s+(?:\(\d+\)\s*)?(?:GERM\.?\s*(?:QTY)?)?|other\s+sown\s+(?:germ\.?\s*)?(?:qty\s*)?|Other\s+#\s+Sown\s+Germ\s+#)',
            header_line, re.IGNORECASE
        )
        if m:
            data_text = header_line[m.end():].strip()
        else:
            data_text = re.sub(r'^OTHER\s+', '', header_line, flags=re.IGNORECASE).strip()

    if not data_text:
        return OtherSowingsResult(raw_section=section, format="freeform")

    # Split into rows — each accession number starts a new row,
    # or each line break does
    data_lines = [l.strip() for l in data_text.split('\n') if l.strip()]

    # If it's a single long line, try splitting on accession boundaries
    if len(data_lines) == 1 and len(data_lines[0]) > 40:
        single = data_lines[0]
        # Split before each accession pattern (but not the first one if it starts the line)
        parts = ACCESSION_RE.split(single)
        accs = ACCESSION_RE.findall(single)
        if len(accs) >= 2:
            data_lines = []
            for i, acc in enumerate(accs):
                remainder = parts[i + 1] if i + 1 < len(parts) else ''
                data_lines.append(f"{acc} {remainder}".strip())
        elif not accs:
            # No accessions — treat whole thing as one record
            data_lines = [single]

    records = []
    for line in data_lines:
        if not line or SEPARATOR_RE.fullmatch(line):
            continue
        # Skip lines that are just header repeats
        if re.fullmatch(r'(?:OTHER|SOWN|GERM|QTY|#|---)+[\s|]*', line, re.IGNORECASE):
            continue
        rec = _parse_freeform_row(line)
        if rec.has_data():
            records.append(rec)

    return OtherSowingsResult(records=records, format="freeform", raw_section=section)


def parse_other_sowings(text: str) -> OtherSowingsResult:
    """Parse the OTHER SOWINGS section from propagation text.

    Extracts the section, detects format (pipe vs freeform), and
    returns structured sowing records.
    """
    if not text:
        return OtherSowingsResult()

    section = _extract_other_section(text)
    if not section:
        return OtherSowingsResult()

    if PIPE_HEADER_RE.match(section):
        return _parse_pipe_table(section)

    return _parse_freeform(section)
