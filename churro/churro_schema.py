"""SQLite schema for the CHURRO-side comparison run.

This mirrors the relevant subset of the parent ``cards.db`` schema
(``schema.py`` in the repo root) so that a SQL join across the two
databases compares like-for-like: same ``pdf_path`` + ``page_num``
key, same status vocabulary, same extraction columns we care about
for the qwen-vs-CHURRO head-to-head.

We deliberately do NOT mirror the full 22-field RAG extraction
schema. CHURRO returns plain transcribed text — there are no
structured field outputs from the model itself. Anything past
``transcript_text`` is something WE extracted from that text in
``run_churro.py`` via the same regex/post-processing conventions
the qwen pipeline uses in ``post_processing.py``.

# ------------------------------------------------------------------
# Data definitions (HtDP)
# ------------------------------------------------------------------

# DbPath is String
# interp. filesystem path to a SQLite file, absolute or relative.
# examples:
#   "churro_cards.db"
#   "/Volumes/DeweyRunner/churro_cards.db"

# RunRow is Compound{ id: Int, started_at: ISO8601, model: Str,
#                     backend: Str, cards_dir: Str, notes: Str|None }
# interp. one row in churro_processing_runs; one row per invocation
#         of run_churro.py.

# CardRow is Compound{ id: Int, run_id: Int, pdf_path: Str,
#                      page_num: Int>=0, image_path: Str,
#                      status: Status, error_message: Str|None,
#                      created_at: ISO8601, processed_at: ISO8601|None }
# interp. one row per (pdf, page) we attempted to OCR with CHURRO.
#         Same key shape as cards.cards so we can join.

# Status is one of:
#   "pending"   — inventoried, not yet OCR'd
#   "success"   — CHURRO returned non-empty text
#   "failed"    — CHURRO returned empty text or non-zero exit
#   "error"     — uncaught exception in the worker loop

# ExtractionRow is Compound{ id, card_id, transcript_text,
#                            botanical_name|None, accession_number|None,
#                            propagation_text|None, raw_stdout,
#                            model, processing_time_s, created_at }
# interp. CHURRO's raw transcript plus our heuristic field pulls.
#         botanical_name / accession_number / propagation_text are
#         best-effort extractions from transcript_text using the
#         same regex conventions as the qwen post-processing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS churro_processing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    total_cards INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    model TEXT,
    backend TEXT,
    cards_dir TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS churro_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    pdf_path TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    FOREIGN KEY (run_id) REFERENCES churro_processing_runs(id),
    UNIQUE(pdf_path, page_num)
);

CREATE TABLE IF NOT EXISTS churro_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER UNIQUE NOT NULL,
    transcript_text TEXT,
    botanical_name TEXT,
    accession_number TEXT,
    propagation_text TEXT,
    raw_stdout TEXT,
    model TEXT,
    backend TEXT,
    processing_time_s REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (card_id) REFERENCES churro_cards(id)
);

CREATE INDEX IF NOT EXISTS idx_churro_cards_pdf_page
    ON churro_cards(pdf_path, page_num);
"""


def init_db(db_path: str) -> None:
    """Create CHURRO tables if they don't already exist.

    Signature: String -> None
    Purpose:   ensure the churro_cards.db file exists and has
               all four tables; idempotent.
    Example:   init_db("churro_cards.db")
               # after: sqlite_master has churro_cards, churro_extractions,
               #        churro_processing_runs, idx_churro_cards_pdf_page
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def get_db(db_path: str) -> sqlite3.Connection:
    """Open a connection with Row factory + WAL + FK enforcement.

    Signature: String -> sqlite3.Connection
    Purpose:   match the parent project's connection conventions
               (see schema.py::get_db) so both DBs behave the same.
    Example:   conn = get_db("churro_cards.db")
               assert conn.row_factory is sqlite3.Row
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Signature: -> String
    Purpose:   match schema.py::now_iso so timestamps are comparable
               across cards.db and churro_cards.db.
    Example:   s = now_iso()
               assert s.endswith("+00:00") or "T" in s
    """
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db")
        init_db(db)
        # Idempotent: running again must not throw.
        init_db(db)
        conn = get_db(db)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "churro_processing_runs",
            "churro_cards",
            "churro_extractions",
        }.issubset(tables), tables
        # now_iso is parseable.
        ts = now_iso()
        datetime.fromisoformat(ts)
        conn.close()
    print("churro_schema: ok")
