"""Post-processing for OCR extractions.

Extracts accession numbers from propagation text that the model transcribed
but didn't include in the accession_number array. Validates and classifies
all accession numbers against the RAG index.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from privacy_redaction import Redaction, redact

# Fields that may contain incidentally-extracted donor PII.
# `source_info` is the designed locus; the others are content fields where
# PII appears only by accident.
PII_PRONE_FIELDS: tuple[str, ...] = (
    "source_info",
    "curators_info",
    "collection_info",
    "propagation_text",
)


# --- Accession number patterns ---

# Legacy format as written on cards: NNNNN-NNN-NN or NNNNN-NNNN-NNNN
# The DB normalizes to NNNNN-NNN-NN but cards may use longer forms
LEGACY_CARD_RE = re.compile(
    r"\b(\d{4,6}[-/]\d{2,4}[-/]\d{2,4})\b"
)

# Modern format: YYYY-NNNNN or YYYY-NNNN (4-digit year, 4-5 digit sequence)
MODERN_RE = re.compile(
    r"\b((?:19|20)\d{2}-\d{4,5})\b"
)

# Item suffix: .NN appended to any format
ITEM_SUFFIX_RE = re.compile(r"^(.+?)\.(\d{1,2})$")

# Strict classification patterns (after normalization)
LEGACY_STRICT = re.compile(r"^\d{4,6}-\d{2,4}-\d{2,4}$")
MODERN_STRICT = re.compile(r"^(?:19|20)\d{2}-\d{4,5}$")

# --- False positive patterns ---

# Standalone numbers without dashes: geocodes (5-digit), source codes (3-digit),
# quantities, page numbers, etc.
BARE_NUMBER_RE = re.compile(r"^\d+$")

# Date-like patterns: D/M/Y, M/D/Y, Y/M/D in various separators
DATE_PATTERNS = [
    re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"),      # D/M/Y or M/D/Y
    re.compile(r"^(19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}$"),  # Y/M/D
]

# Numbers with dots that aren't item suffixes (geocode.source like "42600.08")
# Real item suffixes have a dash-formatted accession before the dot
GEOCODE_DOT_SOURCE_RE = re.compile(r"^\d{4,5}\.\d{1,3}$")


def normalize_dashes(raw: str) -> str:
    """Normalize unicode dashes and slashes to hyphens."""
    result = raw.strip()
    result = result.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    result = result.replace("/", "-")
    result = re.sub(r"\s+", "", result)
    return result


def normalize_legacy_to_db(accession: str) -> str:
    """Normalize a card-format legacy accession to DB format (NNNNN-NNN-NN).
    
    Card may write: 39149-0077-2008
    DB stores:      39149-077-08
    """
    normalized = normalize_dashes(accession)
    parts = normalized.split("-")
    if len(parts) != 3:
        return normalized

    prefix, source, year = parts

    # Ensure prefix is up to 5 digits
    prefix = prefix.lstrip("0") or "0"
    prefix = prefix.zfill(5) if len(prefix) <= 5 else prefix

    # Source: take last 3 digits, zero-pad
    source = source[-3:].lstrip("0") or "0"
    source = source.zfill(3)

    # Year: take last 2 digits
    year = year[-2:]

    return f"{prefix}-{source}-{year}"


def classify_format(accession: str) -> str:
    """Classify an accession number as legacy, modern, or unknown."""
    normalized = normalize_dashes(accession)

    # Strip item suffix for classification
    base = normalized
    suffix = None
    m = ITEM_SUFFIX_RE.match(normalized)
    if m:
        base, suffix = m.group(1), m.group(2)

    if MODERN_STRICT.fullmatch(base):
        return "modern_item" if suffix else "modern"
    if LEGACY_STRICT.fullmatch(base):
        return "legacy_item" if suffix else "legacy"
    return "unknown"


def is_false_positive(candidate: str) -> bool:
    """Filter out non-accession patterns."""
    raw = candidate.strip()
    normalized = normalize_dashes(raw)

    # Bare numbers without dashes: geocodes, source codes, quantities
    if BARE_NUMBER_RE.fullmatch(normalized):
        return True

    # Geocode.source pattern (e.g., "42600.08")
    if GEOCODE_DOT_SOURCE_RE.fullmatch(normalized):
        return True

    # Date-like patterns
    for pattern in DATE_PATTERNS:
        if pattern.fullmatch(normalized):
            return True

    # Too short to be an accession (need at least X-Y-Z or YYYY-NNNN)
    parts = normalized.split("-")
    if len(parts) == 1:
        return True  # No dashes = not an accession
    if len(parts) == 2:
        # Modern format YYYY-NNNNN: year part must be a valid year
        if not re.fullmatch(r"(?:19|20)\d{2}", parts[0]):
            return True
        if len(parts[1]) < 4:
            return True

    # Two-part number where first segment is too short for modern
    # and pattern doesn't match legacy 3-part
    if len(parts) == 2 and len(parts[0]) < 4:
        return True

    return False


def extract_accessions_from_text(text: str) -> list[str]:
    """Extract candidate accession numbers from free text.
    
    Finds both legacy (NNNNN-NNN-NN variants) and modern (YYYY-NNNNN)
    patterns from propagation text the model transcribed.
    """
    if not text:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    # Find legacy-format candidates (various digit widths with dashes)
    for match in LEGACY_CARD_RE.finditer(text):
        raw = match.group(1)
        if is_false_positive(raw):
            continue
        normalized = normalize_dashes(raw)
        fmt = classify_format(normalized)
        if fmt == "unknown":
            continue
        # Normalize to DB format for dedup
        db_form = normalize_legacy_to_db(normalized) if "legacy" in fmt else normalized
        if db_form not in seen:
            candidates.append(normalized)
            seen.add(db_form)

    # Find modern-format candidates (YYYY-NNNNN)
    for match in MODERN_RE.finditer(text):
        raw = match.group(1)
        if is_false_positive(raw):
            continue
        normalized = normalize_dashes(raw)
        fmt = classify_format(normalized)
        if fmt == "unknown":
            continue
        if normalized not in seen:
            candidates.append(normalized)
            seen.add(normalized)

    return candidates


def validate_model_accessions(accessions: list[str]) -> list[str]:
    """Filter model-provided accessions, removing false positives.
    
    The model often picks up geocodes, source numbers, and other
    non-accession numbers from header fields.
    """
    valid = []
    for acc in accessions:
        if is_false_positive(acc):
            continue
        fmt = classify_format(acc)
        if fmt != "unknown":
            valid.append(acc)
    return valid


def merge_accessions(model_accessions: list[str], text_accessions: list[str]) -> list[str]:
    """Merge model-extracted and text-extracted accessions, deduplicating.
    
    Uses DB-normalized form for dedup so card-format and DB-format
    of the same accession don't both appear.
    """
    seen: set[str] = set()
    merged: list[str] = []

    for acc in model_accessions:
        normalized = normalize_dashes(acc)
        fmt = classify_format(normalized)
        db_form = normalize_legacy_to_db(normalized) if "legacy" in fmt else normalized
        if db_form not in seen:
            merged.append(acc)
            seen.add(db_form)

    for acc in text_accessions:
        normalized = normalize_dashes(acc)
        fmt = classify_format(normalized)
        db_form = normalize_legacy_to_db(normalized) if "legacy" in fmt else normalized
        if db_form not in seen:
            merged.append(acc)
            seen.add(db_form)

    return merged


def validate_against_rag(accession: str, rag_db_path: str) -> dict | None:
    """Check if an accession number exists in the RAG index.
    
    Tries both the raw form and the DB-normalized legacy form.
    Returns match info dict or None if not found.
    """
    if not Path(rag_db_path).exists():
        return None

    normalized = normalize_dashes(accession)
    fmt = classify_format(normalized)
    db_form = normalize_legacy_to_db(normalized) if "legacy" in fmt else normalized

    conn = sqlite3.connect(rag_db_path)
    conn.row_factory = sqlite3.Row

    # Try raw form first, then DB-normalized form
    for search_val in [normalized, db_form]:
        row = conn.execute(
            "SELECT accession_number, genus, taxon_name, taxon_name_full, family "
            "FROM rag_accessions WHERE accession_number = ?",
            (search_val,)
        ).fetchone()
        if row:
            result = {
                "found_in": "rag_accessions",
                "accession_number": row["accession_number"],
                "matched_as": search_val,
                "genus": row["genus"],
                "taxon_name": row["taxon_name"],
                "taxon_name_full": row["taxon_name_full"],
                "family": row["family"],
            }
            conn.close()
            return result

    # Check rag_items for item-suffixed accessions
    for search_val in [normalized, db_form]:
        row = conn.execute(
            "SELECT item_accession_number, genus, taxon_name "
            "FROM rag_items WHERE item_accession_number = ?",
            (search_val,)
        ).fetchone()
        if row:
            result = {
                "found_in": "rag_items",
                "accession_number": row["item_accession_number"],
                "matched_as": search_val,
                "genus": row["genus"],
                "taxon_name": row["taxon_name"],
            }
            conn.close()
            return result

    conn.close()
    return None


def find_taxon_matches(botanical_name: str, family: str | None, rag_db_path: str) -> list[dict]:
    """Find matching taxa in the RAG index by botanical name and/or family.
    
    Used when no accession number is available (pre-accessioning era cards).
    Returns list of candidate matches.
    """
    if not botanical_name or not Path(rag_db_path).exists():
        return []

    conn = sqlite3.connect(rag_db_path)
    conn.row_factory = sqlite3.Row

    parts = botanical_name.strip().split()
    if not parts:
        conn.close()
        return []

    genus = parts[0]
    matches = []

    # Try exact taxon match first
    rows = conn.execute(
        "SELECT DISTINCT genus, taxon_name, taxon_name_full, family, observation_count "
        "FROM rag_taxa WHERE taxon_name_full LIKE ? ORDER BY observation_count DESC LIMIT 10",
        (f"{botanical_name}%",)
    ).fetchall()

    if rows:
        matches = [dict(r) for r in rows]
    else:
        # Fall back to genus match
        rows = conn.execute(
            "SELECT DISTINCT genus, taxon_name, taxon_name_full, family, observation_count "
            "FROM rag_taxa WHERE genus = ? ORDER BY observation_count DESC LIMIT 20",
            (genus,)
        ).fetchall()
        matches = [dict(r) for r in rows]

    # If family provided, boost matches with matching family
    if family and matches:
        family_lower = family.lower()
        matches.sort(key=lambda m: (
            0 if (m.get("family") or "").lower() == family_lower else 1,
            -m.get("observation_count", 0),
        ))

    conn.close()
    return matches


def redact_pii_fields(extraction: dict) -> tuple[dict, dict[str, list[Redaction]]]:
    """Apply privacy_redaction.redact to every PII-prone field.

    Returns (redacted_extraction, audit_by_field). `redacted_extraction` is
    a shallow copy of the input with PII-prone fields replaced by their
    redacted form, plus a `*_raw` shadow key for each field that actually
    had PII removed (so the caller can persist both forms). `audit_by_field`
    maps the field name to its Redaction list — only present for fields
    that matched something.

    Non-string field values pass through untouched.
    """
    redacted: dict = dict(extraction)
    audit: dict[str, list[Redaction]] = {}

    for field in PII_PRONE_FIELDS:
        value = extraction.get(field)
        if not isinstance(value, str) or not value:
            continue
        new_value, matches = redact(value)
        if matches:
            redacted[field] = new_value
            redacted[f"{field}_raw"] = value
            audit[field] = matches

    return redacted, audit


def postprocess_extraction(
    model_accessions: list[str],
    propagation_text: str,
    botanical_name: str | None = None,
    family: str | None = None,
    rag_db_path: str | None = None,
) -> dict:
    """Run full post-processing on a single card extraction.
    
    1. Filter model accessions (remove geocodes, source numbers, etc.)
    2. Extract accessions from propagation text
    3. Merge and deduplicate
    4. Validate against RAG index
    5. If no accessions found, try taxon matching
    """
    # Filter model accessions first
    filtered_model = validate_model_accessions(model_accessions)
    rejected_model = [a for a in model_accessions if a not in filtered_model]

    # Extract accessions from propagation text
    text_accessions = extract_accessions_from_text(propagation_text)

    # Merge with filtered model accessions
    merged = merge_accessions(filtered_model, text_accessions)

    # Classify and validate each
    classified = []
    for acc in merged:
        normalized = normalize_dashes(acc)
        fmt = classify_format(normalized)
        entry = {
            "accession_number": acc,
            "normalized": normalized,
            "db_normalized": normalize_legacy_to_db(normalized) if "legacy" in fmt else normalized,
            "format": fmt,
            "source": "model" if acc in filtered_model else "text_extraction",
        }
        if rag_db_path:
            entry["rag_match"] = validate_against_rag(acc, rag_db_path)
        classified.append(entry)

    # Track what was new from text extraction
    model_db_forms = set()
    for acc in filtered_model:
        n = normalize_dashes(acc)
        f = classify_format(n)
        model_db_forms.add(normalize_legacy_to_db(n) if "legacy" in f else n)

    text_only = []
    for acc in text_accessions:
        n = normalize_dashes(acc)
        f = classify_format(n)
        db = normalize_legacy_to_db(n) if "legacy" in f else n
        if db not in model_db_forms:
            text_only.append(acc)

    result = {
        "accessions": classified,
        "text_extracted_new": text_only,
        "rejected_model": rejected_model,
        "total_count": len(classified),
        "model_count": len(filtered_model),
        "model_rejected_count": len(rejected_model),
        "text_extracted_count": len(text_only),
    }

    # If no accessions found, try taxon matching
    if not classified and botanical_name and rag_db_path:
        result["taxon_matches"] = find_taxon_matches(botanical_name, family, rag_db_path)

    return result
