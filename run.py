#!/usr/bin/env python3
"""CLI entry point for propagation card reader."""

import argparse
import csv
import os
import sys

from schema import init_db, get_db, now_iso
from inventory import build_inventory
from worker import process_batch


DEFAULT_DB = "cards.db"
DEFAULT_OLLAMA = "http://192.168.1.120:11434"
DEFAULT_MODEL = "qwen2.5vl:3b"
DEFAULT_DPI = 100


def cmd_inventory(args):
    """Scan PDFs and build card inventory."""
    pdf_dir = args.pdf_dir
    db_path = args.db
    
    if not os.path.isdir(pdf_dir):
        print(f"Error: PDF directory not found: {pdf_dir}")
        sys.exit(1)
    
    init_db(db_path)
    conn = get_db(db_path)
    
    # Create a processing run
    cur = conn.execute(
        "INSERT INTO processing_runs (started_at, dpi, model, notes) VALUES (?, ?, ?, ?)",
        (now_iso(), args.dpi, args.model, f"inventory scan of {pdf_dir}")
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    build_inventory(pdf_dir, db_path, run_id)
    print(f"\nRun ID: {run_id}")


def cmd_process(args):
    """Process pending cards through Ollama vision LLM."""
    db_path = args.db
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found: {db_path}")
        print("Run 'inventory' first to scan PDFs.")
        sys.exit(1)
    
    init_db(db_path)
    conn = get_db(db_path)
    
    # Create a processing run
    cur = conn.execute(
        "INSERT INTO processing_runs (started_at, dpi, model, notes) VALUES (?, ?, ?, ?)",
        (now_iso(), args.dpi, args.model, f"processing batch={args.batch}")
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    process_batch(
        db_path=db_path,
        run_id=run_id,
        ollama_url=args.ollama,
        model=args.model,
        dpi=args.dpi,
        batch_size=args.batch,
    )


def cmd_status(args):
    """Show processing status summary."""
    db_path = args.db
    
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return
    
    conn = get_db(db_path)
    
    total = conn.execute("SELECT COUNT(*) as cnt FROM cards").fetchone()["cnt"]
    if total == 0:
        print("No cards in database.")
        conn.close()
        return
    
    pending = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='pending'").fetchone()["cnt"]
    processing = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='processing'").fetchone()["cnt"]
    success = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='success'").fetchone()["cnt"]
    failed = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='failed'").fetchone()["cnt"]
    error = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='error'").fetchone()["cnt"]
    
    # Average processing time from extractions
    avg_row = conn.execute(
        "SELECT AVG(processing_time_s) as avg_time FROM extractions"
    ).fetchone()
    avg_time = avg_row["avg_time"]
    
    print(f"\n--- Card Processing Status ---")
    print(f"Total cards:  {total}")
    print(f"  Pending:    {pending}")
    print(f"  Processing: {processing}")
    print(f"  Success:    {success}")
    print(f"  Failed:     {failed}")
    print(f"  Error:      {error}")
    
    completed = success + failed + error
    if completed > 0:
        success_rate = (success / completed) * 100
        print(f"\nSuccess rate: {success_rate:.1f}% ({success}/{completed})")
    
    if avg_time is not None:
        print(f"Avg time/card: {avg_time:.1f}s")
        if pending > 0:
            est_remaining = pending * avg_time
            mins = est_remaining / 60
            if mins > 60:
                print(f"Est. remaining: {mins/60:.1f} hours ({pending} cards)")
            else:
                print(f"Est. remaining: {mins:.1f} minutes ({pending} cards)")
    
    conn.close()


def cmd_export(args):
    """Export results to CSV."""
    db_path = args.db
    output = args.output
    
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return
    
    conn = get_db(db_path)
    
    rows = conn.execute("""
        SELECT 
            c.pdf_path,
            c.page_num,
            a.accession_number,
            e.botanical_name,
            e.propagation_text,
            e.processing_time_s,
            c.status
        FROM cards c
        LEFT JOIN extractions e ON e.card_id = c.id
        LEFT JOIN accession_numbers a ON a.extraction_id = e.id
        ORDER BY c.pdf_path, c.page_num, a.position
    """).fetchall()
    
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pdf_file", "page_num", "accession_number",
            "botanical_name", "propagation_text", "processing_time_s", "status"
        ])
        for row in rows:
            pdf_file = os.path.basename(row["pdf_path"]) if row["pdf_path"] else ""
            writer.writerow([
                pdf_file,
                row["page_num"],
                row["accession_number"] or "",
                row["botanical_name"] or "",
                row["propagation_text"] or "",
                f"{row['processing_time_s']:.1f}" if row["processing_time_s"] else "",
                row["status"],
            ])
    
    print(f"Exported {len(rows)} rows to {output}")
    conn.close()


def cmd_failures(args):
    """Show failed cards, optionally retry them."""
    db_path = args.db
    
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return
    
    conn = get_db(db_path)
    
    failed = conn.execute(
        "SELECT * FROM cards WHERE status IN ('failed', 'error') ORDER BY pdf_path, page_num"
    ).fetchall()
    
    if not failed:
        print("No failed cards.")
        conn.close()
        return
    
    print(f"\n--- Failed Cards ({len(failed)}) ---")
    for card in failed:
        pdf_name = os.path.basename(card["pdf_path"])
        print(f"  {pdf_name} p{card['page_num']} [{card['status']}]: {card['error_message']}")
    
    if args.retry:
        conn.execute(
            "UPDATE cards SET status = 'pending', error_message = NULL WHERE status IN ('failed', 'error')"
        )
        conn.commit()
        print(f"\nReset {len(failed)} cards back to 'pending'.")
    
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Propagation Card Reader — Local Vision LLM OCR"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    
    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB})")
    common.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    common.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"DPI for image extraction (default: {DEFAULT_DPI})")
    
    # inventory
    inv = sub.add_parser("inventory", parents=[common], help="Scan PDFs and build card inventory")
    inv.add_argument("--pdf-dir", required=True, help="Directory containing PDF files")
    inv.set_defaults(func=cmd_inventory)
    
    # process
    proc = sub.add_parser("process", parents=[common], help="Process pending cards")
    proc.add_argument("--ollama", default=DEFAULT_OLLAMA, help=f"Ollama URL (default: {DEFAULT_OLLAMA})")
    proc.add_argument("--batch", type=int, default=None, help="Max cards to process (default: all)")
    proc.set_defaults(func=cmd_process)
    
    # status
    st = sub.add_parser("status", parents=[common], help="Show processing status")
    st.set_defaults(func=cmd_status)
    
    # export
    exp = sub.add_parser("export", parents=[common], help="Export results to CSV")
    exp.add_argument("--output", default="results.csv", help="Output CSV path (default: results.csv)")
    exp.set_defaults(func=cmd_export)
    
    # failures
    fail = sub.add_parser("failures", parents=[common], help="Show/retry failed cards")
    fail.add_argument("--retry", action="store_true", help="Reset failed cards back to pending")
    fail.set_defaults(func=cmd_failures)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
