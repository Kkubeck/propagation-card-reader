"""PDF scanner — builds card inventory from PDF files."""

import os
import fitz  # PyMuPDF
from schema import get_db, now_iso


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
