"""SQLite schema and helpers for propagation card processing."""

import sqlite3
from datetime import datetime, timezone


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    total_cards INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    dpi INTEGER,
    model TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    pdf_path TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    FOREIGN KEY (run_id) REFERENCES processing_runs(id),
    UNIQUE(pdf_path, page_num)
);

CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER UNIQUE NOT NULL,
    botanical_name TEXT,
    propagation_text TEXT,
    raw_json TEXT,
    model TEXT,
    dpi INTEGER,
    processing_time_s REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (card_id) REFERENCES cards(id)
);

CREATE TABLE IF NOT EXISTS accession_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_id INTEGER NOT NULL,
    accession_number TEXT,
    position INTEGER,
    FOREIGN KEY (extraction_id) REFERENCES extractions(id)
);
"""


def init_db(db_path):
    """Create tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def get_db(db_path):
    """Return a connection with row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso():
    """Return current time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
