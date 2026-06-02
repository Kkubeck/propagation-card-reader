"""Recover botanical names from accession numbers, and report recoverability.

When a card's name region is cropped or illegible but its accession number is
readable, the canonical taxon is recoverable by exact lookup against the
authoritative index (rag_accessions) — the accession is the primary key, so the
database name beats any handwriting OCR. This tool wraps the existing
post_processing.validate_against_rag (normalize-then-join lookup; no new
matching logic) over the extractions already in a cards.db.

Two actions:
  --report (default, read-only): classify each selected extraction's accession
      as resolved / unresolved / none, and — where the card also carries an
      OCR'd name — measure OCR-name vs database-name binomial agreement.
  --apply: where botanical_name is missing/empty AND the accession resolves,
      fill it from the database and stamp botanical_name_source. Existing OCR
      names are NEVER overwritten (kept for comparison / provenance).

Accessions are read from the accession_numbers junction table (primary =
position 0), falling back to extractions.accession_number.
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from schema import get_db, now_iso  # noqa: E402
from schema_migrations import migrate  # noqa: E402
from post_processing import validate_against_rag  # noqa: E402


SELECT_SQL = {
    "success": "c.status = 'success'",
    "all": "1=1",
}


def primary_accession(conn, extraction_id, fallback):
    """Position-0 accession from the junction table, else the scalar fallback."""
    row = conn.execute(
        "SELECT accession_number FROM accession_numbers "
        "WHERE extraction_id = ? ORDER BY position LIMIT 1",
        (extraction_id,),
    ).fetchone()
    acc = row["accession_number"] if row and row["accession_number"] else fallback
    return (acc or "").strip() or None


def binomial(name):
    """Lowercased 'genus species' for agreement comparison (drops author/infra)."""
    if not name:
        return ""
    return " ".join(str(name).strip().lower().split()[:2])


def iter_targets(conn, where, limit):
    # extractions.accession_number is a later column — older dbs lack it, so
    # select it only when present (keeps --report read-only, no migration).
    has_acc_col = any(
        row["name"] == "accession_number"
        for row in conn.execute("PRAGMA table_info(extractions)")
    )
    acc_col = "e.accession_number" if has_acc_col else "NULL AS accession_number"
    sql = (
        f"SELECT e.id AS ext_id, e.botanical_name, {acc_col} "
        "FROM extractions e JOIN cards c ON c.id = e.card_id "
        f"WHERE {where} ORDER BY e.id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="cards.db", help="cards.db to read/update")
    ap.add_argument("--rag-db", default="rag.db", help="RAG index (rag_accessions)")
    ap.add_argument("--select", choices=list(SELECT_SQL), default="success",
                    help="Extraction set (default: success)")
    ap.add_argument("--where", help="Custom SQL WHERE (overrides --select)")
    ap.add_argument("--limit", type=int, help="Cap rows (sampling)")
    ap.add_argument("--apply", action="store_true", help="Back-fill missing names (default: report only)")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"Error: db not found: {args.db}"); sys.exit(1)
    if not Path(args.rag_db).exists():
        print(f"Error: rag db not found: {args.rag_db}"); sys.exit(1)

    if args.apply:
        migrate(args.db)  # ensure botanical_name_source column exists

    where = args.where or SELECT_SQL[args.select]
    conn = get_db(args.db)
    rows = iter_targets(conn, where, args.limit)

    classes = Counter()           # resolved / unresolved / no_accession
    agree = both = 0              # name-agreement among resolved+OCR-named cards
    backfillable = 0              # resolved + name missing (the recovery win)
    to_fill = []                  # (ext_id, db_name) for --apply

    for r in rows:
        acc = primary_accession(conn, r["ext_id"], r["accession_number"])
        ocr_name = (r["botanical_name"] or "").strip()
        if not acc:
            classes["no_accession"] += 1
            continue
        match = validate_against_rag(acc, args.rag_db)
        if not match:
            classes["unresolved"] += 1
            continue
        classes["resolved"] += 1
        db_name = match.get("taxon_name_full") or match.get("taxon_name")
        if ocr_name:
            both += 1
            if binomial(ocr_name) == binomial(match.get("taxon_name") or db_name):
                agree += 1
        else:
            backfillable += 1
            if db_name:
                to_fill.append((r["ext_id"], db_name))

    total = sum(classes.values())
    print(f"\n=== Accession recovery report ({total} extractions) ===")
    for k in ("resolved", "unresolved", "no_accession"):
        n = classes[k]
        print(f"  {k:<13} {n:>6}  {n / total:.1%}" if total else f"  {k}: 0")
    print(f"\n  Name back-fillable (resolved + name missing): {backfillable}")
    if both:
        print(f"  OCR-name vs DB-name agreement (resolved + OCR named): "
              f"{agree}/{both} = {agree / both:.1%} binomial match")

    if not args.apply:
        print(f"\nDRY RUN. {len(to_fill)} names would be back-filled. Re-run with --apply.")
        conn.close()
        return

    for ext_id, db_name in to_fill:
        conn.execute(
            "UPDATE extractions SET botanical_name = ?, botanical_name_source = 'accession_lookup' "
            "WHERE id = ?",
            (db_name, ext_id),
        )
    conn.commit()
    conn.close()
    print(f"\nBack-filled {len(to_fill)} botanical names (botanical_name_source='accession_lookup').")


if __name__ == "__main__":
    main()
