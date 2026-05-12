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
}

EXTRACTIONS_COLUMNS = {
    "normalized_botanical_name": "TEXT",
    "prompt_text": "TEXT",
    "prompt_context": "TEXT",
    "notes": "TEXT",
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
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "cards.db"
    migrate(target)
    print(f"Migrations applied to {target}")
