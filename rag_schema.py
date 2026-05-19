"""SQLite schema and helpers for the RAG index."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rag_accessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accession_number TEXT NOT NULL,
    accession_format_type TEXT NOT NULL CHECK (accession_format_type IN ('legacy', 'modern')),
    accession_year INTEGER,
    genus TEXT,
    species TEXT,
    infra_text TEXT,
    taxon_name TEXT,
    taxon_name_full TEXT,
    family TEXT,
    collector TEXT,
    collection_date TEXT,
    country TEXT,
    provenance_code TEXT,
    is_current INTEGER,
    source_row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_accession_number TEXT NOT NULL,
    parent_accession_number TEXT,
    item_suffix TEXT,
    genus TEXT,
    taxon_name TEXT,
    item_status TEXT,
    item_status_date TEXT,
    item_location_code TEXT,
    item_location_name TEXT,
    material_type TEXT,
    propagule TEXT,
    project_code TEXT,
    prop_comment TEXT,
    prop_container TEXT,
    prop_duration TEXT,
    prop_environment TEXT,
    prop_medium TEXT,
    prop_quantity TEXT,
    prop_treatment TEXT,
    provenance_code TEXT,
    rec_date TEXT,
    source_row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_taxa (
    genus TEXT,
    genus_normalized TEXT NOT NULL,
    taxon_name TEXT,
    taxon_name_normalized TEXT NOT NULL,
    taxon_name_full TEXT,
    family TEXT,
    observation_count INTEGER NOT NULL,
    first_accession_year INTEGER,
    last_accession_year INTEGER,
    PRIMARY KEY (genus, taxon_name, taxon_name_full)
);

CREATE TABLE IF NOT EXISTS rag_filename_genus_index (
    genus TEXT PRIMARY KEY,
    prefix_3 TEXT,
    prefix_4 TEXT,
    prefix_5 TEXT,
    sort_key TEXT NOT NULL,
    accession_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_accessions_accession_number ON rag_accessions(accession_number);
CREATE INDEX IF NOT EXISTS idx_rag_accessions_genus ON rag_accessions(genus);
CREATE INDEX IF NOT EXISTS idx_rag_accessions_taxon_name ON rag_accessions(taxon_name);
CREATE INDEX IF NOT EXISTS idx_rag_accessions_year ON rag_accessions(accession_year);
CREATE INDEX IF NOT EXISTS idx_rag_items_item_accession_number ON rag_items(item_accession_number);
CREATE INDEX IF NOT EXISTS idx_rag_items_parent_accession ON rag_items(parent_accession_number);
CREATE INDEX IF NOT EXISTS idx_rag_items_genus ON rag_items(genus);
CREATE INDEX IF NOT EXISTS idx_rag_taxa_genus ON rag_taxa(genus);
CREATE INDEX IF NOT EXISTS idx_rag_taxa_genus_normalized ON rag_taxa(genus_normalized);
CREATE INDEX IF NOT EXISTS idx_rag_taxa_taxon_name_normalized ON rag_taxa(taxon_name_normalized);
CREATE TABLE IF NOT EXISTS rag_synonyms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synonym_name TEXT NOT NULL,
    synonym_genus TEXT,
    accepted_name TEXT NOT NULL,
    accepted_genus TEXT,
    family TEXT,
    source TEXT DEFAULT 'accession_csv'
);

CREATE INDEX IF NOT EXISTS idx_rag_filename_prefix3 ON rag_filename_genus_index(prefix_3);
CREATE INDEX IF NOT EXISTS idx_rag_filename_prefix4 ON rag_filename_genus_index(prefix_4);
CREATE INDEX IF NOT EXISTS idx_rag_filename_prefix5 ON rag_filename_genus_index(prefix_5);
CREATE INDEX IF NOT EXISTS idx_rag_filename_sort_key ON rag_filename_genus_index(sort_key);
CREATE INDEX IF NOT EXISTS idx_rag_synonyms_genus ON rag_synonyms(synonym_genus);
CREATE INDEX IF NOT EXISTS idx_rag_synonyms_accepted_genus ON rag_synonyms(accepted_genus);
CREATE INDEX IF NOT EXISTS idx_rag_synonyms_synonym_name ON rag_synonyms(synonym_name);
"""


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
