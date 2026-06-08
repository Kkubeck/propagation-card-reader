"""Parser for multi-replicate propagation cards.

Modern cards (~2010+) often test multiple treatments on the same taxon:
outdoor natural cold stratification (PSH sowing) vs artificial (fridge).
This module detects and splits replicate blocks from narrative text.

Three narrative patterns:
1. Circled numbers: ①②③ delimit treatment arms
2. Numbered pots/trays: "1 Seed pot - PSH / 1 Seed pot - CS in fridge"
3. Numbered items: "Tray #1 ... Tray #2 ..."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence


# --- Detection patterns ---

CIRCLED_NUM_RE = re.compile(r'[①②③④⑤⑥⑦⑧⑨⑩]')
CIRCLED_MAP = {c: i + 1 for i, c in enumerate('①②③④⑤⑥⑦⑧⑨⑩')}

POT_DECL_RE = re.compile(
    r'(?:[A-Z]{3,9}\.?\s+\d{1,2}[,.]?\s*\d{2,4}\s+)?'  # optional leading date
    r'(\d+)\s+'
    r'(?:seed\s+)?(?:pot|pots)\s*'
    r'(?:\(([^)]+)\)\s*)?'  # optional "(30 seeds)"
    r'[-–—]\s*'
    r'(.+?)'  # non-greedy treatment
    r'(?=\s+\d+\s+(?:seed\s+)?(?:pot|pots)\b|$)',  # stop before next pot decl or end
    re.IGNORECASE,
)

# Broader split to find pot declarations on single lines
POT_SPLIT_RE = re.compile(
    r'(\d+\s+(?:seed\s+)?(?:pot|pots)\s*(?:\([^)]+\)\s*)?[-–—])',
    re.IGNORECASE,
)

TRAY_RE = re.compile(r'Tray\s*#?\s*(\d+)', re.IGNORECASE)

LOCATION_TERMS_ORDERED = [
    'PSHT', 'PSH', 'PHS', 'PHN', 'PSA', 'GH', 'GREENHOUSE',
    'COLDFRAME', 'COLD FRAME', 'FRIDGE', 'MIST', 'POLY SHADEHOUSE',
]
LOCATION_TERMS = set(LOCATION_TERMS_ORDERED)

TREATMENT_SIGNALS = re.compile(
    r'\b(?:cs|cold\s+strat|fridge|natural|artificial|outdoor|indoor'
    r'|water\s+pit|sphagnum|warm|room\s+temp)\b',
    re.IGNORECASE,
)

GERM_RE = re.compile(
    r'(?:G\.?\s|Germ\.?\s|Germinated\s)\s*'
    r'([A-Z][a-z]{2,8}\.?\s+\d{1,2}[,.]?\s*\d{2,4}'
    r'|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
    re.IGNORECASE,
)

QTY_GERM_RE = re.compile(
    r'(?:G\.?\s|Germ\.?\s)\s*[^(]*\((\d+)\)'
    r'|\((\d+)\)\s*seedlings?'
    r'|\((\d+)\s+seedlings?\)',
    re.IGNORECASE,
)


def _qty_germ_from_match(m: re.Match) -> str:
    return m.group(1) or m.group(2) or m.group(3)

DATE_LINE_RE = re.compile(
    r'^(?:[A-Z]{3,9}\.?\s+\d{1,2}[,.]?\s*\d{2,4}'
    r'|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}'
    r'|[JFMASOND][a-z]{2,8}\s+\d{4})',
    re.IGNORECASE,
)


@dataclass
class Replicate:
    """One treatment arm from a multi-replicate card."""
    replicate_id: int = 0
    treatment: Optional[str] = None
    location: Optional[str] = None
    qty_sown: Optional[str] = None
    date_sown: Optional[str] = None
    date_germ: Optional[str] = None
    qty_germ: Optional[str] = None
    raw_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['raw_text'] = '\n'.join(self.raw_lines)
        del d['raw_lines']
        return d

    def has_data(self) -> bool:
        return any([self.treatment, self.location, self.date_sown,
                     self.date_germ, self.qty_sown, self.qty_germ])


@dataclass
class ReplicateResult:
    """Result of parsing a multi-replicate card."""
    replicates: list[Replicate] = field(default_factory=list)
    shared_lines: list[str] = field(default_factory=list)
    format: str = "unknown"
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "replicates": [r.to_dict() for r in self.replicates],
            "shared_lines": self.shared_lines,
            "format": self.format,
            "replicate_count": len(self.replicates),
        }


def is_multi_replicate(text: str) -> bool:
    """Quick check whether text contains multi-replicate signals."""
    if not text:
        return False
    if CIRCLED_NUM_RE.search(text):
        return True
    # Check across all lines (handles single-line multi-pot cases)
    all_lines = [l.strip() for l in text.split('\n') if l.strip()]
    total_pot_matches = sum(
        len(POT_DECL_RE.findall(line)) for line in all_lines
    )
    if total_pot_matches >= 2:
        return True
    tray_matches = TRAY_RE.findall(text)
    if len(tray_matches) >= 2:
        return True
    return False


def _parse_circled(text: str) -> ReplicateResult:
    """Parse text delimited by circled numbers ①②③."""
    parts = re.split(r'([①②③④⑤⑥⑦⑧⑨⑩])', text)

    replicates: list[Replicate] = []
    shared_lines: list[str] = []
    current_rep: Optional[Replicate] = None

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in CIRCLED_MAP:
            if current_rep and current_rep.has_data():
                replicates.append(current_rep)
            current_rep = Replicate(replicate_id=CIRCLED_MAP[part])
            continue
        if current_rep is not None:
            lines = [l.strip() for l in part.split('\n') if l.strip()]
            current_rep.raw_lines.extend(lines)
            _extract_fields_from_lines(current_rep, lines)
        else:
            for line in part.split('\n'):
                if line.strip():
                    shared_lines.append(line.strip())

    if current_rep and current_rep.has_data():
        replicates.append(current_rep)

    return ReplicateResult(
        replicates=replicates,
        shared_lines=shared_lines,
        format="circled_numbers",
        raw_text=text,
    )


def _expand_inline_pots(lines: list[str]) -> list[str]:
    """Split single lines containing multiple pot declarations into separate lines."""
    expanded = []
    for line in lines:
        # Count pot declarations on this line
        pot_positions = [m.start() for m in POT_DECL_RE.finditer(line)]
        if len(pot_positions) >= 2:
            # Split at each pot declaration boundary
            parts = []
            for i, pos in enumerate(pot_positions):
                end = pot_positions[i + 1] if i + 1 < len(pot_positions) else len(line)
                parts.append(line[pos:end].strip())
            # Preserve any leading date before first pot
            if pot_positions[0] > 0:
                prefix = line[:pot_positions[0]].strip()
                if prefix:
                    expanded.append(prefix)
            expanded.extend(parts)
        else:
            expanded.append(line)
    return expanded


def _parse_pot_declarations(text: str) -> ReplicateResult:
    """Parse text with numbered pot declarations."""
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _expand_inline_pots(raw_lines)
    replicates: list[Replicate] = []
    shared_lines: list[str] = []
    current_date: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for date line that applies to following declarations
        date_match = DATE_LINE_RE.match(line)
        pot_match = POT_DECL_RE.match(line)

        if pot_match:
            rep_id = len(replicates) + 1
            qty_raw = pot_match.group(2)
            treatment_raw = pot_match.group(3).strip()

            rep = Replicate(replicate_id=rep_id)
            rep.raw_lines.append(line)
            if qty_raw:
                qty_num = re.search(r'(\d+)', qty_raw)
                if qty_num:
                    rep.qty_sown = qty_num.group(1)
            if current_date:
                rep.date_sown = current_date

            _classify_treatment_location(rep, treatment_raw)
            replicates.append(rep)

        elif date_match and not replicates:
            current_date = line
            shared_lines.append(line)
        else:
            # Try to attribute outcome lines to replicates
            if replicates:
                _try_attribute_outcome(replicates, line)
            shared_lines.append(line)

        i += 1

    return ReplicateResult(
        replicates=replicates,
        shared_lines=shared_lines,
        format="pot_declarations",
        raw_text=text,
    )


def _parse_tray_numbered(text: str) -> ReplicateResult:
    """Parse text with numbered trays."""
    parts = re.split(r'(Tray\s*#?\s*\d+)', text, flags=re.IGNORECASE)
    replicates: list[Replicate] = []
    shared_lines: list[str] = []

    current_rep: Optional[Replicate] = None

    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue
        tray_match = TRAY_RE.match(part_stripped)
        if tray_match:
            if current_rep and current_rep.has_data():
                replicates.append(current_rep)
            current_rep = Replicate(replicate_id=int(tray_match.group(1)))
            continue
        if current_rep is not None:
            # Content following a "Tray #N" marker — may be inline or multiline
            combined = part_stripped
            lines = [l.strip() for l in combined.split('\n') if l.strip()]
            current_rep.raw_lines.extend(lines)
            _extract_fields_from_lines(current_rep, lines)
        else:
            for line in part.split('\n'):
                if line.strip():
                    shared_lines.append(line.strip())

    if current_rep and current_rep.has_data():
        replicates.append(current_rep)

    return ReplicateResult(
        replicates=replicates,
        shared_lines=shared_lines,
        format="tray_numbered",
        raw_text=text,
    )


def _clean_treatment_text(raw: str) -> str:
    """Trim treatment text at outcome/date boundaries."""
    # Stop at germination markers, transplant notes, or new date lines
    for pattern in [
        r'\s*[-–—]?\s*(?:G\.|Germ\.?|C\.)\s',
        r'\s+[A-Z]{3,9}\s+\d{1,2}[,.]?\s+\d{4}\b',  # "JAN 21 2011"
        r'\s+(?:March|April|May|June|July|Aug|Sept?|Oct|Nov|Dec)\s+\d{4}\b',
    ]:
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            raw = raw[:m.start()]
    # Strip trailing parens with just a number like "(7)" or "(1)."
    raw = re.sub(r'\s*\(\d+\s*(?:sd|seeds?)?\)\.?\s*$', '', raw, flags=re.IGNORECASE)
    raw = raw.rstrip('. ')
    return raw.strip()


def _classify_treatment_location(rep: Replicate, raw: str):
    """Split a treatment string into location and treatment components."""
    upper = raw.upper().strip()
    # Strip trailing germ/outcome markers like "G. Feb 28, 2012 (24)"
    germ_match = GERM_RE.search(raw)
    if germ_match:
        rep.date_germ = germ_match.group(1)
    qty_match = QTY_GERM_RE.search(raw)
    if qty_match:
        rep.qty_germ = _qty_germ_from_match(qty_match)

    # Check for known location at start (longest match first)
    for loc in LOCATION_TERMS_ORDERED:
        if upper.startswith(loc):
            rep.location = loc
            remainder = _clean_treatment_text(
                raw[len(loc):].strip().lstrip('-–—').strip()
            )
            if remainder and not remainder.startswith(('G.', 'C.')):
                rep.treatment = remainder
            return

    # Location might be embedded (longest match first)
    for loc in LOCATION_TERMS_ORDERED:
        if loc in upper:
            rep.location = loc

    cleaned = _clean_treatment_text(raw)
    if cleaned and TREATMENT_SIGNALS.search(cleaned):
        rep.treatment = cleaned
    elif cleaned and not rep.location:
        rep.treatment = cleaned


def _extract_fields_from_lines(rep: Replicate, lines: list[str]):
    """Extract treatment, location, dates, quantities from free-text lines."""
    for line in lines:
        if not rep.treatment and TREATMENT_SIGNALS.search(line):
            rep.treatment = line

        for loc in LOCATION_TERMS:
            if loc in line.upper() and not rep.location:
                rep.location = loc

        germ = GERM_RE.search(line)
        if germ and not rep.date_germ:
            rep.date_germ = germ.group(1)

        qty = QTY_GERM_RE.search(line)
        if qty and not rep.qty_germ:
            rep.qty_germ = _qty_germ_from_match(qty)

        sown_match = re.search(
            r'(?:Sown|SOW[NE]D?)\s*'
            r'([A-Z][a-z]{2,8}\.?\s+\d{1,2}[,.]?\s*\d{2,4}'
            r'|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            line, re.IGNORECASE
        )
        if sown_match and not rep.date_sown:
            rep.date_sown = sown_match.group(1)


def _try_attribute_outcome(replicates: list[Replicate], line: str):
    """Try to attribute an outcome line to one of the replicates."""
    germ = GERM_RE.search(line)
    qty = QTY_GERM_RE.search(line)

    if not germ and not qty:
        return

    # If only one replicate lacks germ data, attribute to it
    ungerminated = [r for r in replicates if not r.date_germ]
    if germ and len(ungerminated) == 1:
        ungerminated[0].date_germ = germ.group(1)
        ungerminated[0].raw_lines.append(line)
    if qty:
        no_qty = [r for r in replicates if not r.qty_germ]
        if len(no_qty) == 1:
            no_qty[0].qty_germ = _qty_germ_from_match(qty)


def parse_replicates(text: str) -> ReplicateResult:
    """Parse multi-replicate propagation text into separate treatment arms.

    Detects format automatically:
    1. Circled numbers (①②③)
    2. Pot declarations ("1 Seed pot - PSH")
    3. Tray numbers ("Tray #1")
    """
    if not text or not text.strip():
        return ReplicateResult(raw_text=text or "")

    if CIRCLED_NUM_RE.search(text):
        return _parse_circled(text)

    all_lines = [l.strip() for l in text.split('\n') if l.strip()]
    total_pot_matches = sum(
        len(POT_DECL_RE.findall(line)) for line in all_lines
    )
    if total_pot_matches >= 2:
        return _parse_pot_declarations(text)

    tray_matches = TRAY_RE.findall(text)
    if len(tray_matches) >= 2:
        return _parse_tray_numbered(text)

    return ReplicateResult(raw_text=text)
