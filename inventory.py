"""PDF scanner — builds card inventory from PDF files."""

import os
import pymupdf as fitz  # PyMuPDF
from schema import get_db, now_iso
from filename_parser import parse_filename


def build_inventory(pdf_dir, db_path, run_id):
    """Scan all PDFs in directory, enumerate pages, insert as pending cards.
    
    Idempotent: skips cards that already exist (same pdf_path + page_num).
    """
    conn = get_db(db_path)
    
    pdf_files = sorted([
        f for f in os.listdir(pdf_dir)
        if f.lower().endswith('.pdf')
    ])
    
    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}")
        conn.close()
        return
    
    total_pages = 0
    new_cards = 0
    existing_cards = 0
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        
        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            doc.close()
        except Exception as e:
            print(f"  ERROR reading {pdf_file}: {e}")
            continue
        
        total_pages += page_count
        
        for page_num in range(page_count):
            try:
                conn.execute(
                    """INSERT INTO cards (run_id, pdf_path, page_num, status, created_at)
                       VALUES (?, ?, ?, 'pending', ?)""",
                    (run_id, pdf_path, page_num, now_iso())
                )
                new_cards += 1
            except Exception:
                # UNIQUE constraint — already exists
                existing_cards += 1
    
    conn.commit()
    
    # Update run total
    conn.execute(
        "UPDATE processing_runs SET total_cards = ? WHERE id = ?",
        (new_cards + existing_cards, run_id)
    )
    conn.commit()
    conn.close()
    
    print(f"\n--- Inventory Summary ---")
    print(f"PDFs scanned:    {len(pdf_files)}")
    print(f"Total pages:     {total_pages}")
    print(f"New cards added: {new_cards}")
    print(f"Already existed: {existing_cards}")

    # Assign front/back pairing for any duplex PDFs now in the inventory.
    assign_duplex_pairing(db_path)


def assign_duplex_pairing(db_path):
    """Assign card_face + pair_id to the pages of duplex PDFs. Idempotent.

    Duplex detection reuses filename_parser.parse_filename (filename markers).
    Kevin reshuffles cards between front/back scan passes, so for an N-page
    duplex PDF the page order is: pages [0 .. N/2-1] are fronts (in order) and
    pages [N/2 .. N-1] are backs (same order). pair_id links front i to back i;
    no reversal math is needed.

    Odd-paged duplex PDFs cannot be paired (e.g. a missed/extra scan) and are
    flagged via excluded_reason rather than guessed at. Single-sided PDFs are
    left untouched (card_face / pair_id stay NULL).

    Re-running overwrites the same deterministic values, so it is safe to call
    after every inventory pass.
    """
    conn = get_db(db_path)
    try:
        pdf_paths = [row[0] for row in conn.execute("SELECT DISTINCT pdf_path FROM cards")]
        duplex_pdfs = paired = skipped_odd = 0

        for pdf_path in pdf_paths:
            if not parse_filename(os.path.basename(pdf_path)).get("duplex"):
                continue
            duplex_pdfs += 1
            pages = [row[0] for row in conn.execute(
                "SELECT page_num FROM cards WHERE pdf_path = ? ORDER BY page_num",
                (pdf_path,),
            )]
            n = len(pages)
            if n == 0:
                continue
            if n % 2 != 0:
                # Cannot pair an odd page count — flag, don't guess.
                conn.execute(
                    """UPDATE cards
                       SET duplex_flag = 1,
                           excluded_reason = ?
                       WHERE pdf_path = ?""",
                    (f"odd page count ({n}) in duplex PDF — cannot pair fronts/backs", pdf_path),
                )
                skipped_odd += 1
                continue
            half = n // 2
            for idx, page_num in enumerate(pages):
                face, pair_id = ("front", idx) if idx < half else ("back", idx - half)
                conn.execute(
                    """UPDATE cards
                       SET duplex_flag = 1,
                           card_face = ?,
                           pair_id = ?
                       WHERE pdf_path = ? AND page_num = ?""",
                    (face, pair_id, pdf_path, page_num),
                )
                paired += 1
        conn.commit()
    finally:
        conn.close()

    print(f"\n--- Duplex Pairing ---")
    print(f"Duplex PDFs:     {duplex_pdfs}")
    print(f"Pages paired:    {paired}")
    print(f"Odd PDFs skipped: {skipped_odd}")
