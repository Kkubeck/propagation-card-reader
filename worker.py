"""OCR processing worker — sends card images to Ollama vision LLM."""

import base64
import json
import re
import time

import fitz  # PyMuPDF
import requests

from schema import get_db, now_iso
from rag_prompt import BASELINE_PROMPT


# Default prompt for ocr_only mode (RAG mode uses rag_prompt.build_prompt)
PROMPT = BASELINE_PROMPT

# All extraction fields in DB column order (excluding raw_json, model, dpi, processing_time_s, created_at)
EXTRACTION_FIELDS = [
    "botanical_name", "family", "geocode", "received_as", "quantity",
    "date_received", "present_location", "wanted_for_area", "source",
    "source_info", "collector_number", "other_number", "labels_requested",
    "max_quantity", "parent_accession", "collection_info", "distribution",
    "accession_number", "propagation_text", "curators_info", "iris_data_entered",
]


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
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # --- JSON repair pass ---
    # LLMs (especially smaller vision models) often produce broken JSON:
    # missing commas, trailing commas, truncated output, unescaped control chars.
    # Try to fix common issues before giving up.
    
    def _repair_json(raw):
        """Attempt to repair common JSON syntax errors from LLM output."""
        s = raw
        
        # 1. Fix unescaped control characters inside string values
        # Replace literal tabs and other control chars (except already-escaped ones)
        # We process char-by-char to only fix chars inside strings
        repaired_chars = []
        in_str = False
        esc = False
        for c in s:
            if esc:
                repaired_chars.append(c)
                esc = False
                continue
            if c == '\\' and in_str:
                repaired_chars.append(c)
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                repaired_chars.append(c)
                continue
            if in_str and c == '\n':
                repaired_chars.append('\\n')
                continue
            if in_str and c == '\r':
                repaired_chars.append('\\r')
                continue
            if in_str and c == '\t':
                repaired_chars.append('\\t')
                continue
            repaired_chars.append(c)
        s = ''.join(repaired_chars)
        
        # 2. Fix missing commas between key-value pairs
        # Pattern: value followed by whitespace then a new key (quoted string + colon)
        # e.g. '"value"\n  "next_key":' or 'null\n  "next_key":'
        # Handles: string values, null, true, false, numbers before a missing comma
        s = re.sub(
            r'("[^"]*"|null|true|false|\d+(?:\.\d+)?)\s*\n(\s*")',
            r'\1,\n\2',
            s
        )
        
        # 3. Fix trailing commas before closing braces/brackets
        s = re.sub(r',\s*([}\]])', r'\1', s)
        
        # 4. Fix truncated JSON — try to close open structures
        # Count unbalanced braces/brackets (outside strings)
        open_braces = 0
        open_brackets = 0
        in_str2 = False
        esc2 = False
        for c in s:
            if esc2:
                esc2 = False
                continue
            if c == '\\' and in_str2:
                esc2 = True
                continue
            if c == '"':
                in_str2 = not in_str2
                continue
            if in_str2:
                continue
            if c == '{':
                open_braces += 1
            elif c == '}':
                open_braces -= 1
            elif c == '[':
                open_brackets += 1
            elif c == ']':
                open_brackets -= 1
        
        # If we ended inside a string, close it
        if in_str2:
            s += '"'
        
        # Remove any trailing comma before we close structures
        s = s.rstrip()
        s = re.sub(r',\s*$', '', s)
        
        # Close any open brackets then braces
        s += ']' * max(0, open_brackets)
        s += '}' * max(0, open_braces)
        
        return s
    
    try:
        repaired = _repair_json(text)
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    
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
            "num_predict": 2048,  # Expanded for 22-field schema
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
        
        # --- Extract all fields ---
        def _str_field(val):
            """Normalize a field value to string or None."""
            if val is None:
                return None
            if isinstance(val, list):
                return " / ".join(str(x) for x in val)
            s = str(val).strip()
            return s if s else None

        def _text_field(val):
            """Normalize a text field (may be list of lines) to string or None."""
            if val is None:
                return None
            if isinstance(val, list):
                return "\n".join(str(x) for x in val)
            s = str(val).strip()
            return s if s else None

        field_vals = {}
        for fname in EXTRACTION_FIELDS:
            raw_val = data.get(fname)
            if fname == "propagation_text":
                field_vals[fname] = _text_field(raw_val)
            elif fname == "iris_data_entered":
                # Store as integer: 1/0/None
                if raw_val is True:
                    field_vals[fname] = 1
                elif raw_val is False:
                    field_vals[fname] = 0
                else:
                    field_vals[fname] = None
            elif fname == "accession_number":
                # Primary accession — string (model may return list, take first)
                if isinstance(raw_val, list):
                    field_vals[fname] = str(raw_val[0]).strip() if raw_val else None
                else:
                    field_vals[fname] = _str_field(raw_val)
            else:
                field_vals[fname] = _str_field(raw_val)

        # All accession numbers (array) — from all_accession_numbers or fallback to accession_number array
        all_acc = data.get("all_accession_numbers", [])
        if not all_acc:
            # Fallback: if model didn't produce all_accession_numbers, use accession_number
            fallback = data.get("accession_number", [])
            if isinstance(fallback, list):
                all_acc = fallback
            elif fallback:
                all_acc = [fallback]
        if isinstance(all_acc, str):
            all_acc = [all_acc]
        if not isinstance(all_acc, list):
            all_acc = []

        # Clean up any previous extraction for this card (re-processing)
        old_ext = conn.execute("SELECT id FROM extractions WHERE card_id = ?", (card_id,)).fetchone()
        if old_ext:
            conn.execute("DELETE FROM accession_numbers WHERE extraction_id = ?", (old_ext[0],))
            conn.execute("DELETE FROM extractions WHERE id = ?", (old_ext[0],))

        # Build INSERT for extractions with all fields
        col_names = ["card_id"] + EXTRACTION_FIELDS + ["raw_json", "model", "dpi", "processing_time_s", "created_at"]
        col_placeholders = ", ".join(["?"] * len(col_names))
        col_values = (
            [card_id]
            + [field_vals[f] for f in EXTRACTION_FIELDS]
            + [raw_response, model, dpi, elapsed, now_iso()]
        )
        cur = conn.execute(
            f"INSERT INTO extractions ({', '.join(col_names)}) VALUES ({col_placeholders})",
            col_values,
        )
        extraction_id = cur.lastrowid

        # Insert all accession numbers into junction table
        for pos, acc in enumerate(all_acc):
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
