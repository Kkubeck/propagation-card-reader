"""Field normalization for cards.db extractions.

Repeatable CLI pass: copy the original DB, normalize the copy.
Each normalizer function returns the count of rows changed.
"""

from __future__ import annotations

import re
import sqlite3


# --- Family: Title Case ---

def normalize_family(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, family FROM extractions WHERE family IS NOT NULL AND family != ''"
    ).fetchall()
    updated = 0
    for row in rows:
        original = row["family"]
        normalized = original.strip().title()
        if normalized != original:
            conn.execute("UPDATE extractions SET family = ? WHERE id = ?",
                        (normalized, row["id"]))
            updated += 1
    conn.commit()
    return updated


# --- Received As: Uppercase canonical forms ---

RECEIVED_AS_MAP = {
    # SEED variants
    "seed": "SEED", "seeds": "SEED", "seeds.": "SEED", "seed.": "SEED",
    "see": "SEED", "see0": "SEED", "see)": "SEED", "seei": "SEED",
    "seol": "SEED", "sedl": "SEED", "seedl": "SEED", "seedlings": "SEED",
    "sseed": "SEED", "deed": "SEED", "se10": "SEED", "s10": "SEED",
    # URCU variants
    "urcu": "URCU", "urcu.": "URCU", "urcv": "URCU", "urca": "URCU",
    "urco": "URCU", "urcil": "URCU", "urcw": "URCU", "unc": "URCU",
    "unrc": "URCU", "unrooted": "URCU", "u": "URCU", "urbc": "URCU",
    "urw": "URCU", "vru": "URCU", "vrw": "URCU", "urc": "URCU",
    # CUTT (cuttings — normalize to URCU)
    "cutt": "URCU", "cuts": "URCU", "cut": "URCU", "cutting": "URCU",
    "cuttings": "URCU", "rcut": "URCU", "rt": "URCU",
    "rootcutt.": "URCU", "rootcutt": "URCU", "root": "URCU",
    # SC10 (semi-ripe/softwood cuttings — normalize to URCU)
    "sc10": "URCU", "sc102": "URCU", "sc104": "URCU", "sc106": "URCU",
    "sc16": "URCU", "sco": "URCU", "swc": "URCU", "swc10": "URCU",
    "hwc": "URCU", "hwcu": "URCU",
    # PLNT variants
    "plnt": "PLNT", "plnt.": "PLNT", "plant": "PLNT", "plants": "PLNT",
    "plts": "PLNT", "plts.": "PLNT", "plt.": "PLNT", "plt": "PLNT", "plwt": "PLNT",
    "pl.+": "PLNT",
    # SCIO (scions/grafting)
    "scio": "SCIO", "scions": "SCIO", "scion": "SCIO",
    # SPOR
    "spor": "SPOR", "spore": "SPOR", "spores": "SPOR", "spors": "SPOR",
    "spdr": "SPOR",
    # BULB
    "bulb": "BULB", "bulbs": "BULB", "bulbil": "BULB", "bbil": "BULB",
    # DIVI
    "divi": "DIVI", "divi.": "DIVI", "div": "DIVI", "div.": "DIVI",
    "divs.": "DIVI", "divs": "DIVI", "d": "DIVI",
    # CORM
    "corm": "CORM", "corms": "CORM",
    # RHIZ
    "rhiz": "RHIZ",
    # LAYE
    "laye": "LAYE", "layers": "LAYE",
    # TUBE (tubers)
    "tuber": "TUBE", "tube": "TUBE", "tub": "TUBE",
    # BRPL (bare-root plants)
    "brpl": "BRPL", "brph": "BRPL", "bbpl": "BRPL",
    # Other
    "offset": "DIVI", "clum": "DIVI",
    "store": "SEED", "srlg": "SEED",
    "many": "SEED", "unkw": "SEED", "wht": "SEED",
}


def normalize_received_as(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, received_as FROM extractions WHERE received_as IS NOT NULL AND received_as != ''"
    ).fetchall()
    updated = 0
    for row in rows:
        original = row["received_as"]
        stripped = original.strip()
        # Take first token only — rest is usually quantity bleed from adjacent field
        tokens = re.split(r'[\s/,]+', stripped)
        first = tokens[0].lower().rstrip('.')
        # If first token is purely numeric, it's a quantity — use second token
        if re.fullmatch(r'\d+', first) and len(tokens) > 1:
            first = tokens[1].lower().rstrip('.')
        # Strip leading digits (quantity prefix like "4SEED" → "seed")
        first_alpha = re.sub(r'^\d+', '', first)
        # Strip trailing digits (quantity suffix like "URCU124" → "urcu")
        first_no_trail = re.sub(r'\d+$', '', first_alpha) if first_alpha else ''
        # Try lookups in order: exact first token, then without trailing digits
        lookup = None
        for candidate in (first, first_alpha, first_no_trail):
            if candidate and candidate in RECEIVED_AS_MAP:
                lookup = candidate
                break
        if lookup and lookup in RECEIVED_AS_MAP:
            normalized = RECEIVED_AS_MAP[lookup]
        elif re.fullmatch(r'\d+\+?', stripped):
            normalized = "SEED"
        else:
            normalized = stripped.upper()
        if normalized != original:
            conn.execute("UPDATE extractions SET received_as = ? WHERE id = ?",
                        (normalized, row["id"]))
            updated += 1
    conn.commit()
    return updated


# --- Wanted For Area: Uppercase + OCR fixes ---

WANTED_AREA_FIXES = {
    "IA-NA": "1A-NA",
    "IA-AS": "1A-AS",
    "IA-EU": "1A-EU",
    "IA-AF": "1A-AF",
    "IA-AA": "1A-AA",
    "IA-AM": "1A-AM",
    "IA-SA": "1A-SA",
    "IA-1A": "1A-1A",
    "IA-BF": "1A-BF",
    "IA-E4": "1A-E4",
    "IA-5A": "1A-5A",
}


def normalize_wanted_for_area(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, wanted_for_area FROM extractions "
        "WHERE wanted_for_area IS NOT NULL AND wanted_for_area != ''"
    ).fetchall()
    updated = 0
    for row in rows:
        original = row["wanted_for_area"]
        normalized = original.strip().upper()
        if normalized in WANTED_AREA_FIXES:
            normalized = WANTED_AREA_FIXES[normalized]
        if normalized != original:
            conn.execute("UPDATE extractions SET wanted_for_area = ? WHERE id = ?",
                        (normalized, row["id"]))
            updated += 1
    conn.commit()
    return updated


# --- Drop fields: present_location, labels_requested ---

def drop_fields(conn: sqlite3.Connection) -> int:
    count = 0
    for field in ("present_location", "labels_requested"):
        result = conn.execute(
            f"UPDATE extractions SET {field} = NULL "
            f"WHERE {field} IS NOT NULL AND {field} != ''"
        )
        count += result.rowcount
    conn.commit()
    return count


# --- Date Received: Normalize to ISO (YYYY-MM-DD) ---

# D/M/Y with slashes, spaces, or dashes
DATE_SLASH_RE = re.compile(r'^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})$')
DATE_SPACE_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+['\"]?(\d{2,4})$")
DATE_DASH_DMY_RE = re.compile(r'^(\d{1,2})-(\d{1,2})-(\d{2,4})$')
DATE_ISO_RE = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})$')
DATE_YMD_SLASH_RE = re.compile(r'^(\d{4})/(\d{1,2})/(\d{1,2})$')
DATE_DOT_RE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$')
DATE_6DIGIT_RE = re.compile(r'^(\d{2})(\d{2})(\d{2})$')
# Quantity field bleeding into date — take last 3 numbers as D M Y
DATE_4NUM_RE = re.compile(r'^\d{1,2}\s+(\d{1,2})\s+(\d{1,2})\s+(\d{2,4})$')
# Merged month+year: "18-1996" (D-MYY) or "6 197" (D MYY) where space was lost
DATE_D_DASH_MYY_RE = re.compile(r'^(\d{1,2})-(\d{3,4})$')
DATE_D_SPACE_MYY_RE = re.compile(r'^(\d{1,2})\s+(\d{3})$')

MONTH_NAMES = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'jly': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

# "8 FEB 88", "22 FEB 88", "30 MAR 87"
DATE_D_MON_Y_RE = re.compile(
    r"^(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|jly|aug|sep|oct|nov|dec)[a-z]*\.?\s+['\"]?(\d{2,4})$",
    re.IGNORECASE,
)
# "FEB 02 2024", "NOV 15 2016", "NOV 01 2016"
DATE_MON_D_Y_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|jly|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})[,.]?\s+['\"]?(\d{2,4})$",
    re.IGNORECASE,
)
# "9 NOV 2006", "6 OCT 86"
DATE_D_MON_Y2_RE = re.compile(
    r"^(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|jly|aug|sep|oct|nov|dec)[a-z]*\.?\s*[,.]?\s*['\"]?(\d{2,4})$",
    re.IGNORECASE,
)
# Partial: "12/88", "12 86" (month/year only — store as YYYY-MM-01)
DATE_PARTIAL_RE = re.compile(r"^(\d{1,2})\s*[/ ]\s*['\"]?(\d{2,4})$")
# "Oct 2017", "June 2017", "Mar 98"
DATE_MON_Y_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|jly|aug|sep|oct|nov|dec)[a-z]*\.?\s+['\"]?(\d{2,4})$",
    re.IGNORECASE,
)
# "28 AUG-87"
DATE_D_MON_DASH_Y_RE = re.compile(
    r"^(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|jly|aug|sep|oct|nov|dec)[a-z]*\.?-(\d{2,4})$",
    re.IGNORECASE,
)


def _expand_year(yy: str) -> int:
    y = int(yy)
    if y > 99:
        return y
    return 1900 + y if y > 30 else 2000 + y


def _to_iso(day: int, month: int, year: int) -> str | None:
    if month < 1 or month > 12:
        return None
    if day < 1 or day > 31:
        return None
    if year < 1900 or year > 2030:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_date(text: str) -> str | None:
    """Try all known date formats. Returns ISO string or None."""
    s = text.strip()
    # Strip punctuation bleed (apostrophes/backticks from adjacent card lines)
    s = s.replace("'", "").replace("`", "").replace("’", "")
    # Collapse multiple dashes to single (typewriter artifacts)
    s = re.sub(r'-{2,}', '-', s)
    # Strip trailing/leading dashes left by collapse
    s = s.strip('-').strip()

    if DATE_ISO_RE.match(s):
        return s

    # D/M/Y with slashes — but if day > 12, it's M/D/Y
    m = DATE_SLASH_RE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        if a > 12 and b <= 12:
            return _to_iso(a, b, year)  # a is day (M/D/Y where M>12 is impossible, so D/M/Y with big day)
        if b > 12 and a <= 12:
            return _to_iso(b, a, year)  # M/D/Y
        return _to_iso(a, b, year)  # ambiguous, assume D/M/Y

    # D M YY with spaces — swap to M/D/Y when "month" > 12
    m = DATE_SPACE_RE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        if a > 12 and b <= 12:
            return _to_iso(a, b, year)
        if b > 12 and a <= 12:
            return _to_iso(b, a, year)
        return _to_iso(a, b, year)

    # D-M-YY with dashes (not ISO — day first, short year)
    m = DATE_DASH_DMY_RE.match(s)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # "8 FEB 88", "22 FEB 88"
    m = DATE_D_MON_Y_RE.match(s)
    if m:
        day = int(m.group(1))
        month = MONTH_NAMES.get(m.group(2)[:3].lower(), 0)
        year = _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # "FEB 02 2024", "NOV 15 2016"
    m = DATE_MON_D_Y_RE.match(s)
    if m:
        month = MONTH_NAMES.get(m.group(1)[:3].lower(), 0)
        day = int(m.group(2))
        year = _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # "9 NOV 2006" (same as D_MON_Y but catches more patterns)
    m = DATE_D_MON_Y2_RE.match(s)
    if m:
        day = int(m.group(1))
        month = MONTH_NAMES.get(m.group(2)[:3].lower(), 0)
        year = _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # "28 AUG-87"
    m = DATE_D_MON_DASH_Y_RE.match(s)
    if m:
        day = int(m.group(1))
        month = MONTH_NAMES.get(m.group(2)[:3].lower(), 0)
        year = _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # "Oct 2017", "June 2017" → YYYY-MM-01
    m = DATE_MON_Y_RE.match(s)
    if m:
        month = MONTH_NAMES.get(m.group(1)[:3].lower(), 0)
        year = _expand_year(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2030:
            return f"{year:04d}-{month:02d}-01"

    # Y/M/D with slashes: "2014/12/08"
    m = DATE_YMD_SLASH_RE.match(s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _to_iso(day, month, year)

    # D.M.Y with dots: "20.03.01"
    m = DATE_DOT_RE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        if a > 12 and b <= 12:
            return _to_iso(a, b, year)
        if b > 12 and a <= 12:
            return _to_iso(b, a, year)
        return _to_iso(a, b, year)

    # 6-digit concatenated: "200301" as DDMMYY
    m = DATE_6DIGIT_RE.match(s)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        return _to_iso(day, month, year)

    # 4-number field bleed: quantity bled into date, take last 3 as D M Y
    m = DATE_4NUM_RE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), _expand_year(m.group(3))
        if a > 12 and b <= 12:
            return _to_iso(a, b, year)
        if b > 12 and a <= 12:
            return _to_iso(b, a, year)
        return _to_iso(a, b, year)

    # Merged month+year: "18-1996" → D=18, M=1, Y=96 (OCR merged "1 96")
    for pat in (DATE_D_DASH_MYY_RE, DATE_D_SPACE_MYY_RE):
        m = pat.match(s)
        if m:
            day = int(m.group(1))
            merged = m.group(2)
            result = None
            # Try splits: 1-digit month + rest, 2-digit month + rest
            for split in (1, 2):
                if len(merged) > split:
                    month = int(merged[:split])
                    year_part = merged[split:]
                    # Use last 2 digits as year if year_part is 3+ digits
                    if len(year_part) >= 2:
                        year = _expand_year(year_part[-2:])
                        result = _to_iso(day, month, year)
                        if result:
                            break
            if result:
                return result

    # Partial: "12/88", "12 86" → YYYY-MM-01
    m = DATE_PARTIAL_RE.match(s)
    if m:
        month_or_day = int(m.group(1))
        year = _expand_year(m.group(2))
        if 1 <= month_or_day <= 12 and 1900 <= year <= 2030:
            return f"{year:04d}-{month_or_day:02d}-01"

    return None


def normalize_date_received(conn: sqlite3.Connection) -> tuple[int, int]:
    """Returns (updated, skipped) counts."""
    rows = conn.execute(
        "SELECT id, date_received FROM extractions "
        "WHERE date_received IS NOT NULL AND date_received != ''"
    ).fetchall()
    updated = 0
    skipped = 0
    for row in rows:
        original = row["date_received"].strip()

        if DATE_ISO_RE.match(original):
            continue

        iso = _parse_date(original)
        if iso and iso != original:
            conn.execute("UPDATE extractions SET date_received = ? WHERE id = ?",
                        (iso, row["id"]))
            updated += 1
        elif not iso:
            skipped += 1

    conn.commit()
    return updated, skipped


# --- Accession numbers: strip provenance annotations, reclassify format ---

PROVENANCE_TAIL_RE = re.compile(r"\*.*$")
LEGACY_RE = re.compile(r"^\d{5,6}-\d{3,4}-\d{2,4}(?:\.\d{1,2})?$")
MODERN_RE = re.compile(r"^\d{4}-\d{3,5}(?:\.\d{1,2})?$")


def _classify_accession(accession: str) -> str:
    if MODERN_RE.fullmatch(accession):
        return "modern_item" if "." in accession else "modern"
    if LEGACY_RE.fullmatch(accession):
        return "legacy_item" if "." in accession else "legacy"
    return "unknown"


def normalize_accession_numbers(conn: sqlite3.Connection) -> tuple[int, int]:
    """Strip provenance annotations and reclassify format_type. Returns (updated, reclassified)."""
    rows = conn.execute(
        "SELECT id, accession_number, normalized_accession_number, format_type "
        "FROM accession_numbers WHERE accession_number IS NOT NULL"
    ).fetchall()
    updated = 0
    reclassified = 0
    for row in rows:
        raw = row["accession_number"]
        old_norm = row["normalized_accession_number"]
        old_fmt = row["format_type"]

        new_norm = raw.replace(" ", "").upper()
        new_norm = PROVENANCE_TAIL_RE.sub("", new_norm)
        new_fmt = _classify_accession(new_norm)

        if new_norm != old_norm or new_fmt != old_fmt:
            conn.execute(
                "UPDATE accession_numbers SET normalized_accession_number = ?, format_type = ? WHERE id = ?",
                (new_norm, new_fmt, row["id"]),
            )
            updated += 1
            if new_fmt != old_fmt:
                reclassified += 1
    conn.commit()
    return updated, reclassified


# --- Run all ---

def normalize_all(conn: sqlite3.Connection, verbose: bool = False) -> dict:
    results = {}

    n = normalize_family(conn)
    results["family"] = n
    if verbose:
        print(f"  family → Title Case: {n} updated")

    n = normalize_received_as(conn)
    results["received_as"] = n
    if verbose:
        print(f"  received_as → canonical: {n} updated")

    n = normalize_wanted_for_area(conn)
    results["wanted_for_area"] = n
    if verbose:
        print(f"  wanted_for_area → uppercase + OCR fix: {n} updated")

    n = drop_fields(conn)
    results["dropped_fields"] = n
    if verbose:
        print(f"  present_location + labels_requested → NULL: {n} cleared")

    updated, skipped = normalize_date_received(conn)
    results["date_received_updated"] = updated
    results["date_received_skipped"] = skipped
    if verbose:
        print(f"  date_received → ISO: {updated} updated, {skipped} skipped")

    updated, reclassified = normalize_accession_numbers(conn)
    results["accession_numbers_updated"] = updated
    results["accession_numbers_reclassified"] = reclassified
    if verbose:
        print(f"  accession_numbers → strip provenance, reclassify: {updated} updated, {reclassified} reclassified")

    return results
