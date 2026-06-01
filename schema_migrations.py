"""Idempotent Phase 2 schema migrations for cards.db."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


PROCESSING_RUN_COLUMNS = {
    "pipeline_mode": "TEXT",
    "prompt_version": "TEXT",
    "rag_index_version": "TEXT",
}

CARDS_COLUMNS = {
    "pdf_filename": "TEXT",
    "duplex_flag": "INTEGER DEFAULT 0",
    "excluded_reason": "TEXT",
    "filename_hint_json": "TEXT",
    # Duplex pairing: for an N-page *_duplex* PDF, pages 1..N/2 are fronts and
    # pages N/2+1..N are backs (Kevin reshuffles between scans, so order is
    # preserved and no reversal is needed). card_face is 'front'|'back';
    # pair_id = i links front page i to back page N/2+i within the same PDF.
    # Both NULL for ordinary single-sided cards.
    "card_face": "TEXT",
    "pair_id": "INTEGER",
}

EXTRACTIONS_COLUMNS = {
    "normalized_botanical_name": "TEXT",
    "prompt_text": "TEXT",
    "prompt_context": "TEXT",
    "notes": "TEXT",
    "family": "TEXT",
    "received_as": "TEXT",
    "date_received": "TEXT",
    "geocode": "TEXT",
    "quantity": "TEXT",
    "present_location": "TEXT",
    "wanted_for_area": "TEXT",
    "source": "TEXT",
    "source_info": "TEXT",
    "collector_number": "TEXT",
    "other_number": "TEXT",
    "labels_requested": "TEXT",
    "max_quantity": "TEXT",
    "parent_accession": "TEXT",
    "collection_info": "TEXT",
    "distribution": "TEXT",
    "accession_number": "TEXT",
    "curators_info": "TEXT",
    "iris_data_entered": "INTEGER",
    # Shadow columns hold pre-redaction text for fields where PII can land.
    # Kept locally so regex tuning is reversible; dropped from any published
    # export. Schema-of-the-canonical fields above remains unchanged.
    "source_info_raw": "TEXT",
    "curators_info_raw": "TEXT",
    "collection_info_raw": "TEXT",
    "propagation_text_raw": "TEXT",
}

ACCESSION_COLUMNS = {
    "normalized_accession_number": "TEXT",
    "format_type": "TEXT",
}

RAG_CONTEXTS_SQL = """
CREATE TABLE IF NOT EXISTS rag_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    retrieval_query_json TEXT,
    context_text TEXT,
    context_token_estimate INTEGER,
    retrieval_latency_ms REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (card_id) REFERENCES cards(id)
);
"""

# Audit trail for every PII redaction made by privacy_redaction.redact().
# `original` is the verbatim matched substring; treat the table as PII-bearing
# and exclude from any published export.
REDACTIONS_SQL = """
CREATE TABLE IF NOT EXISTS redactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    category TEXT NOT NULL,
    original TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (extraction_id) REFERENCES extractions(id)
);
CREATE INDEX IF NOT EXISTS idx_redactions_extraction ON redactions(extraction_id);
CREATE INDEX IF NOT EXISTS idx_redactions_category ON redactions(category);
"""


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]):
    existing = _column_names(conn, table_name)
    for column_name, column_type in columns.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def migrate(db_path: str):
    """Apply all Phase 2 schema migrations to cards.db. Idempotent."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(path))
    try:
        _ensure_columns(conn, "processing_runs", PROCESSING_RUN_COLUMNS)
        _ensure_columns(conn, "cards", CARDS_COLUMNS)
        _ensure_columns(conn, "extractions", EXTRACTIONS_COLUMNS)
        _ensure_columns(conn, "accession_numbers", ACCESSION_COLUMNS)
        conn.execute(RAG_CONTEXTS_SQL)
        conn.executescript(REDACTIONS_SQL)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "cards.db"
    migrate(target)
    print(f"Migrations applied to {target}")
