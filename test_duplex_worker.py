"""Tests for duplex back-side processing and export merge (Option A).

Pure logic against synthetic cards.db files — no PDFs, no model, no network.
Ollama and PDF I/O are monkeypatched. Runnable directly
(`python3 test_duplex_worker.py`) or under pytest.
"""
import argparse
import csv
import os
import sqlite3
import tempfile

import schema
import schema_migrations
import rag_worker
import run
from schema import now_iso


# --- DB fixtures -------------------------------------------------------------

def _make_db():
    """Return a migrated cards.db path with a processing run row."""
    db = tempfile.mktemp(suffix=".db")
    schema.init_db(db)
    schema_migrations.migrate(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO processing_runs (started_at) VALUES (?)", (now_iso(),)
    )
    conn.commit()
    conn.close()
    return db


def _add_card(conn, pdf, page, face, pair_id, status="pending"):
    cur = conn.execute(
        """INSERT INTO cards (run_id, pdf_path, page_num, status, created_at,
                              duplex_flag, card_face, pair_id)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (pdf, page, status, now_iso(), 1 if face else 0, face, pair_id),
    )
    return cur.lastrowid


def _add_extraction(conn, card_id, propagation_text=None, accessions=()):
    cur = conn.execute(
        """INSERT INTO extractions (card_id, propagation_text, created_at)
           VALUES (?, ?, ?)""",
        (card_id, propagation_text, now_iso()),
    )
    ext_id = cur.lastrowid
    for pos, acc in enumerate(accessions):
        conn.execute(
            "INSERT INTO accession_numbers (extraction_id, accession_number, position) VALUES (?, ?, ?)",
            (ext_id, acc, pos),
        )
    return ext_id


# --- Export merge ------------------------------------------------------------

def _export_rows(db):
    out = tempfile.mktemp(suffix=".csv")
    run.cmd_export(argparse.Namespace(db=db, output=out))
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    os.remove(out)
    return rows


def test_export_merges_back_into_front():
    db = _make_db()
    conn = sqlite3.connect(db)
    f = _add_card(conn, "/x/amso_duplex.pdf", 0, "front", 0, status="success")
    b = _add_card(conn, "/x/amso_duplex.pdf", 1, "back", 0, status="success")
    _add_extraction(conn, f, "FRONT sowing log", accessions=["2015-00634"])
    _add_extraction(conn, b, "BACK continuation rows", accessions=["31748-167-94"])
    conn.commit()
    conn.close()

    rows = _export_rows(db)
    # One emitted row (front), back folded in — not its own row.
    assert len(rows) == 1
    front = rows[0]
    assert "FRONT sowing log" in front["propagation_text"]
    assert "— BACK —" in front["propagation_text"]
    assert "BACK continuation rows" in front["propagation_text"]
    # Accessions unioned, order preserved, deduped.
    assert front["all_accession_numbers"] == "2015-00634 | 31748-167-94"
    os.remove(db)


def test_export_back_merges_into_failed_front():
    # A failed front still has a card row, so the back stays paired with it
    # (status remains 'failed' for retry, but the back text is not lost).
    db = _make_db()
    conn = sqlite3.connect(db)
    _add_card(conn, "/x/acer_duplex.pdf", 0, "front", 0, status="failed")  # no extraction
    b = _add_card(conn, "/x/acer_duplex.pdf", 1, "back", 0, status="success")
    _add_extraction(conn, b, "back text on failed-front pair", accessions=[])
    conn.commit()
    conn.close()

    rows = _export_rows(db)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "back text on failed-front pair" in rows[0]["propagation_text"]
    os.remove(db)


def test_export_true_orphan_back_standalone():
    # No front row exists for the pair at all — emit the back standalone.
    db = _make_db()
    conn = sqlite3.connect(db)
    b = _add_card(conn, "/x/acer_duplex.pdf", 1, "back", 0, status="success")
    _add_extraction(conn, b, "orphan back text", accessions=[])
    conn.commit()
    conn.close()

    rows = _export_rows(db)
    statuses = [r["status"] for r in rows]
    assert any("orphan back" in s for s in statuses)
    os.remove(db)


def test_export_single_sided_untouched():
    db = _make_db()
    conn = sqlite3.connect(db)
    c = _add_card(conn, "/x/rosa.pdf", 0, None, None, status="success")
    _add_extraction(conn, c, "normal card", accessions=["2020-00001"])
    conn.commit()
    conn.close()

    rows = _export_rows(db)
    assert len(rows) == 1
    assert rows[0]["propagation_text"] == "normal card"
    assert "— BACK —" not in rows[0]["propagation_text"]
    os.remove(db)


# --- Back-card processing (monkeypatched Ollama + PDF) -----------------------

class _StubBuilder:
    """Stand-in for RAGContextBuilder so RAGWorker.__init__ touches no disk."""
    def __init__(self, *a, **k):
        pass
    def close(self):
        pass


def _make_worker(db, monkeypatch_target):
    monkeypatch_target(rag_worker, "RAGContextBuilder", _StubBuilder)
    return rag_worker.RAGWorker(db_path=db, rag_db_path="unused.db", config={}, mode="ocr_only")


def _patch(obj, name, value):
    setattr(obj, name, value)


def test_load_front_context_returns_none_when_front_missing():
    db = _make_db()
    conn = sqlite3.connect(db)
    _add_card(conn, "/x/d.pdf", 0, "front", 0, status="failed")  # no extraction
    b_id = _add_card(conn, "/x/d.pdf", 1, "back", 0, status="processing")
    conn.commit()

    worker = _make_worker(db, _patch)
    back = sqlite3.connect(db)
    back.row_factory = sqlite3.Row
    card = back.execute("SELECT * FROM cards WHERE id = ?", (b_id,)).fetchone()
    assert worker._load_front_context(conn, card) is None
    conn.close()
    back.close()
    os.remove(db)


def test_load_front_context_returns_front_fields():
    db = _make_db()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    f = _add_card(conn, "/x/d.pdf", 0, "front", 0, status="success")
    b_id = _add_card(conn, "/x/d.pdf", 1, "back", 0, status="processing")
    conn.execute(
        "INSERT INTO extractions (card_id, botanical_name, family, accession_number, propagation_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (f, "Acer rubrum", "Sapindaceae", "2015-00634", "x" * 300, now_iso()),
    )
    conn.commit()

    worker = _make_worker(db, _patch)
    card = conn.execute("SELECT * FROM cards WHERE id = ?", (b_id,)).fetchone()
    ctx = worker._load_front_context(conn, card)
    assert ctx["botanical_name"] == "Acer rubrum"
    assert ctx["family"] == "Sapindaceae"
    assert ctx["accession_number"] == "2015-00634"
    assert len(ctx["propagation_tail"]) == 200  # tail trimmed
    conn.close()
    os.remove(db)


def test_process_back_card_stores_back_extraction():
    db = _make_db()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    f = _add_card(conn, "/x/d.pdf", 0, "front", 0, status="success")
    b_id = _add_card(conn, "/x/d.pdf", 1, "back", 0, status="processing")
    _add_extraction(conn, f, "front log", accessions=["2015-00634"])
    conn.commit()

    worker = _make_worker(db, _patch)
    # Avoid network + PDF I/O.
    _patch(rag_worker, "extract_page_image", lambda *a, **k: ("b64", None))
    _patch(
        rag_worker, "call_ollama_with_prompt",
        lambda *a, **k: '{"mode": "table_continuation", "propagation_text": "row1 row2", '
                        '"all_accession_numbers": ["31748-167-94"], "curators_info": null, "notes": null}',
    )

    card = conn.execute("SELECT * FROM cards WHERE id = ?", (b_id,)).fetchone()
    status, _ = worker._process_back_card(conn, card, "http://x", "m", 100)
    assert status == "success"

    ext = conn.execute("SELECT * FROM extractions WHERE card_id = ?", (b_id,)).fetchone()
    assert ext["propagation_text"] == "row1 row2"
    assert "back_mode=table_continuation" in ext["notes"]
    accs = [r["accession_number"] for r in
            conn.execute("SELECT accession_number FROM accession_numbers WHERE extraction_id = ?", (ext["id"],))]
    assert accs == ["31748-167-94"]  # back's own number, front's NOT copied in
    card_after = conn.execute("SELECT status FROM cards WHERE id = ?", (b_id,)).fetchone()
    assert card_after["status"] == "success"
    conn.close()
    os.remove(db)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All duplex worker tests passed.")
