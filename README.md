# Propagation Card Reader

A Python tool for extracting structured data from digitized handwritten propagation cards using local vision-language models. Built for botanical gardens with paper archives and zero budget.

**Full archive processed:** 12,700+ cards spanning 50 years of institutional propagation records, transcribed entirely on a single laptop with no cloud services.

[![View Project Website](https://img.shields.io/badge/View%20Website-Live-blue)](https://kkubeck.github.io/propagation-card-reader/)

**For the full story, methodology, and accessible explanations of the technology, visit the [project website](https://kkubeck.github.io/propagation-card-reader/).**

---

## Why local-first?

The pipeline runs entirely on consumer hardware (a Mac with Ollama serving `qwen2.5vl:7b`). No data leaves the machine: not the card images, nor the transcribed text, nor the metadata. Privacy isn't a procedural promise, it's a property of where the computation happens.

It's also free to run, save for a potentially long slog on a single laptop and the electricity to keep it awake.

---

## Quick Start

```sh
# 1. Clone
git clone https://github.com/Kkubeck/propagation-card-reader.git
cd propagation-card-reader

# 2. Conda env (Mac/Linux)
conda env create -f environment.yml
conda activate prop-card-reader

# 3. Start Ollama somewhere reachable and pull the vision model
ollama pull qwen2.5vl:7b

# 4. Build the RAG taxonomy index (one-time, from your accession CSV exports)
python rag_index_builder.py

# 5. Inventory PDFs, then process
python run.py inventory --pdf-dir path/to/cards
python run.py process --mode rag --dpi 175

# 6. Inspect / export
python db_viewer.py            # Streamlit UI
python run.py export -o out.csv
```

---

## Pipeline (v3)

```
   PDF cards
      |
      v
+--------------+
|  inventory   |  pdf_processing.py + filename_parser.py
|              |  -> cards table (one row per card, status=pending)
+--------------+
      |
      v
+--------------+
| rag_worker   |  rag_context_builder.py -> rag.db (taxonomy hints)
|              |  + rag_prompt.py  (22-field schema)
|              |  -> qwen2.5vl:7b via Ollama (LOCAL, no network egress)
|              |  -> extractions table
+--------------+
      |
      v
+--------------+
| post-process |  post_processing.py
|              |  (accession parsing, field validation)
+--------------+
      |
      +---> export (CSV) ---> IrisBG / Quarto / paper
      |
      +---> optional:
            +--------------+
            |  scrub       |  scrub_existing_db.py + privacy_redaction.py
            |  (v4)        |  -> *_raw shadow cols + redactions audit table
            +--------------+
```

---

## Drive Map

```
propagation-card-reader/
├── run.py                    # CLI entrypoint (inventory | process | status | export | failures)
├── config.yaml               # Garden config, RAG budgets, accession formats
├── environment.yml           # Conda env
|
├── docs/                     # Rendered website (GitHub Pages)
├── data/                     # Taxonomy CSVs, audit reports, samples
├── images/                   # Per-page PNGs produced by inventory step
├── templates/                # Legacy field-coordinate templates (v1/v2)
├── reports/                  # Extraction reports
|
├── cards.db                  # Working extraction DB (SQLite)
├── rag.db                    # Taxonomy RAG index
|
|-- Pipeline orchestration --|
├── inventory.py              # PDF scan -> card-row scanner
├── rag_worker.py             # v3 RAG-aware VLM worker
├── worker.py                 # v2 OCR worker (legacy)
|
|-- VLM / RAG extraction ----|
├── rag_config.py             # YAML config loader
├── rag_context_builder.py    # Genus/range-scoped taxonomy hints
├── rag_index_builder.py      # Builds rag.db from accession CSVs
├── rag_prompt.py             # 22-field prompt templates
├── rag_schema.py             # rag.db schema
|
|-- Schema & database --------|
├── schema.py                 # cards.db schema
├── schema_migrations.py      # Idempotent migrations
|
|-- Post-processing ----------|
├── post_processing.py        # Accession parse, field validation, PII tagging
├── privacy_redaction.py      # v4 regex-based PII detector
├── scrub_existing_db.py      # v4 retroactive redaction CLI
|
|-- Image / OCR (v1/v2) ------|
├── pdf_processing.py         # PyMuPDF page -> PNG
├── image_processing.py       # OpenCV template-match alignment
├── ocr_processing.py         # Google Cloud Vision wrapper
├── main.py                   # v1 reference script
├── template.json             # v1 field coordinate config
|
|-- Utilities ----------------|
├── filename_parser.py        # Metadata from filename
├── lexicon_correction.py     # Domain fuzzy correction
└── db_viewer.py              # Streamlit browser
```

---

## Version History

For the full narrative behind each version, see [The Journey](https://kkubeck.github.io/propagation-card-reader/the-journey.html) on the project website.

| Version | Era | Approach | Status |
|---|---|---|---|
| **v1** | Pre-git | Custom training pipeline (scikit-learn, PyTorch) | Abandoned: variation across 50 years of handwriting exceeded feasible training data |
| **v2** | Sep-Oct 2025 | OpenCV alignment + Google Cloud Vision API | Abandoned: 90-98% accuracy but cloud cost, data sovereignty, and layout brittleness |
| **v3** | May 2026 | Local VLM (Gemma 3, then Qwen 2.5-VL 7B) via Ollama | **Complete**: 12,700+ cards processed on a MacBook, no internet required |
| **v4** | May 2026 | Privacy redaction layer (opt-in, post-hoc) | Active: conservative PII detection with audit trail |

---

## Output Schema

22 fields per card. See `docs/extraction-schema.md` and `docs/card-layout-field-mapping.md` for the full mapping. Highlights:

- `accession_number` (primary) + `all_accession_numbers` (pipe-separated)
- `botanical_name`, `common_name`, `family`
- `received_as`, `quantity`, `date_received`
- `source`, `source_info`, `collector_number`, `other_number`
- `present_location`, `wanted_for_area`
- `propagation_text` (large free-text block)
- `curators_info`, `collection_info`

PII-prone fields get `*_raw` shadow columns once the optional scrubber runs.

---

## Further Reading

- [Project website](https://kkubeck.github.io/propagation-card-reader/) for the full story, concepts, and results
- `ACCESSION-FORMATS.md` for legacy vs. modern accession number formats
- `SPEC-RAG-PIPELINE.md` for RAG taxonomy design

---

## License

See `LICENSE`.
