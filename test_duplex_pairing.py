"""Tests for duplex front/back pairing (inventory.assign_duplex_pairing).

Pure logic against a synthetic cards.db — no PDFs, no model, no network.
Runnable directly (`python3 test_duplex_pairing.py`) or under pytest.
"""
import os
import sqlite3
import tempfile

import schema
import schema_migrations
from inventory import assign_duplex_pairing
from schema import now_iso


def _make_db(pdf_pages: dict[str, int]) -> str:
    """Build a migrated cards.db and seed `pdf_pages` = {pdf_name: page_count}."""
    db = tempfile.mktemp(suffix=".db")
    schema.init_db(db)
    schema_migrations.migrate(db)
    conn = sqlite3.connect(db)
    for pdf, pages in pdf_pages.items():
        for page in range(pages):
            conn.execute(
                "INSERT INTO cards (run_id, pdf_path, page_num, status, created_at) "
                "VALUES (1, ?, ?, 'pending', ?)",
                (f"/x/{pdf}", page, now_iso()),
            )
    conn.commit()
    conn.close()
    return db


def _faces(db: str, pdf: str):
    conn = sqlite3.connect(db)
    rows = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT page_num, card_face, pair_id FROM cards WHERE pdf_path=? ORDER BY page_num",
            (f"/x/{pdf}",),
        )
    ]
    conn.close()
    return rows


def test_even_duplex_pairs_front_then_back():
    db = _make_db({"amso_duplex.pdf": 6})
    assign_duplex_pairing(db)
    assert _faces(db, "amso_duplex.pdf") == [
        (0, "front", 0), (1, "front", 1), (2, "front", 2),
        (3, "back", 0), (4, "back", 1), (5, "back", 2),
    ]
    os.remove(db)


def test_odd_duplex_is_flagged_not_guessed():
    db = _make_db({"acer_duplex.pdf": 3})
    assign_duplex_pairing(db)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT card_face, pair_id, excluded_reason FROM cards WHERE pdf_path='/x/acer_duplex.pdf'"
    ).fetchall()
    conn.close()
    assert all(face is None and pair is None for face, pair, _ in rows)
    assert all("odd" in (reason or "") for _, _, reason in rows)
    os.remove(db)


def test_non_duplex_untouched():
    db = _make_db({"rosa.pdf": 4})
    assign_duplex_pairing(db)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT card_face, pair_id, duplex_flag FROM cards WHERE pdf_path='/x/rosa.pdf'"
    ).fetchall()
    conn.close()
    assert all(face is None and pair is None and dup == 0 for face, pair, dup in rows)
    os.remove(db)


def test_idempotent():
    db = _make_db({"amso_duplex.pdf": 6})
    assign_duplex_pairing(db)
    first = _faces(db, "amso_duplex.pdf")
    assign_duplex_pairing(db)
    assert _faces(db, "amso_duplex.pdf") == first
    os.remove(db)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All duplex pairing tests passed.")
