"""Conservative PII redaction for propagation-card extractions.

The propagation cards may incidentally contain donor-identifying information
in free-text fields — most often in `source_info` ("Received from Mrs. Smith,
123 Oak St, Vancouver") but occasionally in `curators_info`, `collection_info`,
or `propagation_text`. This module removes such information before any
extracted record leaves the institution.

Design choices:
- Conservative patterns only. False negatives (missed redactions) can be caught
  in a later pass; false positives erase real botanical data (in particular,
  taxonomic authorities like "L." or "Douglas ex Hook." after a binomial).
- Pure functions returning (redacted_text, audit_records). Storage decisions
  live in the caller (post_processing / scrubber script).
- Replacement tokens are categorised so reviewers can scan the audit trail
  without re-reading the original PII.

Patterns intentionally NOT matched (false-positive risk too high for the
gain):
- Bare capitalised name pairs ("Jane Smith") — collides with botanical
  authority strings and place names.
- Standalone five-digit numbers — collides with accession-number components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# -- Data types ---------------------------------------------------------------

@dataclass(frozen=True)
class Redaction:
    """One PII match found in a text field.

    Stored to the audit table so reviewers can tune patterns without
    re-running OCR.
    """
    category: str          # "titled_name" | "email" | "phone" | "address" | "care_of" | "postal_code"
    original: str          # the matched substring (PII — handle accordingly)
    start: int             # offset in the input string
    end: int


# -- Patterns -----------------------------------------------------------------

# Titled personal name: "Mrs. Jane Smith", "Dr Watson", "Prof. A. B. Hutchinson"
# Up to 4 capitalised tokens following the title (allows initials).
_TITLED_NAME = re.compile(
    r"\b("
    r"Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|Rev|Reverend|"
    r"Sir|Dame|Lord|Lady|Hon|Honorable|Honourable"
    r")\.?\s+"
    r"((?:[A-Z][A-Za-z'\-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'\-]+|[A-Z]\.)){0,3})"
)

# "c/o Jane Smith" or "care of Mr Brown".
_CARE_OF = re.compile(
    r"\b(?:c/o|c\.o\.|care\s+of)\s+"
    r"((?:[A-Z][A-Za-z'\-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'\-]+|[A-Z]\.)){0,3})",
    flags=re.IGNORECASE,
)

# Email address (conservative — local-part forbids leading/trailing dot).
_EMAIL = re.compile(
    r"\b[A-Za-z0-9_+\-](?:[A-Za-z0-9_.+\-]*[A-Za-z0-9_+\-])?@"
    r"[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+\b"
)

# North-American phone: optional +1, area code in parens or not, common
# separators. The (?<!\d) and (?<!\d-) lookbehinds reject embedded digit
# runs (e.g. "289-777-2010" inside the accession number "40289-777-2010").
_PHONE_NA = re.compile(
    r"(?<!\d)(?<!\d-)(?<!\d\.)(?<!\d/)"
    r"(?:\+?1[\s\-.])?"
    r"(?:\(\d{3}\)|\d{3})[\s\-.]"
    r"\d{3}[\s\-.]"
    r"\d{4}(?!\d)(?!-\d)"
)

# International phone: explicit "+" prefix, country code, 7+ digits with any
# common separators. Stricter than NA pattern to avoid catching things like
# "+200 seeds".
_PHONE_INTL = re.compile(
    r"\+\d{1,3}[\s\-.()]+\d[\d\s\-.()]{7,}\d"
)

# Street address: number + 1-4 capitalised tokens + recognised street suffix.
_STREET_SUFFIXES = (
    r"St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|"
    r"Blvd|Boulevard|Way|Crescent|Cres|Court|Ct|Place|Pl|"
    r"Hwy|Highway|Trail|Tr|Terrace|Ter"
)
_STREET_ADDRESS = re.compile(
    r"\b\d{1,5}\s+"
    r"(?:[A-Z][A-Za-z'\-]+\s+){1,4}"
    r"(?:" + _STREET_SUFFIXES + r")\b\.?",
)

# Canadian postal code (A1A 1A1). Not US ZIP — too false-positive prone.
_POSTAL_CODE_CA = re.compile(
    r"\b[A-Z]\d[A-Z][\s\-]?\d[A-Z]\d\b"
)


_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    # (category, compiled_pattern, group_to_use_as_match_text)
    # group 0 means: use the whole match.
    ("titled_name",  _TITLED_NAME,    0),
    ("care_of",      _CARE_OF,        0),
    ("email",        _EMAIL,          0),
    ("phone",        _PHONE_NA,       0),
    ("phone",        _PHONE_INTL,     0),
    ("address",      _STREET_ADDRESS, 0),
    ("postal_code",  _POSTAL_CODE_CA, 0),
)


# -- API ----------------------------------------------------------------------

def find_pii(text: str) -> list[Redaction]:
    """Return all PII matches found in `text`, in order of appearance.

    Overlapping matches across categories are deduplicated by character
    span: the first category that claims a span wins. Pattern order in
    `_PATTERNS` is the precedence (titled_name before address, etc.).
    """
    if not text:
        return []

    claimed: list[tuple[int, int]] = []
    found: list[Redaction] = []

    for category, pattern, _ in _PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if _overlaps_any(span, claimed):
                continue
            claimed.append(span)
            found.append(Redaction(
                category=category,
                original=match.group(0),
                start=span[0],
                end=span[1],
            ))

    found.sort(key=lambda r: r.start)
    return found


def redact(text: str) -> tuple[str, list[Redaction]]:
    """Return (redacted_text, audit_list) for an input string.

    The redacted text replaces every match with `[REDACTED:CATEGORY]`.
    The audit list is in original-string order with the verbatim matched
    substrings; callers decide whether to persist or hash those.
    """
    if not text:
        return text, []

    matches = find_pii(text)
    if not matches:
        return text, []

    # Apply replacements right-to-left so earlier offsets stay valid.
    out = text
    for r in reversed(matches):
        out = out[:r.start] + f"[REDACTED:{r.category.upper()}]" + out[r.end:]
    return out, matches


# -- Helpers ------------------------------------------------------------------

def _overlaps_any(span: tuple[int, int], existing: list[tuple[int, int]]) -> bool:
    """True if `span` overlaps any span in `existing`."""
    s_start, s_end = span
    for e_start, e_end in existing:
        if s_start < e_end and e_start < s_end:
            return True
    return False
