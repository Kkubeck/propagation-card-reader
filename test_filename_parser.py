from __future__ import annotations

import pytest

from filename_parser import parse_filename
from rag_schema import get_db, init_db


@pytest.fixture()
def rag_db(tmp_path):
    db_path = tmp_path / "rag.db"
    init_db(str(db_path))
    conn = get_db(str(db_path))
    genera = [
        "Abelia",
        "Abeliophyllum",
        "Abelmoschus",
        "Abies",
        "Acaena",
        "Acantholimon",
        "Acanthocalycium",
        "Acanthus",
        "Acer",
        "Actaea",
        "Actinidia",
        "Allium",
        "Alnus",
        "Alstroemeria",
        "Ammobium",
        "Betula",
        "Sagina",
        "Salix",
        "Salvia",
        "Sorbus",
    ]
    conn.executemany(
        "INSERT INTO rag_filename_genus_index (genus, prefix_3, prefix_4, prefix_5, sort_key, accession_count) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (genus, genus.lower()[:3], genus.lower()[:4], genus.lower()[:5], genus.lower(), 1)
            for genus in genera
        ],
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_exact_genus_matches(rag_db):
    assert parse_filename("sorbus1.pdf", db_path=rag_db)["genus_candidates"] == ["Sorbus"]
    assert parse_filename("sorbus1.pdf", db_path=rag_db)["hint_mode"] == "exact_genus"

    assert parse_filename("acer3.pdf", db_path=rag_db)["genus_candidates"] == ["Acer"]
    assert parse_filename("acer3.pdf", db_path=rag_db)["hint_mode"] == "exact_genus"

    assert parse_filename("allium2.pdf", db_path=rag_db)["genus_candidates"] == ["Allium"]
    assert parse_filename("allium2.pdf", db_path=rag_db)["hint_mode"] == "exact_genus"


def test_range_prefix_matches(rag_db):
    parsed = parse_filename("abel-abie.pdf", db_path=rag_db)
    assert parsed["hint_mode"] == "range_prefix"
    assert parsed["genus_candidates"] == ["Abelia", "Abeliophyllum", "Abelmoschus", "Abies"]
    assert parsed["range_start"] == "Abelia"
    assert parsed["range_end"] == "Abies"

    parsed = parse_filename("acae-acan.pdf", db_path=rag_db)
    assert parsed["hint_mode"] == "range_prefix"
    assert parsed["genus_candidates"] == ["Acaena", "Acanthocalycium", "Acantholimon", "Acanthus"]


def test_duplex_detection(rag_db):
    assert parse_filename("acer-duplex1.pdf", db_path=rag_db)["duplex"] is True
    assert parse_filename("abie-acti_duplex.pdf", db_path=rag_db)["duplex"] is True
    assert parse_filename("alst-ammo_duplex.pdf", db_path=rag_db)["duplex"] is True


def test_no_hint_with_unknown_filename(rag_db):
    parsed = parse_filename("random_stuff.pdf", db_path=rag_db)
    assert parsed["hint_mode"] == "none"
    assert parsed["confidence"] <= 0.2
    assert parsed["genus_candidates"] == []


def test_clean_canonical_filename(rag_db):
    parsed = parse_filename("2025-07-23__sorbus__duplex.pdf", db_path=rag_db)
    assert parsed["scan_date"] == "2025-07-23"
    assert parsed["duplex"] is True
    assert parsed["genus_candidates"] == ["Sorbus"]
    assert parsed["hint_mode"] == "exact_genus"
