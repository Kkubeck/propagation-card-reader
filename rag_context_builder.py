"""Compact RAG context assembly for propagation card OCR."""

from __future__ import annotations

import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any


class RAGContextBuilder:
    """Retrieve compact genus/range-scoped hints from rag.db."""

    def __init__(self, rag_db_path: str, config: dict):
        self.rag_db_path = str(rag_db_path)
        self.config = config or {}
        rag_cfg = self.config.get("rag", {})
        self.context_budget = rag_cfg.get("context_budget", {})
        self.max_taxa = int(self.context_budget.get("max_taxa", 15))
        self.max_accession_examples = int(self.context_budget.get("max_accession_examples", 10))
        self.max_genera_in_range = int(self.context_budget.get("max_genera_in_range", 20))
        self.max_context_chars = int(self.context_budget.get("max_context_chars", 2000))
        cache_size = int(rag_cfg.get("caching", {}).get("genus_cache_size", 128))

        self._conn: sqlite3.Connection | None = None
        self.available = Path(self.rag_db_path).exists()
        if self.available:
            self._conn = sqlite3.connect(self.rag_db_path)
            self._conn.row_factory = sqlite3.Row

        self._get_genus_context = lru_cache(maxsize=cache_size)(self._get_genus_context_uncached)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        if self._conn is None:
            return []
        return list(self._conn.execute(sql, params))

    def _fetch_global_examples(self) -> dict[str, str]:
        legacy = self._query(
            "SELECT accession_number FROM rag_accessions WHERE accession_format_type='legacy' ORDER BY accession_year DESC, accession_number DESC LIMIT 1"
        )
        modern = self._query(
            "SELECT accession_number FROM rag_accessions WHERE accession_format_type='modern' ORDER BY accession_year DESC, accession_number DESC LIMIT 1"
        )
        item = self._query(
            "SELECT item_accession_number FROM rag_items WHERE item_accession_number IS NOT NULL ORDER BY item_accession_number DESC LIMIT 1"
        )
        return {
            "legacy": legacy[0]["accession_number"] if legacy else "21420-027-82",
            "modern": modern[0]["accession_number"] if modern else "2015-00444",
            "item": item[0]["item_accession_number"] if item else "2019-0082.99",
        }

    def _query_synonyms(self, genus: str) -> list[sqlite3.Row]:
        """Fetch synonym mappings for a genus, gracefully handling missing table."""
        try:
            return self._query(
                """
                SELECT synonym_name, accepted_name
                FROM rag_synonyms
                WHERE synonym_genus = ? OR accepted_genus = ?
                ORDER BY synonym_name
                """,
                (genus, genus),
            )
        except Exception:
            return []

    def _build_taxonomy_checklist(
        self, taxa_lines: list[str], synonym_rows: list[sqlite3.Row], max_lines: int = 40
    ) -> list[str]:
        """Build a compact taxonomy checklist from accepted names + synonyms."""
        if not taxa_lines and not synonym_rows:
            return []

        # Build synonym lookup: accepted_name -> list of synonym_names
        syn_map: dict[str, list[str]] = {}
        extra_synonyms: list[tuple[str, str]] = []  # synonyms whose accepted name isn't in taxa_lines
        taxa_set = {t.lower() for t in taxa_lines if t}
        for row in synonym_rows:
            accepted = row["accepted_name"]
            synonym = row["synonym_name"]
            if not accepted or not synonym:
                continue
            if accepted.lower() in taxa_set:
                syn_map.setdefault(accepted, []).append(synonym)
            else:
                extra_synonyms.append((synonym, accepted))

        lines: list[str] = []
        for taxon in taxa_lines:
            syns = syn_map.get(taxon)
            if syns:
                syn_text = ", ".join(sorted(syns)[:3])  # Limit synonyms per name
                lines.append(f"- {taxon} (syn: {syn_text})")
            else:
                lines.append(f"- {taxon}")
            if len(lines) >= max_lines:
                break

        # Add synonyms that map to names outside the current taxa list
        for synonym, accepted in extra_synonyms:
            if len(lines) >= max_lines:
                break
            lines.append(f"- {synonym} -> accepted: {accepted}")

        return lines

    def _get_genus_context_uncached(self, genus: str) -> dict[str, Any]:
        taxa_rows = self._query(
            """
            SELECT taxon_name_full, observation_count, first_accession_year, last_accession_year
            FROM rag_taxa
            WHERE genus = ?
            ORDER BY observation_count DESC, taxon_name_full
            LIMIT ?
            """,
            (genus, self.max_taxa),
        )
        synonym_rows = self._query_synonyms(genus)
        legacy_rows = self._query(
            """
            SELECT accession_number, taxon_name_full, accession_format_type, accession_year
            FROM rag_accessions
            WHERE genus = ? AND accession_format_type = 'legacy'
            ORDER BY accession_year DESC, accession_number DESC
            LIMIT ?
            """,
            (genus, self.max_accession_examples),
        )
        modern_rows = self._query(
            """
            SELECT accession_number, taxon_name_full, accession_format_type, accession_year
            FROM rag_accessions
            WHERE genus = ? AND accession_format_type = 'modern'
            ORDER BY accession_year DESC, accession_number DESC
            LIMIT ?
            """,
            (genus, self.max_accession_examples),
        )
        accession_rows = legacy_rows + modern_rows
        suffix_rows = self._query(
            """
            SELECT item_suffix, COUNT(*) AS cnt
            FROM rag_items
            WHERE genus = ?
              AND item_suffix IS NOT NULL
              AND item_suffix != ''
              AND LENGTH(item_suffix) <= 2
            GROUP BY item_suffix
            ORDER BY cnt DESC, item_suffix
            LIMIT 10
            """,
            (genus,),
        )
        year_row = self._query(
            "SELECT MIN(accession_year) AS min_year, MAX(accession_year) AS max_year FROM rag_accessions WHERE genus = ?",
            (genus,),
        )
        return {
            "taxa_rows": taxa_rows,
            "accession_rows": accession_rows,
            "suffix_rows": suffix_rows,
            "year_span": year_row[0] if year_row else None,
            "synonym_rows": synonym_rows,
        }

    def _pick_accession_examples(self, accession_rows: list[sqlite3.Row], limit: int) -> list[str]:
        if not accession_rows:
            return []
        legacy: list[str] = []
        modern: list[str] = []
        seen: set[str] = set()
        for row in accession_rows:
            accession = row["accession_number"]
            if accession in seen:
                continue
            seen.add(accession)
            label = accession
            taxon = row["taxon_name_full"]
            if taxon:
                label = f"{label} -> {taxon}"
            if row["accession_format_type"] == "legacy":
                legacy.append(label)
            else:
                modern.append(label)

        mixed: list[str] = []
        while len(mixed) < limit and (legacy or modern):
            if legacy and len(mixed) < limit:
                mixed.append(legacy.pop(0))
            if modern and len(mixed) < limit:
                mixed.append(modern.pop(0))
        return mixed

    def _range_taxa_lines(self, genera: list[str]) -> list[str]:
        if not genera:
            return []
        per_genus = 3 if len(genera) <= 5 else 2
        lines: list[str] = []
        for genus in genera:
            ctx = self._get_genus_context(genus)
            genus_taxa = []
            for row in ctx["taxa_rows"][:per_genus]:
                genus_taxa.append(row["taxon_name_full"])
            for taxon in genus_taxa:
                if taxon not in lines:
                    lines.append(taxon)
                if len(lines) >= self.max_taxa:
                    return lines
        return lines[: self.max_taxa]

    def _range_accession_examples(self, genera: list[str], limit: int) -> list[str]:
        examples: list[str] = []
        seen: set[str] = set()
        for genus in genera:
            ctx = self._get_genus_context(genus)
            for label in self._pick_accession_examples(ctx["accession_rows"], limit=2):
                accession = label.split(" -> ", 1)[0]
                if accession in seen:
                    continue
                seen.add(accession)
                examples.append(label)
                if len(examples) >= limit:
                    return examples
        return examples

    def _describe_hint(self, filename_hints: dict[str, Any], genera_in_scope: list[str], year_span_text: str | None) -> str:
        hint_mode = filename_hints.get("hint_mode", "none")
        confidence = float(filename_hints.get("confidence", 0.0) or 0.0)
        if hint_mode == "exact_genus" and genera_in_scope:
            text = f"File suggests genus {genera_in_scope[0]}"
        elif hint_mode == "range_prefix" and genera_in_scope:
            text = f"File suggests genus range {genera_in_scope[0]}–{genera_in_scope[-1]}"
        elif hint_mode == "single_prefix" and genera_in_scope:
            text = f"File suggests a narrow genus scope near {genera_in_scope[0]}–{genera_in_scope[-1]}"
        else:
            text = "No reliable filename hint was found"
        if confidence:
            text = f"{text} (confidence {confidence:.2f})"
        if filename_hints.get("duplex"):
            text += "; filename is marked duplex"
        if year_span_text:
            text += f"; observed year span {year_span_text}"
        return text

    def _compose_context(
        self,
        hint_description: str,
        taxa_lines: list[str],
        accession_examples: list[str],
        suffixes: list[str],
        examples: dict[str, str],
        taxonomy_checklist: list[str] | None = None,
    ) -> str:
        taxa_block = "\n".join(f"- {line}" for line in taxa_lines) if taxa_lines else "- No genus-specific taxa retrieved"
        accession_block = (
            "\n".join(f"- {line}" for line in accession_examples)
            if accession_examples
            else "- No scoped accession examples retrieved"
        )
        suffix_block = " ".join(f".{suffix}" for suffix in suffixes) if suffixes else "(none observed)"
        taxonomy_block = ""
        if taxonomy_checklist:
            taxonomy_block = (
                "\n\nValid botanical names for this scope:\n"
                + "\n".join(taxonomy_checklist)
                + "\nIf the card name closely matches one of these, prefer the listed spelling."
            )
        return (
            "Garden accession rules:\n"
            f"- Legacy format: NNNNN-NNN-NN (example: {examples['legacy']})\n"
            f"- Modern format: YYYY-NNNNN (example: {examples['modern']})\n"
            f"- Item suffix: .NN (example: {examples['item']})\n"
            "- Bare numbers like 1 or 3 are not valid accessions\n"
            "- Blank accession may be legitimate on pre-2012 failed germination cards\n\n"
            "Filename hint:\n"
            f"- {hint_description}\n\n"
            "Known genera/taxa seen in this scope:\n"
            f"{taxa_block}\n\n"
            "Example accessions from this scope:\n"
            f"{accession_block}\n\n"
            "Observed item suffixes:\n"
            f"- {suffix_block}"
            f"{taxonomy_block}"
        )

    def _shrink_text(
        self,
        context_text: str,
        hint_description: str,
        taxa_lines: list[str],
        accession_examples: list[str],
        suffixes: list[str],
        examples: dict[str, str],
        taxonomy_checklist: list[str] | None = None,
    ) -> tuple[str, list[str], list[str]]:
        current_taxa = list(taxa_lines)
        current_examples = list(accession_examples)
        current_checklist = list(taxonomy_checklist) if taxonomy_checklist else []
        text = context_text
        while len(text) > self.max_context_chars and (current_checklist or current_taxa or current_examples):
            # Trim taxonomy checklist first, then accession examples, then taxa
            if current_checklist:
                current_checklist.pop()
            elif len(current_examples) > max(1, min(3, self.max_accession_examples // 2)):
                current_examples.pop()
            elif current_taxa:
                current_taxa.pop()
            else:
                break
            text = self._compose_context(
                hint_description, current_taxa, current_examples, suffixes, examples,
                taxonomy_checklist=current_checklist or None,
            )
        if len(text) > self.max_context_chars:
            text = text[: self.max_context_chars - 3].rstrip() + "..."
        return text, current_taxa, current_examples

    def build_context(self, filename_hints: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        examples = self._fetch_global_examples()

        hint_mode = filename_hints.get("hint_mode", "none")
        confidence = float(filename_hints.get("confidence", 0.0) or 0.0)
        genera = [str(genus) for genus in filename_hints.get("genus_candidates", []) if genus]
        retrieval_query: dict[str, Any] = {
            "hint_mode": hint_mode,
            "confidence": confidence,
            "genus_candidates": genera,
            "range_start": filename_hints.get("range_start"),
            "range_end": filename_hints.get("range_end"),
            "duplex": bool(filename_hints.get("duplex", False)),
            "rag_available": self.available,
        }

        if not self.available or hint_mode == "none" or confidence < 0.3:
            hint_description = self._describe_hint(filename_hints, [], None)
            context_text = self._compose_context(hint_description, [], [], [], examples)
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "context_text": context_text,
                "retrieval_query": retrieval_query,
                "genera_retrieved": [],
                "taxa_count": 0,
                "accession_example_count": 0,
                "token_estimate": max(1, len(context_text) // 4),
                "retrieval_latency_ms": latency_ms,
            }

        genera_in_scope: list[str] = []
        taxa_lines: list[str] = []
        accession_examples: list[str] = []
        suffixes: list[str] = []
        year_span_text: str | None = None
        all_synonym_rows: list[sqlite3.Row] = []

        if hint_mode == "exact_genus" and confidence >= 0.8 and genera:
            genus = genera[0]
            genera_in_scope = [genus]
            ctx = self._get_genus_context(genus)
            taxa_lines = [row["taxon_name_full"] for row in ctx["taxa_rows"][: self.max_taxa] if row["taxon_name_full"]]
            accession_examples = self._pick_accession_examples(ctx["accession_rows"], self.max_accession_examples)
            suffixes = [row["item_suffix"] for row in ctx["suffix_rows"]]
            all_synonym_rows = ctx.get("synonym_rows", [])
            span = ctx.get("year_span")
            if span and span["min_year"] and span["max_year"]:
                year_span_text = f"{span['min_year']}-{span['max_year']}"
        elif hint_mode == "range_prefix" and genera:
            genera_in_scope = genera[: self.max_genera_in_range]
            taxa_lines = self._range_taxa_lines(genera_in_scope)
            accession_examples = self._range_accession_examples(genera_in_scope, limit=min(5, self.max_accession_examples))
            suffix_counts: dict[str, int] = {}
            min_year: int | None = None
            max_year: int | None = None
            for genus in genera_in_scope:
                ctx = self._get_genus_context(genus)
                for row in ctx["suffix_rows"]:
                    suffix_counts[row["item_suffix"]] = suffix_counts.get(row["item_suffix"], 0) + int(row["cnt"])
                all_synonym_rows.extend(ctx.get("synonym_rows", []))
                span = ctx.get("year_span")
                if span:
                    if span["min_year"] is not None:
                        min_year = span["min_year"] if min_year is None else min(min_year, span["min_year"])
                    if span["max_year"] is not None:
                        max_year = span["max_year"] if max_year is None else max(max_year, span["max_year"])
            suffixes = [k for k, _ in sorted(suffix_counts.items(), key=lambda item: (-item[1], item[0]))[:10]]
            if min_year is not None and max_year is not None:
                year_span_text = f"{min_year}-{max_year}"
        else:
            hint_description = self._describe_hint(filename_hints, [], None)
            context_text = self._compose_context(hint_description, [], [], [], examples)
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "context_text": context_text,
                "retrieval_query": retrieval_query,
                "genera_retrieved": [],
                "taxa_count": 0,
                "accession_example_count": 0,
                "token_estimate": max(1, len(context_text) // 4),
                "retrieval_latency_ms": latency_ms,
            }

        hint_description = self._describe_hint(filename_hints, genera_in_scope, year_span_text)
        taxonomy_checklist = self._build_taxonomy_checklist(taxa_lines, all_synonym_rows)
        context_text = self._compose_context(
            hint_description, taxa_lines, accession_examples, suffixes, examples,
            taxonomy_checklist=taxonomy_checklist or None,
        )
        context_text, kept_taxa, kept_examples = self._shrink_text(
            context_text,
            hint_description,
            taxa_lines,
            accession_examples,
            suffixes,
            examples,
            taxonomy_checklist=taxonomy_checklist,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        retrieval_query["retrieved_genera"] = genera_in_scope
        return {
            "context_text": context_text,
            "retrieval_query": retrieval_query,
            "genera_retrieved": genera_in_scope,
            "taxa_count": len(kept_taxa),
            "accession_example_count": len(kept_examples),
            "token_estimate": max(1, len(context_text) // 4),
            "retrieval_latency_ms": latency_ms,
        }
