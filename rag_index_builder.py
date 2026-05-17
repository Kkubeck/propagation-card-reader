"""Build a compact SQLite RAG index from accession CSV exports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from rag_config import load_config
from rag_schema import get_db, init_db


PROGRESS_EVERY = 5000
DASH_TRANSLATION = str.maketrans({"–": "-", "—": "-", "−": "-"})
AUTHORSHIP_TOKENS = {
    "subsp.",
    "subsp",
    "ssp.",
    "ssp",
    "var.",
    "var",
    "f.",
    "f",
    "cv.",
    "cv",
    "x",
    "×",
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_accession(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    value = value.translate(DASH_TRANSLATION)
    value = re.sub(r"\s*([./-])\s*", r"\1", value)
    value = re.sub(r"\s+", "", value)
    return value.upper()


def normalize_legacy_accession(acc_no_cons: str | None) -> str | None:
    value = clean_text(acc_no_cons)
    if not value or value == "0":
        return None
    value = value.translate(DASH_TRANSLATION)
    match = re.fullmatch(r"(\d{5})/(\d)-(\d{4})-(\d{4})", value)
    if match:
        prefix, _series, middle, year = match.groups()
        return f"{prefix}-{middle[-3:]}-{year[-2:]}"
    digits = re.findall(r"\d+", value)
    if len(digits) >= 3 and len(digits[0]) >= 5:
        prefix = digits[0][:5]
        middle = digits[-2][-3:].zfill(3)
        year = digits[-1][-2:]
        return f"{prefix}-{middle}-{year}"
    return normalize_accession(value)


def parse_boolish(value: str | None) -> int | None:
    value = clean_text(value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {">>>", "y", "yes", "true", "1", "current", "active"}:
        return 1
    if normalized in {"n", "no", "false", "0", "inactive", "former"}:
        return 0
    return None


def normalize_date(value: str | None) -> str | None:
    value = clean_text(value)
    if not value or value in {"9999-12-31", "9999/12/31"}:
        return None
    value = value.replace("/", "-")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return value


def build_infra_text(infra_type: str | None, infra_name: str | None) -> str | None:
    infra_type = clean_text(infra_type)
    infra_name = clean_text(infra_name)
    if infra_type and infra_name:
        return f"{infra_type} {infra_name}"
    return infra_type or infra_name


def normalize_taxon_for_compare(value: str | None) -> str:
    value = clean_text(value)
    if not value:
        return ""
    raw_tokens = [token.strip(",.;:()[]{}") for token in value.translate(DASH_TRANSLATION).split()]
    kept: list[str] = []
    for token in raw_tokens:
        if not token:
            continue
        lower = token.lower()
        if lower in AUTHORSHIP_TOKENS:
            kept.append(lower)
            continue
        if kept and token[0].isupper() and lower not in {"x", "×"}:
            break
        if len(lower) == 1 and lower.isalpha() and lower not in {"x", "×"}:
            break
        kept.append(lower)
    text = " ".join(kept).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s×x.-]", "", text)
    return text


def row_hash(row: dict[str, str]) -> str:
    payload = "\x1f".join(f"{key}={row.get(key, '')}" for key in sorted(row))
    return hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()


def derive_accession_number(row: dict[str, str]) -> tuple[str | None, str | None]:
    legacy = normalize_legacy_accession(row.get("AccNoCons"))
    if legacy:
        return legacy, "legacy"
    modern = normalize_accession(row.get("AccNoFull") or row.get("AccNo"))
    if modern:
        return modern, "modern"
    return None, None


def derive_accession_year(row: dict[str, str], accession_number: str | None, fmt: str | None) -> int | None:
    raw_year = clean_text(row.get("AccYear"))
    if raw_year and raw_year.isdigit():
        return int(raw_year)
    if not accession_number:
        return None
    if fmt == "modern":
        match = re.match(r"(\d{4})-", accession_number)
        if match:
            return int(match.group(1))
    if fmt == "legacy":
        match = re.search(r"-(\d{2})$", accession_number)
        if match:
            year = int(match.group(1))
            return 1900 + year if year >= 30 else 2000 + year
    return None


def extract_parent_and_suffix(item_accession_number: str | None, parent_hint: str | None = None) -> tuple[str | None, str | None]:
    item_accession_number = normalize_accession(item_accession_number)
    if item_accession_number and "." in item_accession_number:
        parent, suffix = item_accession_number.rsplit(".", 1)
        return parent, suffix
    parent = normalize_accession(parent_hint)
    suffix = None
    if item_accession_number and parent and item_accession_number.startswith(parent):
        suffix = item_accession_number[len(parent):].lstrip(".") or None
    return parent, suffix


def iter_csv_rows(path: str) -> Iterable[dict[str, str]]:
    with open(path, "r", encoding="latin-1", newline="") as handle:
        yield from csv.DictReader(handle)


def rebuild_database(db_path: str) -> None:
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()
    wal = db_file.with_suffix(db_file.suffix + "-wal")
    shm = db_file.with_suffix(db_file.suffix + "-shm")
    for sidecar in (wal, shm):
        if sidecar.exists():
            sidecar.unlink()
    init_db(str(db_file))


def build_index(config_path: str | None = None) -> dict[str, int]:
    def build_short_taxon_name(genus: str | None, species: str | None, infra_text: str | None, taxon_name_full: str | None) -> str | None:
        parts = [part for part in (genus, species, infra_text) if part]
        if parts:
            return " ".join(parts)
        full_name = clean_text(taxon_name_full)
        if not full_name:
            return None
        tokens = full_name.split()
        short_tokens: list[str] = []
        for token in tokens:
            short_tokens.append(token)
            if len(short_tokens) >= 2 and token and token[0].isupper() and token.lower() not in AUTHORSHIP_TOKENS:
                short_tokens.pop()
                break
        return " ".join(short_tokens) or full_name

    def parse_genus_from_taxon_name(taxon_name: str | None) -> str | None:
        taxon_name = clean_text(taxon_name)
        if not taxon_name:
            return None
        match = re.match(r"([A-Za-z×x-]+)", taxon_name)
        return match.group(1) if match else None

    config = load_config(config_path)
    accession_csv = config["data_sources"]["accession_nomenclature"]
    item_csv = config["data_sources"]["accession_item_history"]
    db_path = config["rag_db_path"]

    rebuild_database(db_path)
    conn = get_db(db_path)
    conn.execute("BEGIN")

    accession_rows = []
    taxa_stats: dict[tuple[str, str, str, str], dict[str, int | str | None]] = {}
    genus_counts: defaultdict[str, int] = defaultdict(int)
    accession_genus_lookup: dict[str, str] = {}
    accession_count = 0

    for accession_count, row in enumerate(iter_csv_rows(accession_csv), start=1):
        accession_number, fmt = derive_accession_number(row)
        if not accession_number or not fmt:
            continue

        genus = clean_text(row.get("Genus"))
        species = clean_text(row.get("Species"))
        infra_text = build_infra_text(row.get("InfraType1"), row.get("InfraName1"))
        taxon_name_full = clean_text(row.get("TaxonNameFull"))
        # Construct TaxonNameFull from TaxonName + SpeciesAuthor if not present
        if not taxon_name_full:
            taxon_name_raw = clean_text(row.get("TaxonName"))
            species_author = clean_text(row.get("SpeciesAuthor"))
            if taxon_name_raw and species_author:
                taxon_name_full = f"{taxon_name_raw} {species_author}"
            elif taxon_name_raw:
                taxon_name_full = taxon_name_raw
        taxon_name = build_short_taxon_name(genus, species, infra_text, taxon_name_full)
        family = clean_text(row.get("Family"))
        accession_year = derive_accession_year(row, accession_number, fmt)
        acc_no_full = normalize_accession(row.get("AccNoFull"))
        if acc_no_full and genus:
            accession_genus_lookup[acc_no_full] = genus
        accession_rows.append(
            (
                accession_number,
                fmt,
                accession_year,
                genus,
                species,
                infra_text,
                taxon_name,
                taxon_name_full,
                family,
                None,
                None,
                None,
                None,
                None,
                row_hash(row),
            )
        )

        if genus:
            genus_counts[genus] += 1
        if genus or taxon_name:
            genus_norm = normalize_taxon_for_compare(genus)
            taxon_norm = normalize_taxon_for_compare(taxon_name or taxon_name_full)
            key = (genus or "", taxon_name or "", taxon_name_full or "", family or "")
            stats = taxa_stats.setdefault(
                key,
                {
                    "genus": genus,
                    "genus_normalized": genus_norm,
                    "taxon_name": taxon_name,
                    "taxon_name_normalized": taxon_norm,
                    "taxon_name_full": taxon_name_full,
                    "family": family,
                    "observation_count": 0,
                    "first_accession_year": accession_year,
                    "last_accession_year": accession_year,
                },
            )
            stats["observation_count"] = int(stats["observation_count"]) + 1
            if accession_year is not None:
                first_year = stats["first_accession_year"]
                last_year = stats["last_accession_year"]
                stats["first_accession_year"] = accession_year if first_year is None else min(int(first_year), accession_year)
                stats["last_accession_year"] = accession_year if last_year is None else max(int(last_year), accession_year)

        if accession_count % PROGRESS_EVERY == 0:
            print(f"Processed {accession_count:,} accession rows...")

    conn.executemany(
        """
        INSERT INTO rag_accessions (
            accession_number, accession_format_type, accession_year, genus, species,
            infra_text, taxon_name, taxon_name_full, family, collector,
            collection_date, country, provenance_code, is_current, source_row_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        accession_rows,
    )

    item_rows = []
    item_count = 0
    for item_count, row in enumerate(iter_csv_rows(item_csv), start=1):
        item_accession_number = normalize_accession(row.get("ItemAccNoFull"))
        if not item_accession_number:
            continue
        # Derive parent from AccNoFull if present, else from ItemAccNoFull prefix
        acc_no_full_hint = row.get("AccNoFull")
        if not acc_no_full_hint and "." in (item_accession_number or ""):
            acc_no_full_hint = item_accession_number.rsplit(".", 1)[0]
        parent_accession_number, item_suffix = extract_parent_and_suffix(item_accession_number, acc_no_full_hint)
        taxon_name = clean_text(row.get("TaxonName"))
        genus = accession_genus_lookup.get(normalize_accession(acc_no_full_hint)) or parse_genus_from_taxon_name(taxon_name)
        item_rows.append(
            (
                item_accession_number,
                parent_accession_number,
                item_suffix,
                genus,
                taxon_name,
                clean_text(row.get("ItemStatus")),
                normalize_date(row.get("ItemStatusDate")),
                clean_text(row.get("ItemLocationCode")),
                clean_text(row.get("ItemLocationName")),
                clean_text(row.get("MaterialType")),
                clean_text(row.get("Propagule")),
                clean_text(row.get("ProjectCode")),
                clean_text(row.get("PropComment")),
                clean_text(row.get("PropContainer")),
                clean_text(row.get("PropDuration")),
                clean_text(row.get("PropEnvironment")),
                clean_text(row.get("PropMedium")),
                clean_text(row.get("PropQuantity")),
                clean_text(row.get("PropTreatment")),
                clean_text(row.get("ProvenanceCode")),
                normalize_date(row.get("RecDate")),
                row_hash(row),
            )
        )
        if item_count % PROGRESS_EVERY == 0:
            print(f"Processed {item_count:,} item rows...")

    conn.executemany(
        """
        INSERT INTO rag_items (
            item_accession_number, parent_accession_number, item_suffix, genus, taxon_name,
            item_status, item_status_date, item_location_code, item_location_name, material_type,
            propagule, project_code, prop_comment, prop_container, prop_duration,
            prop_environment, prop_medium, prop_quantity, prop_treatment, provenance_code,
            rec_date, source_row_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        item_rows,
    )

    taxa_rows = [
        (
            stats["genus"],
            stats["genus_normalized"],
            stats["taxon_name"],
            stats["taxon_name_normalized"],
            stats["taxon_name_full"],
            stats["family"],
            stats["observation_count"],
            stats["first_accession_year"],
            stats["last_accession_year"],
        )
        for stats in taxa_stats.values()
    ]
    conn.executemany(
        """
        INSERT INTO rag_taxa (
            genus, genus_normalized, taxon_name, taxon_name_normalized, taxon_name_full,
            family, observation_count, first_accession_year, last_accession_year
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        taxa_rows,
    )

    genus_rows = []
    for genus in sorted(genus_counts, key=lambda value: value.lower()):
        genus_lower = genus.lower()
        genus_rows.append(
            (
                genus,
                genus_lower[:3] or None,
                genus_lower[:4] or None,
                genus_lower[:5] or None,
                genus_lower,
                genus_counts[genus],
            )
        )
    conn.executemany(
        """
        INSERT INTO rag_filename_genus_index (
            genus, prefix_3, prefix_4, prefix_5, sort_key, accession_count
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        genus_rows,
    )

    conn.commit()

    counts = {
        "rag_accessions": conn.execute("SELECT COUNT(*) FROM rag_accessions").fetchone()[0],
        "rag_items": conn.execute("SELECT COUNT(*) FROM rag_items").fetchone()[0],
        "rag_taxa": conn.execute("SELECT COUNT(*) FROM rag_taxa").fetchone()[0],
        "rag_filename_genus_index": conn.execute("SELECT COUNT(*) FROM rag_filename_genus_index").fetchone()[0],
    }
    conn.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rag.db from accession CSVs")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args()

    counts = build_index(args.config)
    config = load_config(args.config)
    db_path = config["rag_db_path"]
    db_size = os.path.getsize(db_path)
    print("\nRAG index build complete")
    print(f"Database: {db_path}")
    print(f"Size: {db_size / (1024 * 1024):.2f} MiB")
    for table_name, count in counts.items():
        print(f"{table_name}: {count:,}")


if __name__ == "__main__":
    main()
