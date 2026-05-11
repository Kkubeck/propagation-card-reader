#!/usr/bin/env python3
"""Nursery lexicon correction for propagation card OCR output.

This module adds a conservative, domain-specific correction layer for the
propagation card reader. It is designed to fix obvious OCR near-misses in
highly formulaic nursery text without aggressively guessing.

Features
--------
- Small nursery/propagation lexicon (~200+ unique terms)
- Regex patterns for common card phrase shapes
- Conservative token-level fuzzy correction using only the Python stdlib
- SQLite batch application for successful extractions
- Standalone CLI for dry runs and statistics

The correction logic is intentionally cautious:
- numbers, dates, accession numbers, and mixed alphanumeric IDs are preserved
- only clear single best matches are applied
- likely botanical-name strings are left alone
"""

from __future__ import annotations

import argparse
import difflib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


LEXICON_CATEGORIES: Dict[str, Sequence[str]] = {
    "actions": [
        "sow",
        "sown",
        "sowing",
        "sowings",
        "surface sow",
        "surfacesow",
        "direct sow",
        "germ",
        "germs",
        "germination",
        "germinate",
        "germinated",
        "emergent",
        "emerged",
        "prick",
        "pricked",
        "pricked out",
        "potted",
        "potting",
        "transplant",
        "transplanted",
        "planted",
        "moved",
        "removed",
        "discarded",
        "eliminated",
        "failed",
        "dead",
        "soak",
        "soaked",
        "rooted",
        "rooting",
        "scarify",
        "scarified",
        "stratification",
        "cover",
        "covered",
        "collect",
        "collected",
        "divide",
        "divided",
        "stick",
        "stuck",
        "double stuck",
        "treated",
        "repeated",
        "punched",
        "dip",
        "wound",
        "taken",
        "using",
        "keep",
        "kept",
        "removed from",
        "moved to",
    ],
    "locations": [
        "greenhouse",
        "greenhouse 1",
        "greenhouse 2",
        "glasshouse",
        "glass house",
        "coldframe",
        "cold frame",
        "frame",
        "shadehouse",
        "poly shadehouse",
        "polyhouse",
        "poly house",
        "nursery",
        "alpine house",
        "mist bench",
        "propagation bench",
        "bench",
        "mist",
        "fridge",
        "inside",
        "indoors",
        "outside",
        "outdoors",
        "cool",
        "warm",
        "gh",
        "ph",
        "phn",
        "phs",
        "psh",
    ],
    "materials": [
        "gravel",
        "peat",
        "perlite",
        "vermiculite",
        "sand",
        "sawdust",
        "osmocote",
        "nutricote",
        "lime",
        "gypsum",
        "micromax",
        "alpine mix",
        "seedling mix",
        "alpine media",
        "alpine medium",
        "media",
        "medium",
        "mix",
        "granite",
        "grit",
        "granite grit",
        "sphagnum",
        "moss",
        "aqua",
        "water",
        "physan",
        "powder",
        "nutrient",
        "rate",
        "soil",
        "compost",
        "bark",
        "pumice",
        "charcoal",
    ],
    "plant_parts": [
        "seed",
        "seeds",
        "seedling",
        "seedlings",
        "cutting",
        "cuttings",
        "tip cutting",
        "tip cuttings",
        "tip",
        "tips",
        "scion",
        "scions",
        "bulb",
        "bulbs",
        "offset",
        "offsets",
        "rhizome",
        "rhizomes",
        "tuber",
        "tubers",
        "rootstock",
        "rootstocks",
        "propagule",
        "propagules",
        "radicle",
        "radicles",
        "foliage",
        "leaf",
        "leaves",
        "root",
        "roots",
        "stem",
        "stems",
        "node",
        "nodes",
        "bud",
        "buds",
        "stock",
        "stocks",
        "shoot",
        "shoots",
        "plant",
        "plants",
    ],
    "conditions_treatments": [
        "cold stratification",
        "warm stratification",
        "cold strat",
        "warm strat",
        "cold stock",
        "cold winter",
        "dormancy",
        "dormant",
        "scarify",
        "scarification",
        "ga3",
        "gibberellic acid",
        "bottom heat",
        "full light",
        "light",
        "lightly",
        "cover lightly",
        "cover nightly",
        "warm water",
        "cool to germ",
        "soak",
        "soaked",
        "fridge",
        "mist",
        "standard",
        "reduced",
        "single",
        "double",
        "intact",
        "wild",
        "spring",
        "dorm",
        "treatment",
        "treatments",
    ],
    "abbreviations": [
        "sdg",
        "sdgs",
        "germ",
        "g.",
        "cs",
        "cw",
        "cws",
        "dorm",
        "hr",
        "hrs",
        "sec",
        "sec.",
        "min",
        "mins",
        "cm",
        "cm.",
        "mm",
        "pl",
        "pl.",
        "fl",
        "fls",
        "fls.",
        "qty",
        "sr",
        "ws",
    ],
    "time_measurement": [
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "hour",
        "hours",
        "hr",
        "hrs",
        "minute",
        "minutes",
        "second",
        "seconds",
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
        "spring",
        "winter",
        "°c",
        "°f",
        "c",
        "f",
        "%",
    ],
    "container_terms": [
        "pot",
        "pots",
        "seed pot",
        "tray",
        "trays",
        "flat",
        "flats",
        "deepot",
        "deepots",
        "deepdot",
        "deepdots",
        "deepdop",
        "deepdops",
        "plug",
        "plugs",
        "cell",
        "cells",
        "band pot",
        "band pots",
        "bench",
    ],
    "other_context_terms": [
        "large",
        "small",
        "individual",
        "individually",
        "only",
        "nightly",
        "indoors",
        "surface",
        "alpine",
        "heat",
    ],
}


# Exact token or phrase replacements for especially common OCR slips.
EXPLICIT_REPLACEMENTS: Dict[str, str] = {
    "cermination": "germination",
    "gernination": "germination",
    "germiation": "germination",
    "gerrn": "germ",
    "gern": "germ",
    "herm": "germ",
    "soon": "sown",
    "prickled": "pricked",
    "pickled": "pricked",
    "osmosote": "osmocote",
    "osmocotee": "osmocote",
    "nutricole": "nutricote",
    "coldfrarne": "coldframe",
    "coldfrarne.": "coldframe",
    "glasthouse": "glasshouse",
    "shadehause": "shadehouse",
    "seediing": "seedling",
    "seediings": "seedlings",
    "buibs": "bulbs",
    "offsefs": "offsets",
    "scionss": "scions",
    "periite": "perlite",
    "vermicuiite": "vermiculite",
    "gibberellic": "gibberellic",
}

PHRASE_CORRECTION_RULES: Sequence[Tuple[str, str]] = [
    ("prickled out", "pricked out"),
    ("picked out", "pricked out"),
    ("germs", "germ"),
    ("cold strat", "cold stratification"),
    ("warm strat", "warm stratification"),
    ("surfacesow", "surface sow"),
    ("tip cutts", "tip cuttings"),
    ("seediings", "seedlings"),
]


DEFAULT_BASE_DIR = Path(__file__).parent
DEFAULT_LEXICON_PATH = DEFAULT_BASE_DIR / "nursery_lexicon.txt"
DEFAULT_CORRECTIONS_PATH = DEFAULT_BASE_DIR / "ocr_corrections.txt"


@dataclass
class CorrectionDetail:
    original: str
    corrected: str
    replacements: int


def _flatten_terms(categories: Dict[str, Sequence[str]]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for terms in categories.values():
        for term in terms:
            normalized = term.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
    return ordered


def _compile_phrase_normalizations(
    phrase_rules: Sequence[Tuple[str, str]]
) -> List[Tuple[re.Pattern[str], str]]:
    compiled: List[Tuple[re.Pattern[str], str]] = []
    for source, replacement in phrase_rules:
        escaped = re.escape(source.strip().lower())
        pattern = r"\b" + escaped.replace(r"\ ", r"\s+") + r"\b"
        compiled.append((re.compile(pattern, re.IGNORECASE), replacement.strip().lower()))
    return compiled


PHRASE_NORMALIZATIONS: Sequence[Tuple[re.Pattern[str], str]] = _compile_phrase_normalizations(
    PHRASE_CORRECTION_RULES
)


ALL_TERMS: List[str] = []
SINGLE_TOKEN_TERMS: List[str] = []
MULTIWORD_TERMS: List[str] = []
SINGLE_TOKEN_SET = set()
LENGTH_BUCKETS: Dict[int, List[str]] = {}
ACTIVE_EXPLICIT_REPLACEMENTS: Dict[str, str] = dict(EXPLICIT_REPLACEMENTS)
ACTIVE_PHRASE_NORMALIZATIONS: Sequence[Tuple[re.Pattern[str], str]] = list(
    PHRASE_NORMALIZATIONS
)


# Generic helpers for common card phrase shapes.
MONTH_RE = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC|JANUARY|FEBRUARY|MARCH|APRIL|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\.?(?:\s+[A-Z]+)?"
DATE_RE = (
    r"(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|"
    r"%s\s+\d{1,2}(?:[ ,./-]+\d{2,4})?"
    r"|"
    r"\d{1,2}\s+%s(?:\s+\d{2,4})?"
    r"|"
    r"%s\s+\d{4}"
    r")" % (MONTH_RE, MONTH_RE, MONTH_RE)
)
LOCATION_RE = r"(?:GREENHOUSE(?:\s+\d+)?|GLASSHOUSE|COLD\s*FRAME|COLDFRAME|SHADEHOUSE|POLY\s+SHADEHOUSE|POLYHOUSE|PHN|PHS|PSH|GH|PH|ALPINE\s+HOUSE|MIST\s+BENCH|PROPAGATION\s+BENCH|NURSERY)"

CARD_PHRASE_PATTERNS: Dict[str, re.Pattern[str]] = {
    "sown_location_date": re.compile(rf"\bSOWN\b\s*(?:-|:)?\s*(?P<location>{LOCATION_RE})\s+(?P<date>{DATE_RE})", re.IGNORECASE),
    "sown_date_location": re.compile(rf"\bSOWN\b\s*(?P<date>{DATE_RE})\s+(?P<location>{LOCATION_RE})", re.IGNORECASE),
    "germ_date": re.compile(rf"\b(?:GERM|G\.)\b\s*(?P<date>{DATE_RE})", re.IGNORECASE),
    "pricked_out_date": re.compile(rf"\bPRICKED\s+OUT\b\s*(?P<date>{DATE_RE})", re.IGNORECASE),
    "potted_date": re.compile(rf"\bPOTTED\b\s*(?P<date>{DATE_RE})", re.IGNORECASE),
    "transplanted_date": re.compile(rf"\bTRANSPLANTED\b\s*(?P<date>{DATE_RE})", re.IGNORECASE),
    "moved_to_location": re.compile(rf"\bMOVED\s+TO\b\s*(?P<location>{LOCATION_RE})", re.IGNORECASE),
    "removed_from_container": re.compile(r"\bREMOVED\s+FROM\b\s*(?P<container>SEED\s+POT|POTS?|TRAYS?|FLATS?)", re.IGNORECASE),
    "cover_with_gravel": re.compile(r"\bCOVER\s+(?:LIGHTLY|NIGHTLY)?\s*WITH\s+GRAVEL\s+ONLY\b", re.IGNORECASE),
    "stratification_range": re.compile(rf"\b(?:COLD|WARM)\s+STRATIFICATION\b.*?(?P<start>{DATE_RE}).*?(?P<end>{DATE_RE})", re.IGNORECASE),
}


TOKEN_RE = re.compile(r"\s+|[A-Za-z]+(?:[./'-][A-Za-z0-9]+)*|°[CFcf]|\d+(?:[./:-]\d+)*|.")
ACCESSION_RE = re.compile(r"\d{3,}[A-Za-z.-]*-[A-Za-z0-9.-]+")
BOTANICAL_MARKERS = {"subsp", "ssp", "var", "cv", "aff", "cf", "x", "hyb", "ex", "et"}
NURSERY_SIGNAL_TERMS = {
    "sown",
    "sow",
    "germ",
    "germination",
    "pricked",
    "potted",
    "transplanted",
    "seed",
    "seedling",
    "seedlings",
    "cutting",
    "cuttings",
    "pot",
    "pots",
    "greenhouse",
    "glasshouse",
    "coldframe",
    "shadehouse",
    "mist",
    "stratification",
    "physan",
    "perlite",
    "peat",
    "gravel",
    "nutricote",
    "osmocote",
}


def _resolve_data_path(path: Optional[str], default_path: Path) -> Path:
    if path:
        return Path(path).expanduser()
    return default_path


def load_lexicon(path: str | Path) -> List[str]:
    lexicon_path = Path(path)
    if not lexicon_path.exists():
        return _flatten_terms(LEXICON_CATEGORIES)

    seen = set()
    ordered: List[str] = []
    for line in lexicon_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = stripped.lower()
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def load_corrections(
    path: str | Path,
) -> Tuple[Dict[str, str], Sequence[Tuple[re.Pattern[str], str]]]:
    corrections_path = Path(path)
    if not corrections_path.exists():
        return dict(EXPLICIT_REPLACEMENTS), list(PHRASE_NORMALIZATIONS)

    explicit: Dict[str, str] = {}
    phrase_rules: List[Tuple[str, str]] = []
    current_section = ""

    for line in corrections_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("##"):
            current_section = stripped.lstrip("#").strip().lower()
            continue
        if stripped.startswith("#"):
            continue
        if "->" not in stripped:
            raise ValueError(f"Invalid correction line: {stripped}")
        wrong, correct = (part.strip().lower() for part in stripped.split("->", 1))
        if not wrong or not correct:
            raise ValueError(f"Invalid correction line: {stripped}")
        if "phrase" in current_section:
            phrase_rules.append((wrong, correct))
        else:
            explicit[wrong] = correct

    return explicit, _compile_phrase_normalizations(phrase_rules)


def _set_runtime_lexicon(terms: Sequence[str]) -> None:
    global ALL_TERMS, SINGLE_TOKEN_TERMS, MULTIWORD_TERMS, SINGLE_TOKEN_SET, LENGTH_BUCKETS

    ALL_TERMS = list(terms)
    SINGLE_TOKEN_TERMS = [term for term in ALL_TERMS if " " not in term]
    MULTIWORD_TERMS = [term for term in ALL_TERMS if " " in term]
    SINGLE_TOKEN_SET = set(SINGLE_TOKEN_TERMS)

    LENGTH_BUCKETS = {}
    for term in SINGLE_TOKEN_TERMS:
        LENGTH_BUCKETS.setdefault(len(term), []).append(term)


def configure_runtime_resources(
    lexicon_path: Optional[str] = None,
    corrections_path: Optional[str] = None,
) -> Dict[str, str]:
    global ACTIVE_EXPLICIT_REPLACEMENTS, ACTIVE_PHRASE_NORMALIZATIONS

    resolved_lexicon_path = _resolve_data_path(lexicon_path, DEFAULT_LEXICON_PATH)
    resolved_corrections_path = _resolve_data_path(corrections_path, DEFAULT_CORRECTIONS_PATH)

    _set_runtime_lexicon(load_lexicon(resolved_lexicon_path))
    ACTIVE_EXPLICIT_REPLACEMENTS, ACTIVE_PHRASE_NORMALIZATIONS = load_corrections(
        resolved_corrections_path
    )

    return {
        "lexicon_source": str(resolved_lexicon_path.resolve()) if resolved_lexicon_path.exists() else "built-in fallback (nursery_lexicon.txt not found)",
        "corrections_source": str(resolved_corrections_path.resolve()) if resolved_corrections_path.exists() else "built-in fallback (ocr_corrections.txt not found)",
    }


def _normalize_token(token: str) -> str:
    return token.strip().lower().strip(".,:;()[]{}")


def _strip_edge_punctuation(token: str) -> Tuple[str, str, str]:
    match = re.match(r"^([^A-Za-z0-9°]*)(.*?)([^A-Za-z0-9%°]*)$", token)
    if not match:
        return "", token, ""
    return match.group(1), match.group(2), match.group(3)


def _preserve_case(source: str, target: str) -> str:
    if not source:
        return target
    if source.isupper():
        return target.upper()
    if source.islower():
        return target.lower()
    if source.istitle():
        return target.title()
    if source[:1].isupper() and source[1:].islower():
        return target.capitalize()
    return target


def _looks_protected(token: str) -> bool:
    core = token.strip()
    if not core:
        return True
    if ACCESSION_RE.fullmatch(core):
        return True
    if any(ch.isdigit() for ch in core):
        return True
    if re.fullmatch(r"[.\-/:,'\"]+", core):
        return True
    normalized = _normalize_token(core)
    if not normalized:
        return True
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", core):
        return True
    return False


def _looks_like_botanical_name_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or any(ch.isdigit() for ch in stripped):
        return False

    tokens = re.findall(r"[A-Za-z]+(?:\.[A-Za-z]+)?", stripped)
    if not tokens or len(tokens) > 12:
        return False

    lowered = {_normalize_token(tok) for tok in tokens}
    if lowered & NURSERY_SIGNAL_TERMS:
        return False

    authorish = (
        any(marker in lowered for marker in BOTANICAL_MARKERS)
        or "(" in stripped
        or ")" in stripped
        or "'" in stripped
        or '"' in stripped
        or "&" in stripped
    )
    genus_like = tokens[0][:1].isupper() and (len(tokens[0]) == 1 or tokens[0][1:].islower())
    case_like_name = 0
    for token in tokens:
        norm = _normalize_token(token)
        if norm in BOTANICAL_MARKERS:
            case_like_name += 1
        elif token.istitle() or token.islower() or token.isupper() or token.endswith("."):
            case_like_name += 1

    mostly_name_case = case_like_name >= max(2, len(tokens) - 1)
    if stripped.isupper() and len(tokens) <= 6:
        return True
    if tokens[0].isupper() and mostly_name_case and len(tokens) <= 6:
        return True
    if genus_like and mostly_name_case:
        return True
    if authorish and mostly_name_case:
        return True
    return False


def _levenshtein_distance(a: str, b: str, max_distance: int = 3) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    if len(a) > len(b):
        a, b = b, a
    previous = list(range(len(a) + 1))
    for i, char_b in enumerate(b, start=1):
        current = [i]
        min_in_row = current[0]
        for j, char_a in enumerate(a, start=1):
            insertions = previous[j] + 1
            deletions = current[j - 1] + 1
            substitutions = previous[j - 1] + (char_a != char_b)
            value = min(insertions, deletions, substitutions)
            current.append(value)
            if value < min_in_row:
                min_in_row = value
        if min_in_row > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def _candidate_terms(token: str) -> Iterable[str]:
    length = len(token)
    for bucket_len in range(max(1, length - 2), length + 3):
        for candidate in LENGTH_BUCKETS.get(bucket_len, []):
            yield candidate


def _best_single_token_match(token: str) -> Optional[str]:
    token = _normalize_token(token)
    if not token or token in SINGLE_TOKEN_SET:
        return None
    if token in ACTIVE_EXPLICIT_REPLACEMENTS:
        return ACTIVE_EXPLICIT_REPLACEMENTS[token]
    if len(token) < 5:
        return None

    best: Optional[Tuple[str, int, float]] = None
    second: Optional[Tuple[str, int, float]] = None

    for candidate in _candidate_terms(token):
        distance = _levenshtein_distance(token, candidate, max_distance=2)
        ratio = difflib.SequenceMatcher(None, token, candidate).ratio()
        shared_prefix = token[:1] == candidate[:1]
        shared_suffix = len(token) >= 6 and len(candidate) >= 6 and token[-4:] == candidate[-4:]
        acceptable = distance <= 2 or (len(token) >= 8 and ratio >= 0.88)
        if not acceptable:
            continue
        if not (shared_prefix or shared_suffix or ratio >= 0.93):
            continue
        result = (candidate, distance, ratio)
        if best is None or (distance, -ratio, abs(len(candidate) - len(token))) < (
            best[1],
            -best[2],
            abs(len(best[0]) - len(token)),
        ):
            second = best
            best = result
        elif second is None or (distance, -ratio, abs(len(candidate) - len(token))) < (
            second[1],
            -second[2],
            abs(len(second[0]) - len(token)),
        ):
            second = result

    if best is None:
        return None

    candidate, distance, ratio = best
    if distance == 0:
        return None

    if second is not None:
        _, second_distance, second_ratio = second
        clearly_better = (distance + 1 <= second_distance) or (ratio >= second_ratio + 0.10)
        if not clearly_better:
            return None

    if distance == 2 and ratio < 0.84:
        return None
    if ratio < 0.80:
        return None

    return candidate


def _apply_phrase_normalizations(text: str) -> str:
    result = text
    for pattern, replacement in ACTIVE_PHRASE_NORMALIZATIONS:

        def _repl(match: re.Match[str]) -> str:
            return _preserve_case(match.group(0), replacement)

        result = pattern.sub(_repl, result)
    return result


def _correct_text_with_stats(text: str) -> CorrectionDetail:
    if not text:
        return CorrectionDetail(original=text, corrected=text, replacements=0)

    if _looks_like_botanical_name_text(text.strip()):
        return CorrectionDetail(original=text, corrected=text, replacements=0)

    normalized_text = _apply_phrase_normalizations(text)
    phrase_replacements = 0 if normalized_text == text else 1

    pieces = TOKEN_RE.findall(normalized_text)
    replacements = phrase_replacements

    for idx, piece in enumerate(pieces):
        if piece.isspace() or _looks_protected(piece):
            continue
        prefix, core, suffix = _strip_edge_punctuation(piece)
        if not core or _looks_protected(core):
            continue
        normalized_core = _normalize_token(core)
        if len(normalized_core) < 3:
            continue
        if core.islower() and len(normalized_core) < 6 and normalized_core not in ACTIVE_EXPLICIT_REPLACEMENTS:
            continue
        if core.istitle() and len(normalized_core) < 5 and normalized_core not in ACTIVE_EXPLICIT_REPLACEMENTS:
            continue
        candidate = _best_single_token_match(core)
        if not candidate:
            continue
        corrected = prefix + _preserve_case(core, candidate) + suffix
        if corrected != piece:
            pieces[idx] = corrected
            replacements += 1

    corrected_text = "".join(pieces)
    return CorrectionDetail(original=text, corrected=corrected_text, replacements=replacements)


def correct_text(text: str) -> str:
    """Return conservatively corrected OCR text.

    Parameters
    ----------
    text:
        Raw OCR output.

    Returns
    -------
    str
        Text after conservative lexicon-based correction.
    """

    return _correct_text_with_stats(text).corrected


def _ensure_output_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(extractions)")}
    if "corrected_propagation_text" not in columns:
        conn.execute("ALTER TABLE extractions ADD COLUMN corrected_propagation_text TEXT")
    if "corrected_botanical_name" not in columns:
        conn.execute("ALTER TABLE extractions ADD COLUMN corrected_botanical_name TEXT")


def apply_corrections_to_db(db_path: str, dry_run: bool = False) -> dict:
    """Apply lexicon corrections to successful extraction records.

    The original fields are left untouched. Corrected values are written to
    `corrected_propagation_text` and `corrected_botanical_name`.
    """

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_output_columns(conn)
        rows = conn.execute(
            """
            SELECT e.id, e.botanical_name, e.propagation_text
            FROM extractions e
            JOIN cards c ON c.id = e.card_id
            WHERE c.status = 'success'
            ORDER BY e.id
            """
        ).fetchall()

        total_processed = 0
        changed_rows = 0
        total_replacements = 0
        botanical_changes = 0
        propagation_changes = 0
        updates: List[Tuple[str, str, int]] = []

        for row in rows:
            total_processed += 1
            botanical = row["botanical_name"] or ""
            propagation = row["propagation_text"] or ""

            corrected_botanical = _correct_text_with_stats(botanical)
            corrected_propagation = _correct_text_with_stats(propagation)

            row_changed = False
            if corrected_botanical.corrected != botanical:
                row_changed = True
                botanical_changes += 1
            if corrected_propagation.corrected != propagation:
                row_changed = True
                propagation_changes += 1
            if row_changed:
                changed_rows += 1

            total_replacements += (
                corrected_botanical.replacements + corrected_propagation.replacements
            )

            updates.append(
                (
                    corrected_botanical.corrected,
                    corrected_propagation.corrected,
                    row["id"],
                )
            )

        if not dry_run:
            conn.executemany(
                """
                UPDATE extractions
                SET corrected_botanical_name = ?,
                    corrected_propagation_text = ?
                WHERE id = ?
                """,
                updates,
            )
            conn.commit()
        else:
            conn.rollback()

        return {
            "db_path": db_path,
            "dry_run": dry_run,
            "total_processed": total_processed,
            "rows_changed": changed_rows,
            "botanical_fields_changed": botanical_changes,
            "propagation_fields_changed": propagation_changes,
            "total_corrections_made": total_replacements,
            "lexicon_terms": len(ALL_TERMS),
            "single_token_terms": len(SINGLE_TOKEN_TERMS),
            "multiword_terms": len(MULTIWORD_TERMS),
        }
    finally:
        conn.close()


def _print_stats(stats: dict) -> None:
    for key in (
        "db_path",
        "dry_run",
        "total_processed",
        "rows_changed",
        "botanical_fields_changed",
        "propagation_fields_changed",
        "total_corrections_made",
        "lexicon_terms",
        "single_token_terms",
        "multiword_terms",
    ):
        print(f"{key}: {stats[key]}")


def _print_dry_run(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT e.id, e.botanical_name, e.propagation_text
            FROM extractions e
            JOIN cards c ON c.id = e.card_id
            WHERE c.status = 'success'
            ORDER BY e.id
            """
        ).fetchall()
        for row in rows:
            botanical = row["botanical_name"] or ""
            propagation = row["propagation_text"] or ""
            corrected_botanical = correct_text(botanical)
            corrected_propagation = correct_text(propagation)
            if corrected_botanical == botanical and corrected_propagation == propagation:
                continue
            print(f"\n=== extraction_id={row['id']} ===")
            if corrected_botanical != botanical:
                print("[botanical_name]")
                print(f"- before: {botanical}")
                print(f"- after:  {corrected_botanical}")
            if corrected_propagation != propagation:
                print("[propagation_text]")
                print("- before:")
                print(propagation)
                print("- after:")
                print(corrected_propagation)
    finally:
        conn.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Nursery lexicon correction for propagation card OCR output")
    parser.add_argument("--db", default="cards.db", help="Path to cards.db (default: cards.db)")
    parser.add_argument("--lexicon", help="Path to nursery_lexicon.txt (default: script-relative nursery_lexicon.txt)")
    parser.add_argument("--corrections", help="Path to ocr_corrections.txt (default: script-relative ocr_corrections.txt)")
    parser.add_argument("--dry-run", action="store_true", help="Show corrections without writing to the database")
    parser.add_argument("--stats", action="store_true", help="Print correction statistics")
    args = parser.parse_args(argv)

    resource_info = configure_runtime_resources(args.lexicon, args.corrections)
    print(f"Loaded lexicon: {resource_info['lexicon_source']}")
    print(f"Loaded corrections: {resource_info['corrections_source']}")

    if args.dry_run:
        _print_dry_run(args.db)

    stats = apply_corrections_to_db(args.db, dry_run=args.dry_run)
    if args.stats or not args.dry_run:
        _print_stats(stats)

    return 0


configure_runtime_resources()


if __name__ == "__main__":
    raise SystemExit(main())
