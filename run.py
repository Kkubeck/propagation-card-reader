#!/usr/bin/env python3
"""CLI entry point for propagation card reader."""

import argparse
import csv
import os
import sys
from pathlib import Path

from inventory import build_inventory
from rag_config import load_config
from rag_worker import RAGWorker
from schema import get_db, init_db, now_iso
from schema_migrations import migrate


DEFAULT_DB = "cards.db"
DEFAULT_OLLAMA = "http://192.168.1.120:11434"
DEFAULT_MODEL = "qwen2.5vl:7b"
DEFAULT_DPI = 100
DEFAULT_RAG_DB = "rag.db"
DEFAULT_CONFIG = "config.yaml"


def _create_processing_run(conn, args, note_text: str, pipeline_mode: str | None = None, prompt_version: str | None = None, rag_index_version: str | None = None):
    if pipeline_mode is None:
        cur = conn.execute(
            "INSERT INTO processing_runs (started_at, dpi, model, notes) VALUES (?, ?, ?, ?)",
            (now_iso(), args.dpi, args.model, note_text),
        )
        return cur.lastrowid

    cur = conn.execute(
        """
        INSERT INTO processing_runs (started_at, dpi, model, notes, pipeline_mode, prompt_version, rag_index_version)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (now_iso(), args.dpi, args.model, note_text, pipeline_mode, prompt_version, rag_index_version),
    )
    return cur.lastrowid


def _rag_index_version(rag_db_path: str) -> str | None:
    path = Path(rag_db_path)
    if not path.exists():
        return None
    stat = path.stat()
    return f"{path.name}:{int(stat.st_mtime)}"


def cmd_inventory(args):
    """Scan PDFs and build card inventory."""
    pdf_dir = args.pdf_dir
    db_path = args.db

    if not os.path.isdir(pdf_dir):
        print(f"Error: PDF directory not found: {pdf_dir}")
        sys.exit(1)

    init_db(db_path)
    # Ensure Phase-2 columns exist (incl. card_face/pair_id) before inventory,
    # since build_inventory runs duplex pairing which writes those columns.
    migrate(db_path)
    conn = get_db(db_path)

    run_id = _create_processing_run(conn, args, f"inventory scan of {pdf_dir}")
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
    # Always migrate: both modes now run through RAGWorker, whose duplex routing
    # depends on the card_face / pair_id columns added by migrate().
    migrate(db_path)

    requested_mode = args.mode
    effective_mode = requested_mode
    config = None
    rag_db_path = None
    prompt_version = None
    rag_index_version = None
    note_text = f"processing batch={args.batch}"

    if requested_mode == "rag_prompt":
        config = load_config(args.config)
        rag_db_path = args.rag_db or config.get("rag_db_path", DEFAULT_RAG_DB)
        if not os.path.isabs(rag_db_path):
            rag_db_path = str((Path(args.config).resolve().parent / rag_db_path).resolve())
        prompt_cfg = config.get("rag", {}).get("prompt", {})
        prompt_version = prompt_cfg.get("version", "v2.0-rag")
        rag_index_version = _rag_index_version(rag_db_path)
        if not os.path.exists(rag_db_path):
            print(f"Warning: rag.db not found at {rag_db_path}; falling back to ocr_only mode.")
            effective_mode = "ocr_only"
            rag_db_path = None
            prompt_version = prompt_cfg.get("baseline_version", "v1.0-baseline")
            note_text += f" | requested_mode=rag_prompt fallback_missing_rag_db"
        else:
            note_text += f" | mode=rag_prompt rag_db={rag_db_path}"
    else:
        note_text += " | mode=ocr_only"

    conn = get_db(db_path)
    run_id = _create_processing_run(
        conn,
        args,
        note_text,
        pipeline_mode=effective_mode,
        prompt_version=prompt_version,
        rag_index_version=rag_index_version,
    )
    conn.commit()
    conn.close()

    # Single worker for both modes. In ocr_only it skips retrieval (no rag.db
    # needed) but still applies duplex front/back routing.
    worker = RAGWorker(
        db_path=db_path,
        rag_db_path=rag_db_path,
        config=config or {},
        mode=effective_mode,
    )
    worker.process_batch(
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
    excluded = conn.execute("SELECT COUNT(*) as cnt FROM cards WHERE status='excluded'").fetchone()["cnt"]

    avg_row = conn.execute("SELECT AVG(processing_time_s) as avg_time FROM extractions").fetchone()
    avg_time = avg_row["avg_time"]

    print(f"\n--- Card Processing Status ---")
    print(f"Total cards:  {total}")
    print(f"  Pending:    {pending}")
    print(f"  Processing: {processing}")
    print(f"  Success:    {success}")
    print(f"  Failed:     {failed}")
    print(f"  Error:      {error}")
    print(f"  Excluded:   {excluded}")

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


def _merge_accession_strings(front_str, back_str):
    """Union two ' | '-joined accession strings, preserving order, no dupes."""
    seen = []
    for part in (front_str or "").split(" | ") + (back_str or "").split(" | "):
        p = part.strip()
        if p and p not in seen:
            seen.append(p)
    return " | ".join(seen)


def cmd_export(args):
    """Export results to CSV.

    Duplex backs are folded into their paired front (Option A): the back's
    propagation_text is appended to the front under a '— BACK —' separator and
    the back's accession numbers are unioned into all_accession_numbers. A back
    whose front is missing/failed is emitted standalone so its data is not lost.
    """
    db_path = args.db
    output = args.output

    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    conn = get_db(db_path)

    # All extraction field columns (matches schema.py EXTRACTION_FIELDS order)
    ext_fields = [
        "botanical_name", "family", "geocode", "received_as", "quantity",
        "date_received", "present_location", "wanted_for_area", "source",
        "source_info", "collector_number", "other_number", "labels_requested",
        "max_quantity", "parent_accession", "collection_info", "distribution",
        "accession_number", "propagation_text", "curators_info", "iris_data_entered",
    ]
    ext_select = ", ".join(f"e.{f}" for f in ext_fields)

    rows = conn.execute(
        f"""
        SELECT
            c.pdf_path,
            c.page_num,
            c.status,
            c.card_face,
            c.pair_id,
            e.processing_time_s,
            {ext_select},
            GROUP_CONCAT(a.accession_number, ' | ') AS all_accession_numbers
        FROM cards c
        LEFT JOIN extractions e ON e.card_id = c.id
        LEFT JOIN accession_numbers a ON a.extraction_id = e.id
        GROUP BY c.id
        ORDER BY c.pdf_path, c.page_num
        """
    ).fetchall()

    csv_headers = [
        "pdf_file", "page_num", "status", "processing_time_s",
    ] + ext_fields + ["all_accession_numbers"]

    def _row_dict(row):
        d = {f: (row[f] if row[f] is not None else "") for f in ext_fields}
        d["pdf_file"] = os.path.basename(row["pdf_path"]) if row["pdf_path"] else ""
        d["page_num"] = row["page_num"]
        d["status"] = row["status"]
        d["processing_time_s"] = f"{row['processing_time_s']:.1f}" if row["processing_time_s"] else ""
        d["all_accession_numbers"] = row["all_accession_numbers"] or ""
        return d

    # ORDER BY pdf_path, page_num guarantees each duplex front is seen before
    # its back (fronts are the first half of a duplex PDF's pages).
    fronts = {}   # (pdf_path, pair_id) -> emitted front row dict
    emitted = []

    for row in rows:
        face = row["card_face"]
        d = _row_dict(row)
        if face == "front":
            fronts[(row["pdf_path"], row["pair_id"])] = d
            emitted.append(d)
        elif face == "back":
            front = fronts.get((row["pdf_path"], row["pair_id"]))
            if front is None:
                # No paired front (front failed/missing) — emit standalone.
                d["status"] = f"{d['status']} (orphan back)"
                emitted.append(d)
                continue
            back_text = (d.get("propagation_text") or "").strip()
            if back_text:
                front_text = front.get("propagation_text") or ""
                front["propagation_text"] = (
                    f"{front_text}\n— BACK —\n{back_text}" if front_text else back_text
                )
            front["all_accession_numbers"] = _merge_accession_strings(
                front["all_accession_numbers"], d["all_accession_numbers"]
            )
        else:
            emitted.append(d)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)
        for d in emitted:
            writer.writerow([d.get(h, "") for h in csv_headers])

    print(f"Exported {len(emitted)} rows to {output}")
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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB})")
    common.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    common.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"DPI for image extraction (default: {DEFAULT_DPI})")

    inv = sub.add_parser("inventory", parents=[common], help="Scan PDFs and build card inventory")
    inv.add_argument("--pdf-dir", required=True, help="Directory containing PDF files")
    inv.set_defaults(func=cmd_inventory)

    proc = sub.add_parser("process", parents=[common], help="Process pending cards")
    proc.add_argument("--ollama", default=DEFAULT_OLLAMA, help=f"Ollama URL (default: {DEFAULT_OLLAMA})")
    proc.add_argument("--batch", type=int, default=None, help="Max cards to process (default: all)")
    proc.add_argument("--mode", choices=["ocr_only", "rag_prompt"], default="ocr_only", help="Pipeline mode (default: ocr_only)")
    proc.add_argument("--rag-db", default=DEFAULT_RAG_DB, help=f"RAG SQLite index path (default: {DEFAULT_RAG_DB})")
    proc.add_argument("--config", default=DEFAULT_CONFIG, help=f"Config YAML path (default: {DEFAULT_CONFIG})")
    proc.set_defaults(func=cmd_process)

    st = sub.add_parser("status", parents=[common], help="Show processing status")
    st.set_defaults(func=cmd_status)

    exp = sub.add_parser("export", parents=[common], help="Export results to CSV")
    exp.add_argument("--output", default="results.csv", help="Output CSV path (default: results.csv)")
    exp.set_defaults(func=cmd_export)

    fail = sub.add_parser("failures", parents=[common], help="Show/retry failed cards")
    fail.add_argument("--retry", action="store_true", help="Reset failed cards back to pending")
    fail.set_defaults(func=cmd_failures)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
