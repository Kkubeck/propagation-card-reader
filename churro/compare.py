"""Side-by-side comparison report: qwen (cards.db) vs CHURRO (churro_cards.db).

Reads both SQLite files, joins on (pdf_path, page_num), and emits a
Markdown report. The report is keyed by source PDF basename + page
number — that matches the audit conventions in
data/card-audit-report.md so a reader can cross-reference flagged
cards between the qwen audit and this comparison.

Invocation:
    python3 compare.py \\
        --qwen-db ../cards.db \\
        --churro-db churro_cards.db \\
        --output comparison.md

# ------------------------------------------------------------------
# Data definitions (HtDP)
# ------------------------------------------------------------------

# Pair is Compound{
#   pdf_basename: Str, page_num: Int>=0,
#   qwen_status: Str|None, churro_status: Str|None,
#   qwen_accession: Str|None, churro_accession: Str|None,
#   qwen_botanical: Str|None, churro_botanical: Str|None,
#   qwen_prop_len: Int|None,  churro_prop_len: Int|None,
#   qwen_time_s: Float|None,  churro_time_s: Float|None,
# }
# interp. one head-to-head row. *_status is None when that pipeline
#         never saw the card (asymmetric inventories).

# Agreement is one of:
#   "exact"     — non-empty equal strings
#   "differ"    — both non-empty, not equal
#   "qwen_only" — qwen had a value, CHURRO did not
#   "churro_only"
#   "both_empty"
# interp. coarse buckets for the summary stats table.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter
from typing import NamedTuple


class Pair(NamedTuple):
    pdf_basename: str
    page_num: int
    qwen_status: str | None
    churro_status: str | None
    qwen_accession: str | None
    churro_accession: str | None
    qwen_botanical: str | None
    churro_botanical: str | None
    qwen_prop_len: int | None
    churro_prop_len: int | None
    qwen_time_s: float | None
    churro_time_s: float | None


# ------------------------------------------------------------------
# DB readers
# ------------------------------------------------------------------

def _open(path: str) -> sqlite3.Connection:
    """Open a SQLite DB read-only-ish (no schema mutation).

    Signature: String -> sqlite3.Connection
    Purpose:   thin helper. Row factory set.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_qwen(db_path: str) -> dict[tuple[str, int], dict]:
    """Map (pdf_basename, page_num) -> qwen extraction summary.

    Signature: String -> Dict[(Str,Int), Dict]
    Purpose:   pull the fields we want to compare from cards.db.
    """
    conn = _open(db_path)
    rows = conn.execute(
        """
        SELECT c.pdf_path, c.page_num, c.status,
               e.botanical_name, e.accession_number,
               e.propagation_text, e.processing_time_s
        FROM cards c
        LEFT JOIN extractions e ON e.card_id = c.id
        """
    ).fetchall()
    conn.close()
    out: dict[tuple[str, int], dict] = {}
    for r in rows:
        key = (os.path.basename(r["pdf_path"] or ""), r["page_num"])
        out[key] = dict(r)
    return out


def load_churro(db_path: str) -> dict[tuple[str, int], dict]:
    """Map (pdf_basename, page_num) -> CHURRO extraction summary.

    Signature: String -> Dict[(Str,Int), Dict]
    """
    conn = _open(db_path)
    rows = conn.execute(
        """
        SELECT c.pdf_path, c.page_num, c.status,
               e.botanical_name, e.accession_number,
               e.propagation_text, e.processing_time_s
        FROM churro_cards c
        LEFT JOIN churro_extractions e ON e.card_id = c.id
        """
    ).fetchall()
    conn.close()
    out: dict[tuple[str, int], dict] = {}
    for r in rows:
        key = (os.path.basename(r["pdf_path"] or ""), r["page_num"])
        out[key] = dict(r)
    return out


# ------------------------------------------------------------------
# Pairing + agreement classification
# ------------------------------------------------------------------

def pair_rows(qwen: dict, churro: dict) -> list[Pair]:
    """Outer-join the two extraction maps into Pair records.

    Signature: Dict Dict -> List[Pair]
    Purpose:   produce one Pair per unique (pdf_basename, page_num).
               Sorted by (pdf_basename, page_num) — same order the
               qwen audit uses.
    Example:   pair_rows({}, {}) == []
    """
    keys = sorted(set(qwen) | set(churro))
    out: list[Pair] = []
    for k in keys:
        q = qwen.get(k) or {}
        c = churro.get(k) or {}
        out.append(Pair(
            pdf_basename=k[0],
            page_num=k[1],
            qwen_status=q.get("status"),
            churro_status=c.get("status"),
            qwen_accession=q.get("accession_number"),
            churro_accession=c.get("accession_number"),
            qwen_botanical=q.get("botanical_name"),
            churro_botanical=c.get("botanical_name"),
            qwen_prop_len=len(q.get("propagation_text") or "") or None,
            churro_prop_len=len(c.get("propagation_text") or "") or None,
            qwen_time_s=q.get("processing_time_s"),
            churro_time_s=c.get("processing_time_s"),
        ))
    return out


def agreement(a: str | None, b: str | None) -> str:
    """Bucket two optional strings into an Agreement label.

    Signature: Str|None Str|None -> Str
    Examples:
        agreement("x", "x") == "exact"
        agreement("x", "y") == "differ"
        agreement("x", None) == "qwen_only"
        agreement(None, "y") == "churro_only"
        agreement(None, None) == "both_empty"
    """
    aa = (a or "").strip()
    bb = (b or "").strip()
    if not aa and not bb:
        return "both_empty"
    if aa and not bb:
        return "qwen_only"
    if bb and not aa:
        return "churro_only"
    return "exact" if aa.lower() == bb.lower() else "differ"


# ------------------------------------------------------------------
# Report rendering
# ------------------------------------------------------------------

def _fmt(v) -> str:
    """Markdown-table-safe cell render: None -> '', pipes escaped.

    Signature: Any -> Str
    """
    if v is None:
        return ""
    s = str(v)
    return s.replace("|", "\\|").replace("\n", " ⏎ ")


def render_summary(pairs: list[Pair]) -> str:
    """Markdown summary tables (counts + agreement).

    Signature: List[Pair] -> Str
    """
    acc_agree = Counter(agreement(p.qwen_accession, p.churro_accession)
                        for p in pairs)
    bot_agree = Counter(agreement(p.qwen_botanical, p.churro_botanical)
                        for p in pairs)
    qwen_succ = sum(1 for p in pairs if p.qwen_status == "success")
    chu_succ = sum(1 for p in pairs if p.churro_status == "success")
    both = sum(1 for p in pairs
               if p.qwen_status == "success" and p.churro_status == "success")

    qwen_times = [p.qwen_time_s for p in pairs if p.qwen_time_s]
    chu_times = [p.churro_time_s for p in pairs if p.churro_time_s]

    def _avg(xs):
        return f"{sum(xs)/len(xs):.1f}s" if xs else "—"

    lines = [
        "## Summary",
        "",
        f"- Cards in qwen DB: **{sum(1 for p in pairs if p.qwen_status)}**",
        f"- Cards in CHURRO DB: **{sum(1 for p in pairs if p.churro_status)}**",
        f"- Cards processed by both: **{both}**",
        f"- qwen successes: **{qwen_succ}** | CHURRO successes: **{chu_succ}**",
        f"- Avg time/card — qwen: **{_avg(qwen_times)}**, "
        f"CHURRO: **{_avg(chu_times)}**",
        "",
        "### Accession-number agreement",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket in ("exact", "differ", "qwen_only", "churro_only", "both_empty"):
        lines.append(f"| {bucket} | {acc_agree.get(bucket, 0)} |")
    lines += [
        "",
        "### Botanical-name agreement",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket in ("exact", "differ", "qwen_only", "churro_only", "both_empty"):
        lines.append(f"| {bucket} | {bot_agree.get(bucket, 0)} |")
    return "\n".join(lines)


def render_table(pairs: list[Pair]) -> str:
    """Full per-card comparison table in Markdown.

    Signature: List[Pair] -> Str
    """
    header = (
        "| PDF | Page | qwen status | CHURRO status | "
        "qwen accession | CHURRO accession | "
        "qwen botanical | CHURRO botanical | "
        "qwen prop_len | CHURRO prop_len | "
        "qwen s | CHURRO s |"
    )
    sep = "|" + "|".join(["---"] * 12) + "|"
    rows = [header, sep]
    for p in pairs:
        rows.append("| " + " | ".join(_fmt(x) for x in [
            p.pdf_basename, p.page_num,
            p.qwen_status, p.churro_status,
            p.qwen_accession, p.churro_accession,
            p.qwen_botanical, p.churro_botanical,
            p.qwen_prop_len, p.churro_prop_len,
            f"{p.qwen_time_s:.1f}" if p.qwen_time_s else None,
            f"{p.churro_time_s:.1f}" if p.churro_time_s else None,
        ]) + " |")
    return "\n".join(rows)


def render_report(pairs: list[Pair], qwen_db: str, churro_db: str) -> str:
    """Full Markdown report.

    Signature: List[Pair] Str Str -> Str
    """
    from datetime import datetime, timezone
    return "\n\n".join([
        "# Qwen vs CHURRO — Propagation Card OCR Comparison",
        f"_Generated: {datetime.now(timezone.utc).isoformat()}_",
        f"- qwen DB: `{qwen_db}`",
        f"- CHURRO DB: `{churro_db}`",
        render_summary(pairs),
        "## Per-card detail",
        render_table(pairs),
    ])


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--qwen-db", default="../cards.db",
                   help="Path to qwen cards.db (default: ../cards.db)")
    p.add_argument("--churro-db", default="churro_cards.db",
                   help="Path to churro_cards.db")
    p.add_argument("--output", default="comparison.md",
                   help="Output Markdown path")
    ns = p.parse_args(argv)

    qwen = load_qwen(ns.qwen_db)
    churro = load_churro(ns.churro_db)
    pairs = pair_rows(qwen, churro)
    text = render_report(pairs, ns.qwen_db, ns.churro_db)
    with open(ns.output, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {len(pairs)} rows to {ns.output}")
    return 0


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------
if __name__ == "__main__" and os.environ.get("COMPARE_SELFTEST"):
    assert agreement("x", "x") == "exact"
    assert agreement("X", "x") == "exact"
    assert agreement("x", "y") == "differ"
    assert agreement("x", None) == "qwen_only"
    assert agreement(None, "y") == "churro_only"
    assert agreement(None, None) == "both_empty"
    assert agreement("", "") == "both_empty"

    # pair_rows with disjoint keys
    q = {("a.pdf", 0): {"status": "success",
                        "accession_number": "2019-12345",
                        "botanical_name": "Abies grandis",
                        "propagation_text": "sown",
                        "processing_time_s": 1.2}}
    c = {("a.pdf", 0): {"status": "success",
                        "accession_number": "2019-12345",
                        "botanical_name": "Abies grandis",
                        "propagation_text": "sown 1/1",
                        "processing_time_s": 3.4},
         ("b.pdf", 1): {"status": "failed",
                        "accession_number": None,
                        "botanical_name": None,
                        "propagation_text": None,
                        "processing_time_s": None}}
    pairs = pair_rows(q, c)
    assert len(pairs) == 2
    assert pairs[0].pdf_basename == "a.pdf"
    assert pairs[0].qwen_accession == pairs[0].churro_accession
    assert pairs[1].qwen_status is None
    assert pairs[1].churro_status == "failed"

    md = render_report(pairs, "q.db", "c.db")
    assert "## Summary" in md
    assert "a.pdf" in md
    print("compare selftest: ok")
    sys.exit(0)

if __name__ == "__main__":
    sys.exit(main())
