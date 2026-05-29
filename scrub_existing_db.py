"""One-time pass to redact PII from already-extracted rows.

The privacy_redaction module became the canonical PII rule after rows had
already been written to cards.db by the in-flight qwen2.5vl:7B run. This
script walks `extractions`, applies the same redactor to PII-prone fields,
writes the redacted form back into the canonical column, copies the original
into the `*_raw` shadow column, and logs every match to the `redactions`
audit table.

Idempotent: rows whose `*_raw` column is already populated are skipped, so
re-running the script after tuning regexes only touches rows that need it.

Usage:
    python scrub_existing_db.py [--db cards.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

from post_processing import PII_PRONE_FIELDS
from privacy_redaction import redact


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def scrub(db_path: str, dry_run: bool = False) -> dict:
    """Run the scrub. Returns a per-field count summary."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    fields_csv = ", ".join(PII_PRONE_FIELDS)
    raw_csv = ", ".join(f"{f}_raw" for f in PII_PRONE_FIELDS)
    rows = conn.execute(
        f"SELECT id, {fields_csv}, {raw_csv} FROM extractions"
    ).fetchall()

    summary: dict = {field: {"rows_changed": 0, "matches": 0} for field in PII_PRONE_FIELDS}
    summary["rows_scanned"] = len(rows)
    summary["rows_with_any_match"] = 0

    for row in rows:
        ext_id = row["id"]
        row_had_any_match = False

        for field in PII_PRONE_FIELDS:
            value = row[field]
            raw_already = row[f"{field}_raw"]

            # Skip rows already scrubbed for this field (idempotency).
            if raw_already is not None:
                continue
            if not isinstance(value, str) or not value:
                continue

            new_value, matches = redact(value)
            if not matches:
                continue

            row_had_any_match = True
            summary[field]["rows_changed"] += 1
            summary[field]["matches"] += len(matches)

            if dry_run:
                continue

            conn.execute(
                f"UPDATE extractions SET {field} = ?, {field}_raw = ? WHERE id = ?",
                (new_value, value, ext_id),
            )
            for r in matches:
                conn.execute(
                    "INSERT INTO redactions "
                    "(extraction_id, field, category, original, start_offset, end_offset, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ext_id, field, r.category, r.original, r.start, r.end, _now_iso()),
                )

        if row_had_any_match:
            summary["rows_with_any_match"] += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return summary


def _print_summary(summary: dict, dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Rows scanned: {summary['rows_scanned']}")
    print(f"{prefix}Rows with any redaction: {summary['rows_with_any_match']}")
    for field in PII_PRONE_FIELDS:
        s = summary[field]
        print(f"{prefix}  {field}: {s['rows_changed']} rows changed, {s['matches']} matches")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="cards.db", help="Path to cards.db")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args(argv)

    summary = scrub(args.db, dry_run=args.dry_run)
    _print_summary(summary, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
