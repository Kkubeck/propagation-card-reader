"""OCR processing worker — sends card images to Ollama vision LLM."""

import base64
import json
import re
import time

import fitz  # PyMuPDF
import requests

from schema import get_db, now_iso


PROMPT = """Read this scanned botanical garden propagation card. Extract as JSON:
{"accession_number": ["..."], "botanical_name": "...", "propagation_text": "full text as written"}
If multiple accession numbers exist, list all. Read numbers precisely."""


def extract_page_image(pdf_path, page_num, dpi, images_dir=None):
    """Extract a page from a PDF as a base64-encoded PNG.
    
    If images_dir is provided, saves the PNG there and returns (b64_str, saved_path).
    Otherwise returns (b64_str, None).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    saved_path = None
    
    if images_dir:
        os.makedirs(images_dir, exist_ok=True)
        # Filename: sanitized pdf name + page number
        pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
        safe_stem = re.sub(r'[^\w\-.]', '_', pdf_stem)
        saved_path = os.path.join(images_dir, f"{safe_stem}_p{page_num:04d}.png")
        with open(saved_path, 'wb') as f:
            f.write(png_bytes)
    
    return b64, saved_path


def parse_json_response(text):
    """Parse JSON from LLM response, handling common LLM quirks."""
    if not text or not text.strip():
        raise json.JSONDecodeError("Empty response from model", text or "", 0)
    
    # Strip markdown fences
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    
    text = text.strip()
    
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # "Extra data" fix: extract first complete JSON object
    brace_depth = 0
    in_string = False
    escape_next = False
    end_pos = None
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            if in_string:
                escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0:
                end_pos = i + 1
                break
    
    if end_pos:
        try:
            return json.loads(text[:end_pos])
        except json.JSONDecodeError:
            pass
    
    # Last resort: try to find any JSON object in the text
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
    if match:
        return json.loads(match.group(0))
    
    raise json.JSONDecodeError("No valid JSON found in response", text, 0)


def call_ollama(ollama_url, model, image_b64):
    """Send image to Ollama vision API and return parsed response.
    
    Uses /api/chat (required for vision models in Ollama >=0.23.4).
    """
    url = f"{ollama_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT,
                "images": [image_b64],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 512,
        }
    }
    
    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    
    result = resp.json()
    return result.get("message", {}).get("content", "")


def process_card(conn, card, ollama_url, model, dpi, db_path='cards.db'):
    """Process a single card: extract image, call LLM, store results."""
    card_id = card["id"]
    pdf_path = card["pdf_path"]
    page_num = card["page_num"]
    
    # Mark as processing
    conn.execute(
        "UPDATE cards SET status = 'processing', processed_at = ? WHERE id = ?",
        (now_iso(), card_id)
    )
    conn.commit()
    
    start = time.time()
    
    try:
        # Extract image (save to images/ subdir)
        images_dir = os.path.join(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', 'images')
        image_b64, image_path = extract_page_image(pdf_path, page_num, dpi, images_dir=images_dir)
        
        # Store image path
        if image_path:
            conn.execute("UPDATE cards SET image_path = ? WHERE id = ?", (image_path, card_id))
        
        # Call Ollama
        raw_response = call_ollama(ollama_url, model, image_b64)
        
        # Parse response
        data = parse_json_response(raw_response)
        
        elapsed = time.time() - start
        
        botanical_name = data.get("botanical_name", "")
        propagation_text = data.get("propagation_text", "")
        accessions = data.get("accession_number", [])
        
        # Normalize types — model sometimes returns lists instead of strings
        if isinstance(botanical_name, list):
            botanical_name = " / ".join(str(x) for x in botanical_name)
        if isinstance(propagation_text, list):
            propagation_text = "\n".join(str(x) for x in propagation_text)
        botanical_name = str(botanical_name) if botanical_name else ""
        propagation_text = str(propagation_text) if propagation_text else ""
        
        # Normalize accessions to list
        if isinstance(accessions, str):
            accessions = [accessions]
        if not isinstance(accessions, list):
            accessions = []
        
        # Insert extraction
        cur = conn.execute(
            """INSERT INTO extractions 
               (card_id, botanical_name, propagation_text, raw_json, model, dpi, processing_time_s, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, botanical_name, propagation_text, raw_response, model, dpi, elapsed, now_iso())
        )
        extraction_id = cur.lastrowid
        
        # Insert accession numbers
        for pos, acc in enumerate(accessions):
            conn.execute(
                """INSERT INTO accession_numbers (extraction_id, accession_number, position)
                   VALUES (?, ?, ?)""",
                (extraction_id, str(acc), pos)
            )
        
        # Mark success
        conn.execute(
            "UPDATE cards SET status = 'success', processed_at = ? WHERE id = ?",
            (now_iso(), card_id)
        )
        conn.commit()
        
        return "success", elapsed
        
    except json.JSONDecodeError as e:
        elapsed = time.time() - start
        error_msg = f"JSON parse error: {e}"
        conn.execute(
            "UPDATE cards SET status = 'failed', error_message = ?, processed_at = ? WHERE id = ?",
            (error_msg, now_iso(), card_id)
        )
        conn.commit()
        return "failed", elapsed
        
    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start
        error_msg = f"Ollama request error: {e}"
        conn.execute(
            "UPDATE cards SET status = 'error', error_message = ?, processed_at = ? WHERE id = ?",
            (error_msg, now_iso(), card_id)
        )
        conn.commit()
        return "error", elapsed
        
    except Exception as e:
        elapsed = time.time() - start
        error_msg = f"Unexpected error: {type(e).__name__}: {e}"
        conn.execute(
            "UPDATE cards SET status = 'error', error_message = ?, processed_at = ? WHERE id = ?",
            (error_msg, now_iso(), card_id)
        )
        conn.commit()
        return "error", elapsed


def process_batch(db_path, run_id, ollama_url, model, dpi, batch_size=None):
    """Main worker loop — process pending cards."""
    conn = get_db(db_path)
    
    # Count pending
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM cards WHERE status = 'pending'"
    ).fetchone()
    total_pending = row["cnt"]
    
    if total_pending == 0:
        print("No pending cards to process.")
        conn.close()
        return
    
    limit = batch_size if batch_size else total_pending
    print(f"Processing up to {limit} of {total_pending} pending cards...")
    print(f"Model: {model} | DPI: {dpi} | Ollama: {ollama_url}")
    print("-" * 70)
    
    processed = 0
    success_count = 0
    fail_count = 0
    
    while processed < limit:
        # Fetch next pending card
        card = conn.execute(
            "SELECT * FROM cards WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        
        if not card:
            break
        
        processed += 1
        pdf_name = os.path.basename(card["pdf_path"]) if "/" in card["pdf_path"] or "\\" in card["pdf_path"] else card["pdf_path"]
        
        status, elapsed = process_card(conn, card, ollama_url, model, dpi, db_path=db_path)
        
        if status == "success":
            success_count += 1
        else:
            fail_count += 1
        
        print(f"Card {processed}/{limit} | {pdf_name} p{card['page_num']} | {elapsed:.1f}s | {status}")
    
    # Update run stats
    conn.execute(
        """UPDATE processing_runs 
           SET success_count = success_count + ?, 
               fail_count = fail_count + ?,
               ended_at = ?
           WHERE id = ?""",
        (success_count, fail_count, now_iso(), run_id)
    )
    conn.commit()
    conn.close()
    
    print("-" * 70)
    print(f"Batch complete: {success_count} success, {fail_count} failed out of {processed} processed")


# Need os for basename in process_batch
import os
