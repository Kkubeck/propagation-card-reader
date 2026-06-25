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
        "parsed_replicate_json", "parsed_other_sowings_json",
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

    if output.lower().endswith(".xlsx"):
        try:
            from openpyxl import Workbook
        except ImportError:
            print("openpyxl is required for Excel export: pip install openpyxl")
            conn.close()
            return
        wb = Workbook()
        ws = wb.active
        ws.title = "Card Extractions"
        ws.append(csv_headers)
        for d in emitted:
            ws.append([d.get(h, "") for h in csv_headers])
        wb.save(output)
    else:
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


def cmd_duplex(args):
    """Manage duplex card processing — show status, enable, or migrate."""
    db_path = args.db
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    from schema_migrations import migrate
    migrate(db_path)

    from inventory import assign_duplex_pairing
    assign_duplex_pairing(db_path)

    conn = get_db(db_path)

    if args.enable:
        updated = conn.execute(
            """UPDATE cards SET status = 'pending', excluded_reason = NULL
               WHERE duplex_flag = 1 AND status = 'excluded'
               AND card_face IS NOT NULL AND pair_id IS NOT NULL"""
        ).rowcount
        conn.commit()
        print(f"Enabled {updated} paired duplex cards for processing.")

    total = conn.execute("SELECT COUNT(*) FROM cards WHERE duplex_flag = 1").fetchone()[0]
    paired = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND card_face IS NOT NULL"
    ).fetchone()[0]
    unpaired = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND card_face IS NULL"
    ).fetchone()[0]
    fronts_pending = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND card_face = 'front' AND status = 'pending'"
    ).fetchone()[0]
    backs_pending = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND card_face = 'back' AND status = 'pending'"
    ).fetchone()[0]
    excluded = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND status = 'excluded'"
    ).fetchone()[0]
    processed = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE duplex_flag = 1 AND status = 'success'"
    ).fetchone()[0]

    print(f"\n--- Duplex Card Status ---")
    print(f"Total duplex pages:  {total}")
    print(f"  Paired:            {paired} ({paired // 2} front/back pairs)")
    print(f"  Unpaired:          {unpaired}")
    print(f"  Fronts pending:    {fronts_pending}")
    print(f"  Backs pending:     {backs_pending}")
    print(f"  Excluded:          {excluded}")
    print(f"  Processed:         {processed}")

    conn.close()


def cmd_other_sowings(args):
    """Detect and backfill OTHER SOWINGS table data from front-card propagation text."""
    import json
    from other_sowings_parser import has_other_sowings, parse_other_sowings

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    migrate(db_path)
    conn = get_db(db_path)

    rows = conn.execute("""
        SELECT e.id, e.propagation_text, e.botanical_name, e.parsed_other_sowings_json,
               c.pdf_path, c.page_num
        FROM extractions e JOIN cards c ON c.id = e.card_id
        WHERE c.status = 'success' AND e.propagation_text IS NOT NULL
    """).fetchall()

    detected = []
    total_records = 0
    for row in rows:
        if has_other_sowings(row["propagation_text"]):
            result = parse_other_sowings(row["propagation_text"])
            if result.records:
                detected.append((row, result))
                total_records += len(result.records)

    already = sum(1 for row, _ in detected if row["parsed_other_sowings_json"])
    pending = sum(1 for row, _ in detected if not row["parsed_other_sowings_json"])

    print(f"\n--- OTHER SOWINGS Tables ---")
    print(f"Total processed:          {len(rows)}")
    print(f"Cards with OTHER table:   {len(detected)}")
    print(f"Total sowing records:     {total_records}")
    print(f"  Already stored:         {already}")
    print(f"  Pending backfill:       {pending}")

    if args.verbose:
        for row, result in detected:
            pdf = os.path.basename(row["pdf_path"]) if row["pdf_path"] else "?"
            stored = "stored" if row["parsed_other_sowings_json"] else "NEW"
            print(f"\n  [{stored}] id={row['id']} | {pdf} p{row['page_num']} | {row['botanical_name']}")
            print(f"    Format: {result.format}, {len(result.records)} records")
            for rec in result.records:
                parts = []
                if rec.accession: parts.append(f"acc={rec.accession}")
                if rec.date_sown: parts.append(f"sow={rec.date_sown}")
                if rec.location: parts.append(f"loc={rec.location}")
                if rec.date_germ: parts.append(f"germ={rec.date_germ}")
                if rec.qty_germ: parts.append(f"qty_g={rec.qty_germ}")
                if rec.outcome: parts.append(f"outcome={rec.outcome}")
                print(f"      {', '.join(parts)}")

    if args.backfill and pending > 0:
        updated = 0
        for row, result in detected:
            if not row["parsed_other_sowings_json"]:
                conn.execute(
                    "UPDATE extractions SET parsed_other_sowings_json = ? WHERE id = ?",
                    (json.dumps(result.to_dict()), row["id"]),
                )
                updated += 1
        conn.commit()
        print(f"\nBackfilled {updated} cards with OTHER SOWINGS JSON.")

    conn.close()


def cmd_tables(args):
    """Detect and backfill card-back multi-sowing table data into parsed_table_json."""
    import json
    from table_parser import parse_table_text

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    migrate(db_path)
    conn = get_db(db_path)

    rows = conn.execute("""
        SELECT e.id, e.propagation_text, e.botanical_name, e.parsed_table_json,
               e.notes, c.pdf_path, c.page_num, c.id as card_id
        FROM extractions e JOIN cards c ON c.id = e.card_id
        WHERE c.status = 'success'
          AND e.notes LIKE '%back_mode=table_continuation%'
          AND e.propagation_text IS NOT NULL
    """).fetchall()

    detected = []
    total_table_rows = 0
    for row in rows:
        result = parse_table_text(row["propagation_text"])
        if result.rows:
            detected.append((row, result))
            total_table_rows += len(result.rows)

    already = sum(1 for row, _ in detected if row["parsed_table_json"])
    pending = sum(1 for row, _ in detected if not row["parsed_table_json"])

    print(f"\n--- Card-Back Multi-Sowing Tables ---")
    print(f"Table-continuation backs:  {len(rows)}")
    print(f"Cards with parsed rows:    {len(detected)}")
    print(f"Total table rows:          {total_table_rows}")
    print(f"  Already stored:          {already}")
    print(f"  Pending backfill:        {pending}")

    if args.verbose:
        for row, result in detected:
            pdf = os.path.basename(row["pdf_path"]) if row["pdf_path"] else "?"
            stored = "stored" if row["parsed_table_json"] else "NEW"
            print(f"\n  [{stored}] card_id={row['card_id']} | {pdf} p{row['page_num']} | {row['botanical_name'] or '?'}")
            print(f"    Format: {result.format}, {len(result.rows)} rows")
            for tr in result.rows:
                parts = []
                if tr.accession: parts.append(f"acc={tr.accession}")
                if tr.qty_sown: parts.append(f"qty={tr.qty_sown}")
                if tr.date_sown: parts.append(f"sow={tr.date_sown}")
                if tr.treatment: parts.append(f"trt={tr.treatment}")
                if tr.date_germ: parts.append(f"germ={tr.date_germ}")
                if tr.qty_germ: parts.append(f"qty_g={tr.qty_germ}")
                if tr.location: parts.append(f"loc={tr.location}")
                print(f"      {', '.join(parts)}")

    if args.backfill and pending > 0:
        updated = 0
        for row, result in detected:
            if not row["parsed_table_json"]:
                conn.execute(
                    "UPDATE extractions SET parsed_table_json = ? WHERE id = ?",
                    (json.dumps(result.to_dict()), row["id"]),
                )
                updated += 1
        conn.commit()
        print(f"\nBackfilled {updated} cards with table JSON.")

    conn.close()


def cmd_normalize(args):
    """Normalize extraction fields: family, received_as, wanted_for_area, dates.

    Run on a COPY of the original DB — this modifies the database in-place.
    All normalizations are idempotent (safe to run multiple times).
    """
    from normalizer import normalize_all

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    migrate(db_path)
    conn = get_db(db_path)

    verbose = getattr(args, "verbose", False)
    print(f"Normalizing {db_path}...")
    results = normalize_all(conn, verbose=verbose)

    total_changes = sum(v for v in results.values())
    print(f"\nTotal changes: {total_changes}")

    conn.close()


def cmd_replicates(args):
    """Detect multi-replicate cards and optionally backfill parsed_replicate_json."""
    import json
    from replicate_parser import is_multi_replicate, parse_replicates

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"No database found at {db_path}")
        return

    migrate(db_path)
    conn = get_db(db_path)

    rows = conn.execute("""
        SELECT e.id, e.propagation_text, e.botanical_name, e.parsed_replicate_json,
               c.pdf_path, c.page_num
        FROM extractions e JOIN cards c ON c.id = e.card_id
        WHERE c.status = 'success' AND e.propagation_text IS NOT NULL
    """).fetchall()

    detected = []
    for row in rows:
        if is_multi_replicate(row["propagation_text"]):
            result = parse_replicates(row["propagation_text"])
            if result.replicates:
                detected.append((row, result))

    already = sum(1 for row, _ in detected if row["parsed_replicate_json"])
    pending = sum(1 for row, _ in detected if not row["parsed_replicate_json"])

    print(f"\n--- Multi-Replicate Cards ---")
    print(f"Total processed:        {len(rows)}")
    print(f"Multi-replicate found:  {len(detected)}")
    print(f"  Already stored:       {already}")
    print(f"  Pending backfill:     {pending}")

    for row, result in detected:
        pdf = os.path.basename(row["pdf_path"]) if row["pdf_path"] else "?"
        reps = result.replicates
        stored = "stored" if row["parsed_replicate_json"] else "NEW"
        print(f"\n  [{stored}] id={row['id']} | {pdf} p{row['page_num']} | {row['botanical_name']}")
        print(f"    Format: {result.format}, {len(reps)} replicates")
        for rep in reps:
            print(f"    #{rep.replicate_id}: loc={rep.location}, trt={rep.treatment}")

    if args.backfill and pending > 0:
        updated = 0
        for row, result in detected:
            if not row["parsed_replicate_json"]:
                conn.execute(
                    "UPDATE extractions SET parsed_replicate_json = ? WHERE id = ?",
                    (json.dumps(result.to_dict()), row["id"]),
                )
                updated += 1
        conn.commit()
        print(f"\nBackfilled {updated} cards with replicate JSON.")

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
    exp.add_argument("--output", default="results.csv", help="Output path; use .xlsx extension for Excel (default: results.csv)")
    exp.set_defaults(func=cmd_export)

    fail = sub.add_parser("failures", parents=[common], help="Show/retry failed cards")
    fail.add_argument("--retry", action="store_true", help="Reset failed cards back to pending")
    fail.set_defaults(func=cmd_failures)

    dup = sub.add_parser("duplex", parents=[common], help="Manage duplex (front/back) card processing")
    dup.add_argument("--enable", action="store_true", help="Un-exclude paired duplex cards for processing")
    dup.set_defaults(func=cmd_duplex)

    rep = sub.add_parser("replicates", parents=[common], help="Detect and show multi-replicate cards")
    rep.add_argument("--backfill", action="store_true", help="Parse existing cards and store replicate JSON")
    rep.set_defaults(func=cmd_replicates)

    tbl = sub.add_parser("tables", parents=[common], help="Detect and backfill card-back multi-sowing tables")
    tbl.add_argument("--backfill", action="store_true", help="Parse and store table JSON")
    tbl.add_argument("--verbose", "-v", action="store_true", help="Show each card and its parsed rows")
    tbl.set_defaults(func=cmd_tables)

    oth = sub.add_parser("other-sowings", parents=[common], help="Detect and backfill OTHER SOWINGS table data")
    oth.add_argument("--backfill", action="store_true", help="Parse and store OTHER SOWINGS JSON")
    oth.add_argument("--verbose", "-v", action="store_true", help="Show each card and its parsed records")
    oth.set_defaults(func=cmd_other_sowings)

    norm = sub.add_parser("normalize", parents=[common], help="Normalize extraction fields (run on a COPY)")
    norm.add_argument("--verbose", "-v", action="store_true", help="Show per-field update counts")
    norm.set_defaults(func=cmd_normalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
