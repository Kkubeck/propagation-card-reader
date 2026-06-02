"""Requeue duplex cards that an earlier pass marked 'excluded'.

Before duplex front/back routing existed, the worker stamped every duplex card
`duplex_flag=1` and set `status='excluded'`. Those cards are skipped by both
`process` (only touches 'pending') and `failures --retry' (only resets
'failed'/'error'), so they need to be flipped back by hand. This tool does that
safely, then re-runs front/back pairing so they are ready to `process`.

Dry-run by default — prints what it *would* do. Pass --apply to commit.

Usage:
    python scripts/requeue_duplex.py [--db cards.db]            # preview
    python scripts/requeue_duplex.py [--db cards.db] --apply    # do it
"""
import argparse
import sys
from pathlib import Path

# Project root on sys.path so we can import the package modules without installing.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from schema import get_db  # noqa: E402
from schema_migrations import migrate  # noqa: E402
from inventory import assign_duplex_pairing  # noqa: E402


# Cards the old pass parked: duplex by flag, and currently excluded.
EXCLUDED_DUPLEX_WHERE = "duplex_flag = 1 AND status = 'excluded'"


def _excluded_duplex_breakdown(conn):
    """Return (total, [(pdf_path, count), ...]) for excluded duplex cards."""
    total = conn.execute(
        f"SELECT COUNT(*) FROM cards WHERE {EXCLUDED_DUPLEX_WHERE}"
    ).fetchone()[0]
    per_pdf = conn.execute(
        f"""SELECT pdf_path, COUNT(*) AS n
            FROM cards WHERE {EXCLUDED_DUPLEX_WHERE}
            GROUP BY pdf_path ORDER BY pdf_path"""
    ).fetchall()
    return total, per_pdf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="cards.db", help="SQLite database path (default: cards.db)")
    ap.add_argument("--apply", action="store_true", help="Commit the change (default: dry-run preview)")
    args = ap.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Error: database not found: {db_path}")
        sys.exit(1)

    # Ensure duplex columns exist (older dbs predate them).
    migrate(db_path)

    conn = get_db(db_path)
    try:
        total, per_pdf = _excluded_duplex_breakdown(conn)

        print(f"Excluded duplex cards in {db_path}: {total}")
        for row in per_pdf:
            print(f"  {Path(row['pdf_path']).name:<40} {row['n']}")

        if total == 0:
            print("\nNothing to requeue.")
            return

        if not args.apply:
            print(f"\nDRY RUN — would set these {total} cards to 'pending' and re-run pairing.")
            print("Re-run with --apply to commit.")
            return

        conn.execute(
            f"UPDATE cards SET status = 'pending', excluded_reason = NULL "
            f"WHERE {EXCLUDED_DUPLEX_WHERE}"
        )
        conn.commit()
        print(f"\nRequeued {total} cards to 'pending'.")
    finally:
        conn.close()

    # Re-assign front/back pairing (reads page counts from the db — no PDFs
    # needed). Odd/unpairable duplex PDFs stay flagged; the worker re-excludes
    # them at process time.
    assign_duplex_pairing(db_path)

    # Show the resulting face split so the user can sanity-check before process.
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT card_face, COUNT(*) AS n FROM cards "
            "WHERE duplex_flag = 1 AND status = 'pending' GROUP BY card_face ORDER BY card_face"
        ).fetchall()
        print("\nPending duplex cards by face (NULL = odd/unpairable, will re-exclude):")
        for row in rows:
            print(f"  {str(row['card_face']):<6} {row['n']}")
    finally:
        conn.close()

    print("\nNext: python run.py process --db", db_path,
          "--ollama http://localhost:11434 --model qwen2.5vl:7b --mode rag_prompt --rag-db rag.db --config config.yaml")


if __name__ == "__main__":
    main()
