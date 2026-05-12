"""Filename hint extraction for propagation card scan PDFs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rag_config import DEFAULT_CONFIG_PATH, load_config
from rag_schema import get_db


CANONICAL_RE = re.compile(
    r"^(?:(?P<scan_date>\d{4}-\d{2}-\d{2})__)?(?P<scope>[a-z]+(?:-[a-z]+)?)(?:__(?P<mode>simplex|duplex))?$"
)
DATE_RE = re.compile(r"(?:^|[-_])(20\d{2}-\d{2}-\d{2})(?:[-_]|$)")
TRAILING_DIGITS_RE = re.compile(r"\d+$")
DEFAULT_DUPLEX_MARKERS = ["duplex", "double"]


def _duplex_markers() -> list[str]:
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
        markers = config.get("filename_parsing", {}).get("duplex_markers")
        if markers:
            return [str(marker).lower() for marker in markers]
    except Exception:
        pass
    return DEFAULT_DUPLEX_MARKERS


def _default_db_path() -> str | None:
    try:
        return load_config(DEFAULT_CONFIG_PATH).get("rag_db_path")
    except Exception:
        return None


def _empty_result(pdf_name: str) -> dict[str, Any]:
    return {
        "raw_filename": pdf_name,
        "normalized_stem": "",
        "scan_date": None,
        "duplex": False,
        "hint_mode": "none",
        "genus_candidates": [],
        "range_start": None,
        "range_end": None,
        "confidence": 0.0,
    }


def _load_genus_index(db_path: str | None) -> list[dict[str, str]]:
    if not db_path or not Path(db_path).exists():
        return []
    conn = get_db(db_path)
    rows = [dict(row) for row in conn.execute(
        "SELECT genus, prefix_3, prefix_4, prefix_5, sort_key, accession_count FROM rag_filename_genus_index ORDER BY sort_key"
    )]
    conn.close()
    return rows


def _find_exact(token: str, genus_rows: list[dict[str, str]]) -> str | None:
    token = token.lower()
    for row in genus_rows:
        if row["sort_key"] == token:
            return row["genus"]
    return None


def _find_prefix_matches(token: str, genus_rows: list[dict[str, str]]) -> list[str]:
    token = token.lower()
    if not token or not genus_rows:
        return []
    matches = []
    for row in genus_rows:
        genus_lower = row["sort_key"]
        if genus_lower.startswith(token):
            matches.append(row["genus"])
    return matches


def _range_candidates(start_token: str, end_token: str, genus_rows: list[dict[str, str]]) -> tuple[list[str], str | None, str | None]:
    start_matches = _find_prefix_matches(start_token, genus_rows)
    end_matches = _find_prefix_matches(end_token, genus_rows)
    if not start_matches or not end_matches:
        return [], None, None
    start_bound = start_matches[0]
    end_bound = end_matches[-1]
    start_key = start_bound.lower()
    end_key = end_bound.lower()
    if start_key > end_key:
        start_key, end_key = end_key, start_key
        start_bound, end_bound = end_bound, start_bound
    results = [row["genus"] for row in genus_rows if start_key <= row["sort_key"] <= end_key]
    return results, start_bound, end_bound


def _fallback_candidates(tokens: list[str]) -> list[str]:
    candidates = []
    for token in tokens:
        cleaned = token.strip("-_")
        if cleaned and cleaned.isalpha():
            candidates.append(cleaned.capitalize())
    return candidates


def _normalize_stem(stem: str) -> str:
    stem = stem.lower().replace("_", "-")
    stem = re.sub(r"\s+", "-", stem)
    stem = re.sub(r"-+", "-", stem).strip("-")
    return stem


def parse_filename(pdf_name: str, db_path: str | None = None) -> dict[str, Any]:
    result = _empty_result(pdf_name)
    stem = Path(pdf_name).stem.lower()
    stem = stem.replace("_", "-")

    canonical = CANONICAL_RE.fullmatch(Path(pdf_name).stem.lower())
    if canonical:
        scan_date = canonical.group("scan_date")
        scope = canonical.group("scope")
        duplex = canonical.group("mode") == "duplex"
        genus_rows = _load_genus_index(db_path or _default_db_path())
        result.update({
            "normalized_stem": _normalize_stem(Path(pdf_name).stem),
            "scan_date": scan_date,
            "duplex": duplex,
        })
        tokens = scope.split("-")
        if len(tokens) == 1:
            if genus_rows:
                exact = _find_exact(tokens[0], genus_rows)
                if exact:
                    result.update({
                        "hint_mode": "exact_genus",
                        "genus_candidates": [exact],
                        "range_start": exact,
                        "range_end": exact,
                        "confidence": 0.98,
                    })
                else:
                    prefix_matches = _find_prefix_matches(tokens[0], genus_rows)
                    if prefix_matches:
                        result.update({
                            "hint_mode": "single_prefix",
                            "genus_candidates": prefix_matches,
                            "range_start": prefix_matches[0],
                            "range_end": prefix_matches[-1],
                            "confidence": 0.66,
                        })
            else:
                fallback = _fallback_candidates(tokens)
                if fallback:
                    result.update({
                        "hint_mode": "exact_genus",
                        "genus_candidates": fallback,
                        "range_start": fallback[0],
                        "range_end": fallback[0],
                        "confidence": 0.3,
                    })
        elif len(tokens) == 2:
            if genus_rows:
                candidates, start_bound, end_bound = _range_candidates(tokens[0], tokens[1], genus_rows)
                if candidates:
                    result.update({
                        "hint_mode": "range_prefix",
                        "genus_candidates": candidates,
                        "range_start": start_bound,
                        "range_end": end_bound,
                        "confidence": 0.82,
                    })
            else:
                fallback = _fallback_candidates(tokens)
                if fallback:
                    result.update({
                        "hint_mode": "range_prefix",
                        "genus_candidates": fallback,
                        "range_start": fallback[0],
                        "range_end": fallback[-1],
                        "confidence": 0.25,
                    })
        return result

    scan_date = None
    date_match = DATE_RE.search(stem)
    if date_match:
        scan_date = date_match.group(1)
        stem = stem.replace(scan_date, "-")
    stem = re.sub(r"^scan", "", stem)
    stem = stem.replace("_", "-")
    stem = re.sub(r"-+", "-", stem).strip("-")

    duplex = False
    for marker in _duplex_markers():
        if marker in stem:
            duplex = True
            stem = stem.replace(marker, "-")
    stem = re.sub(r"-+", "-", stem).strip("-")
    stem = TRAILING_DIGITS_RE.sub("", stem).strip("-")
    normalized_stem = _normalize_stem(stem)

    result.update({
        "normalized_stem": normalized_stem,
        "scan_date": scan_date,
        "duplex": duplex,
    })
    if not normalized_stem:
        return result

    genus_rows = _load_genus_index(db_path or _default_db_path())
    tokens = [token for token in normalized_stem.split("-") if token]

    if len(tokens) == 1:
        token = tokens[0]
        exact = _find_exact(token, genus_rows) if genus_rows else None
        if exact:
            result.update({
                "hint_mode": "exact_genus",
                "genus_candidates": [exact],
                "range_start": exact,
                "range_end": exact,
                "confidence": 0.95,
            })
            return result
        prefix_matches = _find_prefix_matches(token, genus_rows) if genus_rows else []
        if prefix_matches:
            result.update({
                "hint_mode": "single_prefix",
                "genus_candidates": prefix_matches,
                "range_start": prefix_matches[0],
                "range_end": prefix_matches[-1],
                "confidence": 0.62,
            })
            return result
        fallback = _fallback_candidates(tokens)
        if fallback:
            result.update({
                "hint_mode": "single_prefix",
                "genus_candidates": fallback,
                "range_start": fallback[0],
                "range_end": fallback[-1],
                "confidence": 0.15,
            })
            return result
        return result

    if len(tokens) >= 2:
        start_token, end_token = tokens[0], tokens[1]
        if genus_rows:
            start_exact = _find_exact(start_token, genus_rows)
            end_exact = _find_exact(end_token, genus_rows)
            if start_exact and end_exact:
                candidates, start_bound, end_bound = _range_candidates(start_token, end_token, genus_rows)
                if candidates:
                    result.update({
                        "hint_mode": "range_prefix",
                        "genus_candidates": candidates,
                        "range_start": start_bound,
                        "range_end": end_bound,
                        "confidence": 0.88,
                    })
                    return result
            candidates, start_bound, end_bound = _range_candidates(start_token, end_token, genus_rows)
            if candidates:
                result.update({
                    "hint_mode": "range_prefix",
                    "genus_candidates": candidates,
                    "range_start": start_bound,
                    "range_end": end_bound,
                    "confidence": 0.74,
                })
                return result
        if not genus_rows:
            fallback = _fallback_candidates(tokens[:2])
            if fallback:
                result.update({
                    "hint_mode": "range_prefix",
                    "genus_candidates": fallback,
                    "range_start": fallback[0],
                    "range_end": fallback[-1],
                    "confidence": 0.2,
                })
                return result

    return result
