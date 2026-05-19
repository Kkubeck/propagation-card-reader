"""RAG-aware OCR worker built on top of the baseline worker helpers."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from filename_parser import parse_filename
from rag_context_builder import RAGContextBuilder
from rag_prompt import build_prompt
from schema import get_db, now_iso
from worker import extract_page_image, parse_json_response


LEGACY_RE = re.compile(r"^\d{5}-\d{3}-\d{2}(?:\.\d{1,2})?$")
MODERN_RE = re.compile(r"^\d{4}-\d{4,5}(?:\.\d{1,2})?$")


def call_ollama_with_prompt(ollama_url: str, model: str, image_b64: str, prompt_text: str) -> str:
    """Send image + prompt to Ollama vision API and return the response text.
    
    Uses /api/chat (required for vision models in Ollama >=0.23.4).
    """
    url = f"{ollama_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt_text,
                "images": [image_b64],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2048,  # Expanded for 22-field schema
        },
    }
    response = requests.post(url, json=payload, timeout=300)
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")


class RAGWorker:
    """Worker that enriches OCR prompts with filename-scoped retrieval context."""

    def __init__(self, db_path: str, rag_db_path: str, config: dict, mode: str = "rag_prompt"):
        self.db_path = db_path
        self.rag_db_path = rag_db_path
        self.config = config or {}
        self.mode = mode
        self.context_builder = RAGContextBuilder(rag_db_path, self.config)
        prompt_cfg = self.config.get("rag", {}).get("prompt", {})
        self.prompt_version = prompt_cfg.get(
            "version" if mode != "ocr_only" else "baseline_version",
            "v2.0-rag" if mode != "ocr_only" else "v1.0-baseline",
        )

    def close(self):
        self.context_builder.close()

    @staticmethod
    def _normalize_botanical_name(name: Any) -> str:
        if isinstance(name, list):
            name = " / ".join(str(item) for item in name)
        text = str(name or "").strip()
        return " ".join(text.split())

    @staticmethod
    def _normalize_propagation_text(text: Any) -> str:
        if isinstance(text, list):
            text = "\n".join(str(item) for item in text)
        return str(text or "")

    @staticmethod
    def _normalize_accessions(accessions: Any) -> list[str]:
        if isinstance(accessions, str):
            accessions = [accessions]
        if not isinstance(accessions, list):
            return []
        normalized: list[str] = []
        for value in accessions:
            text = str(value or "").strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_accession_value(accession: str) -> str:
        return accession.replace(" ", "").upper()

    @staticmethod
    def _classify_accession(accession: str) -> str:
        normalized = accession.replace(" ", "")
        if MODERN_RE.fullmatch(normalized):
            return "modern_item" if "." in normalized else "modern"
        if LEGACY_RE.fullmatch(normalized):
            return "legacy_item" if "." in normalized else "legacy"
        return "unknown"

    def process_card(self, conn, card, ollama_url, model, dpi):
        """Process a single card with optional RAG prompt enrichment."""
        card_id = card["id"]
        pdf_path = card["pdf_path"]
        page_num = card["page_num"]
        pdf_filename = os.path.basename(pdf_path)
        filename_hints = parse_filename(pdf_filename, self.rag_db_path)
        filename_hint_json = json.dumps(filename_hints, sort_keys=True)
        duplex_flag = 1 if filename_hints.get("duplex") else 0

        conn.execute(
            """
            UPDATE cards
            SET pdf_filename = ?, duplex_flag = ?, filename_hint_json = ?, excluded_reason = NULL,
                status = 'processing', processed_at = ?
            WHERE id = ?
            """,
            (pdf_filename, duplex_flag, filename_hint_json, now_iso(), card_id),
        )
        conn.commit()

        if duplex_flag:
            conn.execute(
                "UPDATE cards SET status = 'excluded', excluded_reason = ?, processed_at = ? WHERE id = ?",
                ("duplex_flag", now_iso(), card_id),
            )
            conn.commit()
            return "excluded", 0.0

        start = time.time()
        context_payload = {
            "context_text": "",
            "retrieval_query": filename_hints,
            "genera_retrieved": [],
            "taxa_count": 0,
            "accession_example_count": 0,
            "token_estimate": 0,
            "retrieval_latency_ms": 0.0,
        }
        prompt_mode = self.mode if self.mode in {"ocr_only", "rag_prompt"} else "ocr_only"

        try:
            if prompt_mode != "ocr_only":
                context_payload = self.context_builder.build_context(filename_hints)
            prompt_text = build_prompt(context_payload["context_text"], mode=prompt_mode)

            images_dir = os.path.join(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", "images")
            image_b64, image_path = extract_page_image(pdf_path, page_num, dpi, images_dir=images_dir)
            if image_path:
                conn.execute("UPDATE cards SET image_path = ? WHERE id = ?", (image_path, card_id))

            raw_response = call_ollama_with_prompt(ollama_url, model, image_b64, prompt_text)
            data = parse_json_response(raw_response)
            elapsed = time.time() - start

            botanical_name = self._normalize_botanical_name(data.get("botanical_name", ""))
            propagation_text = self._normalize_propagation_text(data.get("propagation_text", ""))

            # Primary accession number (string from the bordered field)
            primary_acc_raw = data.get("accession_number")
            if isinstance(primary_acc_raw, list):
                primary_accession_number = str(primary_acc_raw[0]).strip() if primary_acc_raw else None
            elif primary_acc_raw:
                primary_accession_number = str(primary_acc_raw).strip() or None
            else:
                primary_accession_number = None

            # All accession numbers (array from all_accession_numbers, fallback to accession_number)
            all_acc = data.get("all_accession_numbers", [])
            if not all_acc:
                all_acc = data.get("accession_number", [])
            accessions = self._normalize_accessions(all_acc)
            notes = data.get("notes", "")
            notes = self._normalize_propagation_text(notes).strip()

            # Card field extractions — all nullable text
            def _txt(key: str) -> str | None:
                v = data.get(key)
                if v is None:
                    return None
                s = str(v).strip()
                return s or None

            def _bool(key: str) -> int | None:
                v = data.get(key)
                if v is None:
                    return None
                if isinstance(v, bool):
                    return 1 if v else 0
                s = str(v).strip().lower()
                if s in ('true', 'yes', '1'):
                    return 1
                if s in ('false', 'no', '0'):
                    return 0
                return None

            family = _txt("family")
            received_as = _txt("received_as")
            date_received = _txt("date_received")
            geocode = _txt("geocode")
            quantity = _txt("quantity")
            present_location = _txt("present_location")
            wanted_for_area = _txt("wanted_for_area")
            source = _txt("source")
            source_info = _txt("source_info")
            collector_number = _txt("collector_number")
            other_number = _txt("other_number")
            labels_requested = _txt("labels_requested")
            max_quantity = _txt("max_quantity")
            parent_accession = _txt("parent_accession")
            collection_info = _txt("collection_info")
            distribution = _txt("distribution")
            curators_info = _txt("curators_info")
            iris_data_entered = _bool("iris_data_entered")

            cur = conn.execute(
                """
                INSERT INTO extractions
                    (card_id, botanical_name, propagation_text, raw_json, model, dpi,
                     processing_time_s, created_at, normalized_botanical_name,
                     prompt_text, prompt_context, notes,
                     family, received_as, date_received, geocode, quantity,
                     present_location, wanted_for_area, source, source_info,
                     collector_number, other_number, labels_requested, max_quantity,
                     parent_accession, collection_info, distribution,
                     accession_number, curators_info, iris_data_entered)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    botanical_name,
                    propagation_text,
                    raw_response,
                    model,
                    dpi,
                    elapsed,
                    now_iso(),
                    botanical_name,
                    prompt_text,
                    context_payload["context_text"] if prompt_mode != "ocr_only" else None,
                    notes or None,
                    family, received_as, date_received, geocode, quantity,
                    present_location, wanted_for_area, source, source_info,
                    collector_number, other_number, labels_requested, max_quantity,
                    parent_accession, collection_info, distribution,
                    primary_accession_number, curators_info, iris_data_entered,
                ),
            )
            extraction_id = cur.lastrowid

            for pos, accession in enumerate(accessions):
                normalized_accession = self._normalize_accession_value(accession)
                conn.execute(
                    """
                    INSERT INTO accession_numbers
                        (extraction_id, accession_number, position, normalized_accession_number, format_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        extraction_id,
                        accession,
                        pos,
                        normalized_accession,
                        self._classify_accession(normalized_accession),
                    ),
                )

            conn.execute(
                """
                INSERT INTO rag_contexts
                    (card_id, retrieval_query_json, context_text, context_token_estimate,
                     retrieval_latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    json.dumps(context_payload["retrieval_query"], sort_keys=True),
                    context_payload["context_text"] if prompt_mode != "ocr_only" else None,
                    context_payload["token_estimate"],
                    context_payload["retrieval_latency_ms"],
                    now_iso(),
                ),
            )

            conn.execute(
                "UPDATE cards SET status = 'success', processed_at = ?, excluded_reason = NULL WHERE id = ?",
                (now_iso(), card_id),
            )
            conn.commit()
            return "success", elapsed

        except json.JSONDecodeError as exc:
            elapsed = time.time() - start
            conn.execute(
                "UPDATE cards SET status = 'failed', error_message = ?, processed_at = ? WHERE id = ?",
                (f"JSON parse error: {exc}", now_iso(), card_id),
            )
            conn.commit()
            return "failed", elapsed

        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            conn.execute(
                "UPDATE cards SET status = 'error', error_message = ?, processed_at = ? WHERE id = ?",
                (f"Ollama timeout after {elapsed:.0f}s", now_iso(), card_id),
            )
            conn.commit()
            return "error", elapsed

        except requests.exceptions.RequestException as exc:
            elapsed = time.time() - start
            conn.execute(
                "UPDATE cards SET status = 'error', error_message = ?, processed_at = ? WHERE id = ?",
                (f"Ollama request error: {exc}", now_iso(), card_id),
            )
            conn.commit()
            return "error", elapsed

        except Exception as exc:
            elapsed = time.time() - start
            conn.execute(
                "UPDATE cards SET status = 'error', error_message = ?, processed_at = ? WHERE id = ?",
                (f"Unexpected error: {type(exc).__name__}: {exc}", now_iso(), card_id),
            )
            conn.commit()
            return "error", elapsed

    def process_batch(self, db_path, run_id, ollama_url, model, dpi, batch_size=None):
        """Main worker loop using the RAG-aware process_card implementation."""
        conn = get_db(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM cards WHERE status = 'pending'").fetchone()
            total_pending = row["cnt"]
            if total_pending == 0:
                print("No pending cards to process.")
                return

            limit = batch_size if batch_size else total_pending
            print(f"Processing up to {limit} of {total_pending} pending cards...")
            print(f"Model: {model} | DPI: {dpi} | Ollama: {ollama_url} | Mode: {self.mode}")
            print("-" * 70)

            processed = 0
            success_count = 0
            fail_count = 0

            while processed < limit:
                card = conn.execute("SELECT * FROM cards WHERE status = 'pending' ORDER BY id LIMIT 1").fetchone()
                if not card:
                    break
                processed += 1
                pdf_name = os.path.basename(card["pdf_path"])
                status, elapsed = self.process_card(conn, card, ollama_url, model, dpi)
                if status == "success":
                    success_count += 1
                elif status in {"failed", "error"}:
                    fail_count += 1
                print(f"Card {processed}/{limit} | {pdf_name} p{card['page_num']} | {elapsed:.1f}s | {status}")

            conn.execute(
                """
                UPDATE processing_runs
                SET success_count = success_count + ?,
                    fail_count = fail_count + ?,
                    ended_at = ?
                WHERE id = ?
                """,
                (success_count, fail_count, now_iso(), run_id),
            )
            conn.commit()
        finally:
            conn.close()
            self.close()

        print("-" * 70)
        print(f"Batch complete: {success_count} success, {fail_count} failed out of {processed} processed")
