"""Walk a directory of propagation-card PDFs (or pre-rendered PNGs),
run CHURRO OCR on each page-image, and persist the results in
``churro_cards.db`` for later head-to-head comparison with the
qwen pipeline's ``cards.db``.

Designed for Kevin's M4 MacBook Air against the "DeweyRunner" USB
stick that mirrors the Zotac's
``/media/hevek/LACIE SHARE/propagation_card_ocr/OCR_test/`` tree
of PDF cards. Mac-first: no hardcoded paths; everything goes
through ``--cards-dir``.

Invocation:
    python3 run_churro.py --cards-dir /Volumes/DeweyRunner/OCR_test \\
                          --db churro_cards.db \\
                          --model stanford-oval/churro-3B \\
                          --backend hf \\
                          --dpi 175

Idempotency:
    - PDFs already inventoried (same pdf_path + page_num) are skipped.
    - Card rows already at status='success' are not re-OCR'd.
    - Pre-rendered page PNGs in <cards-dir>/_pages/ are reused.

# ------------------------------------------------------------------
# Data definitions (HtDP)
# ------------------------------------------------------------------

# CardsDir is String
# interp. directory containing *.pdf propagation-card scans, mirroring
#         the qwen pipeline's input layout. May also contain a
#         "_pages/" subdir of pre-rendered <stem>_pNNNN.png images.

# Args is Compound{ cards_dir, db, model, backend, dpi, limit, dry_run }
# interp. parsed CLI arguments.

# PageImage is Compound{ pdf_path: Str, page_num: Int>=0, image_path: Str }
# interp. one card page rendered to PNG, ready to feed CHURRO.

# ChurroResult is Compound{ ok: Bool, text: Str, stderr: Str,
#                           elapsed_s: Float, returncode: Int }
# interp. one CHURRO transcribe invocation's outcome.

# Fields is Compound{ botanical_name: Str|None,
#                     accession_number: Str|None,
#                     propagation_text: Str|None }
# interp. heuristic field extractions from a CHURRO transcript.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, NamedTuple

# Local module — lives in the same churro/ directory.
from churro_schema import get_db, init_db, now_iso


DEFAULT_MODEL = "stanford-oval/churro-3B"
DEFAULT_BACKEND = "hf"
DEFAULT_DPI = 175
DEFAULT_CLI = "churro-ocr"


# ------------------------------------------------------------------
# Field-extraction regexes
#
# These mirror the conventions in ../post_processing.py without
# importing it (post_processing imports privacy_redaction which
# pulls in repo-root dependencies; the churro/ module is meant to
# be self-contained and run on a Mac with only stdlib + CHURRO).
# ------------------------------------------------------------------

# Legacy: NNNNN-NNN-NN (or wider digit counts as written on cards).
LEGACY_ACC_RE = re.compile(r"\b(\d{4,6}[-/]\d{2,4}[-/]\d{2,4})\b")
# Modern: YYYY-NNNN(N)
MODERN_ACC_RE = re.compile(r"\b((?:19|20)\d{2}-\d{4,5})\b")

# Botanical name: a Capitalised genus token followed by a lowercase
# species epithet. Crude but matches the qwen pipeline's first-pass
# heuristic for "name on the top of the card".
BOTANICAL_RE = re.compile(
    r"\b([A-Z][a-z]{2,})\s+([a-z][a-z\-]{2,})\b"
)

# Lines that look like propagation notes — dated entries, sowing /
# germ / transplant / treatment keywords. Used to bound the
# propagation_text block.
PROP_KEYWORDS = (
    "sown", "sow", "germ", "trans", "stratif", "scarif",
    "cuttings", "graft", "potted", "tray", "flat", "seedling",
)


# ------------------------------------------------------------------
# CLI wiring
# ------------------------------------------------------------------

class Args(NamedTuple):
    cards_dir: str
    db: str
    model: str
    backend: str
    dpi: int
    limit: int | None
    dry_run: bool
    churro_cli: str


def parse_args(argv: list[str] | None = None) -> Args:
    """Parse command-line arguments.

    Signature: List[Str]|None -> Args
    Purpose:   produce a validated Args record from argv.
    Example:   parse_args(["--cards-dir", "/tmp/cards"]).cards_dir
               == "/tmp/cards"
    """
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cards-dir", required=True,
                   help="Directory of *.pdf card scans (Mac path OK)")
    p.add_argument("--db", default="churro_cards.db",
                   help="Output SQLite DB (default: churro_cards.db)")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"CHURRO model (default: {DEFAULT_MODEL})")
    p.add_argument("--backend", default=DEFAULT_BACKEND,
                   help=f"CHURRO backend (default: {DEFAULT_BACKEND})")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI,
                   help=f"Render DPI for PDF->PNG (default: {DEFAULT_DPI})")
    p.add_argument("--limit", type=int, default=None,
                   help="Max cards to OCR this run (default: all pending)")
    p.add_argument("--dry-run", action="store_true",
                   help="Inventory + render, but do not call CHURRO")
    p.add_argument("--churro-cli", default=DEFAULT_CLI,
                   help=f"CHURRO CLI executable (default: {DEFAULT_CLI})")
    ns = p.parse_args(argv)
    return Args(
        cards_dir=ns.cards_dir,
        db=ns.db,
        model=ns.model,
        backend=ns.backend,
        dpi=ns.dpi,
        limit=ns.limit,
        dry_run=ns.dry_run,
        churro_cli=ns.churro_cli,
    )


# ------------------------------------------------------------------
# PDF -> page image rendering
# ------------------------------------------------------------------

def list_pdfs(cards_dir: str) -> list[str]:
    """Return absolute paths of all *.pdf files in cards_dir, sorted.

    Signature: String -> List[String]
    Purpose:   match the qwen inventory.py ordering (alphabetical,
               case-insensitive on filename) so audit-line numbers
               between the two DBs stay comparable.
    Example:   list_pdfs("/empty") == []
    """
    if not os.path.isdir(cards_dir):
        raise FileNotFoundError(cards_dir)
    names = sorted(
        (f for f in os.listdir(cards_dir) if f.lower().endswith(".pdf")),
        key=str.lower,
    )
    return [os.path.join(cards_dir, n) for n in names]


def page_image_path(pages_dir: str, pdf_path: str, page_num: int) -> str:
    """Build the canonical PNG path for one page.

    Signature: String String Int -> String
    Purpose:   match the qwen pipeline's <stem>_pNNNN.png convention
               (see propagation-card-reader/images/).
    Example:   page_image_path("/tmp/p", "/x/abel.pdf", 3)
               == "/tmp/p/abel_p0003.png"
    """
    stem = Path(pdf_path).stem
    return os.path.join(pages_dir, f"{stem}_p{page_num:04d}.png")


def render_pdf_pages(pdf_path: str, pages_dir: str, dpi: int) -> list[tuple[int, str]]:
    """Render every page of pdf_path to PNG, skipping any that already exist.

    Signature: String String Int -> List[(Int, String)]
    Purpose:   one PNG per page in pages_dir, return [(page_num, path)].
               Requires PyMuPDF (``pip install pymupdf``).
    Example:   non-existent pdf -> FileNotFoundError
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF (pymupdf) is required to render PDFs. "
            "Install with: pip install pymupdf"
        ) from exc

    os.makedirs(pages_dir, exist_ok=True)
    out: list[tuple[int, str]] = []
    doc = fitz.open(pdf_path)
    try:
        # 72 dpi is PyMuPDF's default; scale matrix accordingly.
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i in range(len(doc)):
            png = page_image_path(pages_dir, pdf_path, i)
            if not os.path.exists(png):
                pix = doc.load_page(i).get_pixmap(matrix=mat, alpha=False)
                pix.save(png)
            out.append((i, png))
    finally:
        doc.close()
    return out


# ------------------------------------------------------------------
# CHURRO invocation
# ------------------------------------------------------------------

def run_churro(image_path: str, model: str, backend: str,
               churro_cli: str = DEFAULT_CLI) -> tuple[bool, str, str, float, int]:
    """Call `churro-ocr transcribe` on one image, capture stdout text.

    Signature: String String String [String] -> (Bool, Str, Str, Float, Int)
    Purpose:   shell out to CHURRO and return (ok, text, stderr,
               elapsed_s, returncode). ``text`` is the transcript
               from --output (CHURRO prints "Wrote to <path>" on
               stdout, so we read the file instead of stdout).
    Example:   bogus image -> ok=False, returncode != 0
    """
    with tempfile.NamedTemporaryFile(
        prefix="churro_", suffix=".txt", delete=False
    ) as fh:
        out_path = fh.name
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [
                churro_cli, "transcribe",
                "--image", image_path,
                "--backend", backend,
                "--model", model,
                "--output", out_path,
            ],
            capture_output=True, text=True, check=False,
        )
        elapsed = time.monotonic() - t0
        text = ""
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except Exception:
                text = ""
        ok = proc.returncode == 0 and bool(text.strip())
        return ok, text, proc.stderr or "", elapsed, proc.returncode
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


# ------------------------------------------------------------------
# Field extraction from CHURRO plain-text transcripts
# ------------------------------------------------------------------

class Fields(NamedTuple):
    botanical_name: str | None
    accession_number: str | None
    propagation_text: str | None


def extract_accession(text: str) -> str | None:
    """First plausible accession number found in text.

    Signature: String -> String|None
    Purpose:   return the first accession-shaped token (modern then
               legacy) in the transcript. Heuristic — matches the
               coarse pattern audited in card-audit-report.md.
    Examples:
        extract_accession("Acc# 2019-12345 sown") == "2019-12345"
        extract_accession("39149-077-08") == "39149-077-08"
        extract_accession("no number here") is None
    """
    if not text:
        return None
    m = MODERN_ACC_RE.search(text)
    if m:
        return m.group(1)
    m = LEGACY_ACC_RE.search(text)
    if m:
        return m.group(1).replace("/", "-")
    return None


def extract_botanical_name(text: str) -> str | None:
    """First Genus species pair on a line, scanning top-to-bottom.

    Signature: String -> String|None
    Purpose:   pick the most prominent botanical name (cards
               typically have it as the top line). Heuristic.
    Examples:
        extract_botanical_name("Abies grandis\nseed lot 12") == "Abies grandis"
        extract_botanical_name("UBC Botanical Garden") is None
    """
    if not text:
        return None
    for line in text.splitlines():
        m = BOTANICAL_RE.search(line)
        if m:
            return f"{m.group(1)} {m.group(2)}"
    return None


def extract_propagation_text(text: str) -> str | None:
    """Lines that mention propagation keywords, joined with newlines.

    Signature: String -> String|None
    Purpose:   crude prop-notes block: keep lines containing any of
               PROP_KEYWORDS. If nothing matches, return the full
               transcript (the model may have ignored the keyword
               structure entirely).
    Examples:
        extract_propagation_text("sown 1/1/24\nnotes\ngerm 5%") ==
            "sown 1/1/24\ngerm 5%"
        extract_propagation_text("") is None
    """
    if not text:
        return None
    kept = [
        ln for ln in text.splitlines()
        if any(kw in ln.lower() for kw in PROP_KEYWORDS)
    ]
    if kept:
        return "\n".join(kept)
    return text.strip() or None


def extract_fields(text: str) -> Fields:
    """Bundle the three field extractions.

    Signature: String -> Fields
    Purpose:   one call site for the worker loop.
    Example:   extract_fields("Abies grandis\n2019-12345\nsown 1/1")
               == Fields("Abies grandis", "2019-12345", "sown 1/1")
    """
    return Fields(
        botanical_name=extract_botanical_name(text),
        accession_number=extract_accession(text),
        propagation_text=extract_propagation_text(text),
    )


# ------------------------------------------------------------------
# Inventory + worker loop
# ------------------------------------------------------------------

def inventory(conn, run_id: int, pdfs: Iterable[str], pages_dir: str,
              dpi: int) -> int:
    """Render each PDF's pages and insert pending card rows.

    Signature: Conn Int Iter[Str] Str Int -> Int
    Purpose:   ensure every (pdf_path, page_num) is in churro_cards
               with status='pending' (idempotent via UNIQUE
               constraint). Returns number of new rows inserted.
    """
    new_rows = 0
    for pdf in pdfs:
        try:
            pages = render_pdf_pages(pdf, pages_dir, dpi)
        except Exception as exc:
            print(f"  WARN: failed to render {pdf}: {exc}", file=sys.stderr)
            continue
        for page_num, png in pages:
            try:
                conn.execute(
                    """INSERT INTO churro_cards
                       (run_id, pdf_path, page_num, image_path, status, created_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)""",
                    (run_id, pdf, page_num, png, now_iso()),
                )
                new_rows += 1
            except Exception:
                # UNIQUE(pdf_path, page_num) — already seen. Refresh
                # the image_path in case the user moved cards_dir.
                conn.execute(
                    "UPDATE churro_cards SET image_path = ? "
                    "WHERE pdf_path = ? AND page_num = ?",
                    (png, pdf, page_num),
                )
    conn.commit()
    return new_rows


def pending_cards(conn, limit: int | None) -> list[dict]:
    """Return up to ``limit`` cards still in status='pending', ordered
    the same way the qwen audit walks them (pdf_path, page_num).

    Signature: Conn Int|None -> List[Dict]
    Purpose:   produce the worker queue.
    """
    sql = (
        "SELECT id, pdf_path, page_num, image_path "
        "FROM churro_cards WHERE status='pending' "
        "ORDER BY pdf_path COLLATE NOCASE, page_num"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql)]


def process_one(conn, card: dict, args: Args) -> None:
    """OCR one card with CHURRO, write result + extraction rows.

    Signature: Conn Dict Args -> None
    Purpose:   the single-card work unit. Handles success / failure
               status transitions and exception capture.
    """
    cid = card["id"]
    img = card["image_path"]
    if not img or not os.path.exists(img):
        conn.execute(
            "UPDATE churro_cards SET status='error', "
            "error_message=?, processed_at=? WHERE id=?",
            (f"image not found: {img}", now_iso(), cid),
        )
        conn.commit()
        return

    if args.dry_run:
        return

    try:
        ok, text, stderr, elapsed, rc = run_churro(
            img, args.model, args.backend, args.churro_cli,
        )
    except FileNotFoundError as exc:
        conn.execute(
            "UPDATE churro_cards SET status='error', "
            "error_message=?, processed_at=? WHERE id=?",
            (f"churro CLI not found: {exc}", now_iso(), cid),
        )
        conn.commit()
        raise  # fatal; abort the run

    status = "success" if ok else "failed"
    err = None if ok else (stderr.strip()[:500] or f"rc={rc}, empty text")
    fields = extract_fields(text) if ok else Fields(None, None, None)

    conn.execute(
        "UPDATE churro_cards SET status=?, error_message=?, processed_at=? "
        "WHERE id=?",
        (status, err, now_iso(), cid),
    )
    conn.execute(
        """INSERT OR REPLACE INTO churro_extractions
           (card_id, transcript_text, botanical_name, accession_number,
            propagation_text, raw_stdout, model, backend,
            processing_time_s, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid, text, fields.botanical_name, fields.accession_number,
            fields.propagation_text, stderr, args.model, args.backend,
            elapsed, now_iso(),
        ),
    )
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    """Entry point: inventory then OCR every pending card.

    Signature: List[Str]|None -> Int (exit code)
    """
    args = parse_args(argv)
    init_db(args.db)
    conn = get_db(args.db)

    cards_dir = os.path.abspath(args.cards_dir)
    pages_dir = os.path.join(cards_dir, "_pages")
    pdfs = list_pdfs(cards_dir)
    if not pdfs:
        print(f"No PDFs found in {cards_dir}", file=sys.stderr)
        return 2

    cur = conn.execute(
        """INSERT INTO churro_processing_runs
           (started_at, model, backend, cards_dir, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (now_iso(), args.model, args.backend, cards_dir,
         f"dpi={args.dpi} limit={args.limit} dry_run={args.dry_run}"),
    )
    run_id = cur.lastrowid
    conn.commit()

    print(f"[run {run_id}] inventorying {len(pdfs)} PDFs from {cards_dir}")
    new = inventory(conn, run_id, pdfs, pages_dir, args.dpi)
    print(f"[run {run_id}] {new} new card rows inserted")

    queue = pending_cards(conn, args.limit)
    print(f"[run {run_id}] {len(queue)} cards pending OCR")

    ok = fail = 0
    for i, card in enumerate(queue, 1):
        t0 = time.monotonic()
        try:
            process_one(conn, card, args)
        except FileNotFoundError:
            print(f"[run {run_id}] ABORT: CHURRO CLI missing", file=sys.stderr)
            break
        row = conn.execute(
            "SELECT status FROM churro_cards WHERE id=?", (card["id"],)
        ).fetchone()
        st = row["status"] if row else "?"
        if st == "success":
            ok += 1
        else:
            fail += 1
        dt = time.monotonic() - t0
        print(
            f"  [{i}/{len(queue)}] {os.path.basename(card['pdf_path'])} "
            f"p{card['page_num']:04d} -> {st} ({dt:.1f}s)"
        )

    conn.execute(
        "UPDATE churro_processing_runs SET ended_at=?, total_cards=?, "
        "success_count=?, fail_count=? WHERE id=?",
        (now_iso(), len(queue), ok, fail, run_id),
    )
    conn.commit()
    conn.close()
    print(f"[run {run_id}] done: {ok} ok / {fail} fail / {len(queue)} total")
    return 0


# ------------------------------------------------------------------
# Tests (no CHURRO required — exercise pure functions only)
# ------------------------------------------------------------------
if __name__ == "__main__" and os.environ.get("CHURRO_SELFTEST"):
    # Pure-function smoke tests.
    assert extract_accession("blah 2019-12345 blah") == "2019-12345"
    assert extract_accession("legacy 39149-077-08 here") == "39149-077-08"
    assert extract_accession("legacy 39149/077/08 here") == "39149-077-08"
    assert extract_accession("nothing here") is None

    assert extract_botanical_name("Abies grandis\nfoo") == "Abies grandis"
    assert extract_botanical_name("UBC BOTANICAL GARDEN") is None
    assert extract_botanical_name("") is None

    txt = "Abies grandis\nsown 2024-01-01\nnotes here\ngerm 5%"
    assert extract_propagation_text(txt) == "sown 2024-01-01\ngerm 5%"
    assert extract_propagation_text("no keywords") == "no keywords"
    assert extract_propagation_text("") is None

    f = extract_fields("Abies grandis\n2019-12345\nsown 1/1")
    assert f.botanical_name == "Abies grandis"
    assert f.accession_number == "2019-12345"
    assert "sown" in (f.propagation_text or "")

    assert page_image_path("/p", "/x/abel.pdf", 3) == "/p/abel_p0003.png"
    print("run_churro selftest: ok")
    sys.exit(0)

if __name__ == "__main__":
    sys.exit(main())
