"""Multi-pass convergence experiment for the stochastic-retry paper angle.

Runs the SAME cards through the model K independent times and records, per pass,
whether the read parsed (status) and what it extracted (accession numbers,
botanical name). Two questions it answers:

  1. Convergence curve — what fraction of a hard set succeeds at least once
     within the first k passes? (The "patience as affordance" figure.)
  2. Answer stability — for cards that succeed more than once, how often does
     the primary accession number agree across passes? (Is one pass an answer,
     or just a sample?)

It is READ-ONLY against the source cards.db (renders images, reads front
context) and writes results to a separate CSV, so it never touches production
extractions. Reuses the production prompt/Ollama/parse helpers.

Examples:
    # 5 passes over the resistant core (failed+error fronts), production mode
    python scripts/convergence_experiment.py --db cards.db --passes 5 \
        --model qwen2.5vl:7b --mode rag_prompt --rag-db rag.db --config config.yaml

    # stability check: re-read cards that already succeeded
    python scripts/convergence_experiment.py --db cards.db --passes 5 \
        --select success --limit 100

    # temperature sweep input (run several with different --temperature)
    python scripts/convergence_experiment.py --db cards.db --temperature 0.4 \
        --out conv_t04.csv
"""
import argparse
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from schema import get_db  # noqa: E402
from rag_config import load_config  # noqa: E402
from rag_prompt import build_prompt, build_back_prompt  # noqa: E402
from worker import extract_page_image  # noqa: E402
from rag_worker import call_ollama_with_prompt, parse_json_response  # noqa: E402
from filename_parser import parse_filename  # noqa: E402


# Selection presets. Backs are excluded by default — the convergence study is
# about front/single-card reads; backs use a different prompt + front context.
SELECT_SQL = {
    "resistant": "status IN ('failed','error') AND (card_face IS NULL OR card_face='front')",
    "success": "status = 'success' AND (card_face IS NULL OR card_face='front')",
    "all": "(card_face IS NULL OR card_face='front')",
}

CSV_COLUMNS = [
    "card_id", "pdf_file", "page_num", "pass_num", "status",
    "primary_accession", "all_accessions", "botanical_name",
    "processing_time_s", "error_message",
]


def load_targets(conn, where, limit):
    sql = f"SELECT * FROM cards WHERE {where} ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def front_context_for_back(conn, card):
    """Front-side context for a duplex back (mirrors RAGWorker._load_front_context)."""
    row = conn.execute(
        """SELECT e.botanical_name, e.family, e.accession_number, e.propagation_text
           FROM cards c JOIN extractions e ON e.card_id = c.id
           WHERE c.pdf_path=? AND c.card_face='front' AND c.pair_id=? AND c.status='success' LIMIT 1""",
        (card["pdf_path"], card["pair_id"]),
    ).fetchone()
    if not row:
        return None
    prop = row["propagation_text"] or ""
    return {"botanical_name": row["botanical_name"], "family": row["family"],
            "accession_number": row["accession_number"], "propagation_tail": prop[-200:]}


def build_prompt_for_card(conn, card, mode, context_builder, rag_db_path):
    """Return the prompt text for a card, matching the production pipeline."""
    if card["card_face"] == "back":
        return build_back_prompt(front_context_for_back(conn, card))
    if mode == "rag_prompt" and context_builder is not None:
        hints = parse_filename(os.path.basename(card["pdf_path"]), rag_db_path)
        ctx = context_builder.build_context(hints)["context_text"]
        return build_prompt(ctx, mode="rag_prompt")
    return build_prompt("", mode="ocr_only")


def extract_fields(data):
    """Pull (primary_accession, all_accessions, botanical_name) from parsed JSON."""
    prim = data.get("accession_number")
    if isinstance(prim, list):
        prim = prim[0] if prim else None
    prim = (str(prim).strip() or None) if prim else None

    allacc = data.get("all_accession_numbers") or ([prim] if prim else [])
    if isinstance(allacc, str):
        allacc = [allacc]
    allacc = [str(a).strip() for a in allacc if str(a).strip()]

    bn = data.get("botanical_name")
    if isinstance(bn, list):
        bn = " / ".join(str(x) for x in bn)
    bn = (str(bn).strip() or None) if bn else None
    return prim, " | ".join(allacc), bn


def run_one(conn, card, prompt_text, ollama_url, model, dpi, temperature):
    """One pass on one card. Returns a CSV row dict (never raises)."""
    row = {c: "" for c in CSV_COLUMNS}
    row["card_id"] = card["id"]
    row["pdf_file"] = os.path.basename(card["pdf_path"])
    row["page_num"] = card["page_num"]
    start = time.time()
    try:
        image_b64, _ = extract_page_image(card["pdf_path"], card["page_num"], dpi)
        raw = call_ollama_with_prompt(ollama_url, model, image_b64, prompt_text,
                                      temperature=temperature)
        data = parse_json_response(raw)
        prim, allacc, bn = extract_fields(data)
        row.update(status="success", primary_accession=prim or "",
                   all_accessions=allacc, botanical_name=bn or "")
    except Exception as exc:  # noqa: BLE001 — record, never abort the sweep
        # JSON parse failure => 'failed'; anything else (network/timeout) => 'error'.
        kind = "failed" if exc.__class__.__name__ == "JSONDecodeError" else "error"
        row.update(status=kind, error_message=f"{type(exc).__name__}: {exc}"[:300])
    row["processing_time_s"] = f"{time.time() - start:.1f}"
    return row


def summarize(rows, passes):
    """Print convergence curve + accession agreement from collected rows."""
    by_card = defaultdict(dict)          # card_id -> {pass_num: row}
    for r in rows:
        by_card[r["card_id"]][r["pass_num"]] = r
    n = len(by_card)
    if n == 0:
        print("No cards processed.")
        return

    print(f"\n=== Convergence over {n} cards, {passes} passes ===")
    print("pass  cum_success  cum_rate   (this-pass failed/error)")
    for k in range(1, passes + 1):
        succeeded_by_k = sum(
            any(card.get(p, {}).get("status") == "success" for p in range(1, k + 1))
            for card in by_card.values()
        )
        this = [card.get(k, {}).get("status") for card in by_card.values()]
        f = this.count("failed"); e = this.count("error")
        print(f"{k:>4}  {succeeded_by_k:>11}  {succeeded_by_k / n:>7.1%}   ({f} failed / {e} error)")

    # Accession agreement among cards that succeeded >=2 times.
    agreements = []
    for card in by_card.values():
        accs = [r["primary_accession"] for r in card.values()
                if r["status"] == "success" and r["primary_accession"]]
        if len(accs) >= 2:
            modal = Counter(accs).most_common(1)[0][1]
            agreements.append(modal / len(accs))
    print(f"\n=== Accession stability ({len(agreements)} cards succeeded >=2x) ===")
    if agreements:
        unanimous = sum(1 for a in agreements if a == 1.0)
        print(f"unanimous primary accession across passes: {unanimous}/{len(agreements)} "
              f"({unanimous / len(agreements):.1%})")
        print(f"mean modal-agreement rate: {sum(agreements) / len(agreements):.1%}")
    else:
        print("(not enough repeat successes to assess)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="cards.db", help="Source cards.db (read-only)")
    ap.add_argument("--out", default="convergence_results.csv", help="Output CSV (default: convergence_results.csv)")
    ap.add_argument("--passes", type=int, default=5, help="Independent passes per card (default: 5)")
    ap.add_argument("--select", choices=list(SELECT_SQL), default="resistant",
                    help="Card set: resistant=failed+error, success, all (default: resistant)")
    ap.add_argument("--where", help="Custom SQL WHERE clause (overrides --select)")
    ap.add_argument("--limit", type=int, help="Cap number of cards (sampling)")
    ap.add_argument("--ollama", default="http://localhost:11434", help="Ollama URL")
    ap.add_argument("--model", default="qwen2.5vl:7b", help="Model (default: qwen2.5vl:7b)")
    ap.add_argument("--dpi", type=int, default=100, help="Render DPI (default: 100)")
    ap.add_argument("--mode", choices=["ocr_only", "rag_prompt"], default="rag_prompt", help="Prompt mode")
    ap.add_argument("--rag-db", default="rag.db", help="RAG index (rag_prompt mode)")
    ap.add_argument("--config", default="config.yaml", help="Config YAML (rag_prompt mode)")
    ap.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature (default: 0.1)")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"Error: database not found: {args.db}")
        sys.exit(1)

    where = args.where or SELECT_SQL[args.select]
    conn = get_db(args.db)
    targets = load_targets(conn, where, args.limit)
    if not targets:
        print(f"No cards match: {where}")
        return
    print(f"Targets: {len(targets)} cards | passes={args.passes} | model={args.model} "
          f"| mode={args.mode} | temp={args.temperature}")

    context_builder = None
    rag_db_path = args.rag_db
    if args.mode == "rag_prompt":
        config = load_config(args.config)
        if not os.path.isabs(rag_db_path):
            rag_db_path = str((Path(args.config).resolve().parent / rag_db_path).resolve())
        if os.path.exists(rag_db_path):
            from rag_context_builder import RAGContextBuilder
            context_builder = RAGContextBuilder(rag_db_path, config)
        else:
            print(f"Warning: rag.db not found at {rag_db_path}; running baseline prompt instead.")

    rows = []
    # Stream to CSV as we go so a crash mid-sweep keeps the data.
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for p in range(1, args.passes + 1):
            t0 = time.time()
            ok = 0
            for card in targets:
                prompt_text = build_prompt_for_card(conn, card, args.mode, context_builder, rag_db_path)
                row = run_one(conn, card, prompt_text, args.ollama, args.model, args.dpi, args.temperature)
                row["pass_num"] = p
                writer.writerow(row)
                rows.append(row)
                ok += row["status"] == "success"
            fh.flush()
            print(f"pass {p}/{args.passes}: {ok}/{len(targets)} parsed  ({time.time() - t0:.0f}s)")

    conn.close()
    if context_builder is not None:
        context_builder.close()

    print(f"\nWrote {len(rows)} rows to {args.out}")
    summarize(rows, args.passes)


if __name__ == "__main__":
    main()
