# Propagation Card Reader

A Python tool for extracting structured data from digitized handwritten propagation cards using local vision-language models. Built for botanical gardens with paper archives and zero budget.

[![View Project Website](https://img.shields.io/badge/View%20Website-Live-blue)](https://kkubeck.github.io/propagation-card-reader/)

---

## Why local-first?

The pipeline runs entirely on consumer hardware (a Mac with Ollama serving `qwen2.5vl:7b`). No data leaves the machine;  not the card images, nor the transcribed text, nor the metadata. Privacy isn't a procedural promise, it's a property of where the computation happens. 

It's also free to run, save for a potentially long 'slog' on a single laptop and costs the electricity to keep it awake.

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

## Drive Map

```
propagation-card-reader/
├── run.py                    # CLI entrypoint (inventory | process | status | export | failures)
├── config.yaml               # Garden config, RAG budgets, accession formats
├── environment.yml           # Conda env
│
├── docs/                     # Project documentation & paper drafts
│   ├── paper-outline.md
│   ├── paper-structural-notes-s1-s5.md
│   ├── card-layout-field-mapping.md
│   ├── extraction-schema.md
│   └── backbone-mapping-*.md
│
├── data/                     # Sample PDFs, taxonomy CSVs, audit reports
│   ├── accession_card_taxonomy.csv
│   ├── item_history_nursery.csv
│   ├── samples/
│   └── failed-card-samples/
│
├── images/                   # Per-page PNGs produced by inventory step
├── templates/                # Legacy field-coordinate templates (v1/v2)
├── reports/                  # Extraction reports
│
├── cards.db                  # Working extraction DB (SQLite)
├── rag.db                    # Taxonomy RAG index
│
├── inventory.py              # PDF scan → card rows
├── pdf_processing.py         # PDF page → PNG
│
├── worker.py                 # v2 OCR worker (baseline prompt)
├── rag_worker.py             # v3 RAG-guided VLM worker
├── rag_config.py             # YAML config loader
├── rag_context_builder.py    # Genus/range-scoped context retrieval
├── rag_index_builder.py      # Build rag.db from accession exports
├── rag_prompt.py             # Prompt templates (22-field extraction)
├── rag_schema.py             # rag.db schema
│
├── schema.py                 # cards.db schema
├── schema_migrations.py      # Idempotent migrations
│
├── post_processing.py        # Accession number parse/validate + PII field tagging
├── privacy_redaction.py      # v4 — regex-based PII detector
├── scrub_existing_db.py      # v4 — retroactive redaction CLI
│
├── filename_parser.py        # Scan-date / scope / duplex from PDF filename
├── lexicon_correction.py     # Domain fuzzy correction for OCR near-misses
├── db_viewer.py              # Streamlit DB browser
│
├── main.py                   # v1 reference script (template-matching pipeline)
├── image_processing.py       # v1 alignment via OpenCV template match
├── ocr_processing.py         # v1 Google Cloud Vision OCR
└── template.json             # v1 field coordinate config
```

---

## Pipeline (v3)

```
   PDF cards
      │
      ▼
┌─────────────┐
│  inventory  │  pdf_processing.py + filename_parser.py
│             │  → cards table (one row per card, status=pending)
└─────────────┘
      │
      ▼
┌─────────────┐
│ rag_worker  │  rag_context_builder.py → rag.db (taxonomy hints)
│             │  + rag_prompt.py  (22-field schema)
│             │  → qwen2.5vl:7b via Ollama (LOCAL — no network egress)
│             │  → extractions table
└─────────────┘
      │
      ▼
┌─────────────┐
│ post-process│  post_processing.py
│             │  (accession parsing, field validation)
└─────────────┘
      │
      ├──► export (CSV) ──► IrisBG / Quarto / paper
      │
      └──► optional ▼
            ┌─────────────┐
            │  scrub      │  scrub_existing_db.py + privacy_redaction.py
            │  (v4)       │  → *_raw shadow cols + redactions audit table
            └─────────────┘
```

---

## Module Map

**Pipeline orchestration**
- `run.py` — CLI for inventory / process / status / export / failures
- `inventory.py` — idempotent PDF → card-row scanner
- `worker.py` — v2 OCR worker (legacy)
- `rag_worker.py` — v3 RAG-aware VLM worker

**VLM / RAG extraction (v3)**
- `rag_config.py` — YAML config loader
- `rag_context_builder.py` — retrieves genus/range-scoped taxonomy hints
- `rag_index_builder.py` — builds `rag.db` from accession CSVs
- `rag_prompt.py` — 22-field prompt templates
- `rag_schema.py` — `rag.db` schema

**Schema & database**
- `schema.py` — `cards.db` schema (cards, extractions, processing_runs, redactions)
- `schema_migrations.py` — idempotent migrations

**Post-processing & privacy**
- `post_processing.py` — accession parse, field validation, PII tagging
- `privacy_redaction.py` — v4 conservative regex PII detector
- `scrub_existing_db.py` — v4 retroactive redaction with audit trail

**Image / OCR (v1/v2, kept for reference)**
- `pdf_processing.py` — PyMuPDF page → PNG
- `image_processing.py` — OpenCV template-match alignment
- `ocr_processing.py` — Google Cloud Vision wrapper

**Utilities & inspection**
- `filename_parser.py` — metadata from filename
- `lexicon_correction.py` — domain fuzzy correction
- `db_viewer.py` — Streamlit browser for extractions + redactions
- `main.py` — v1 reference script

---

## Version History

### v1 — Train-your-own OCR (~2018, pre-git)
- First attempt: hand-sample card images, label them, train a custom OCR model on the result
- Idea was a model that genuinely understood propagation card handwriting and the field layout
- **Failure mode:** the sample size needed to train a usable model from scratch was orders of magnitude beyond what one person at a public garden could practically produce. The project never reached a working prototype.
- Not in git history — predates Kevin's use of version control (started 2022)

### v2 — Cloud vision + field blocking (2025)
- Pivot: stop trying to train a new model; use existing vision models (Google Cloud Vision)
- Per-card cost made naive whole-card OCR uneconomic, so the pipeline added a **blocking system** — locate each field on the card via OpenCV template matching, then OCR each field region individually to keep token use down
- Multi-anchor alignment → per-field coordinate cropping (`image_processing.py`, `template.json`) → Google Cloud Vision OCR per region (`ocr_processing.py`)
- Worked moderately well: ~90–98% on accession and botanical name
- **Failure modes:**
  - **Cost:** every card still hit a paid cloud API, multiple calls per card
  - **Privacy:** card contents leave the institution for transcription
  - **Brittleness:** card layouts changed over decades; the blocking system needed more and more templates to keep up — diminishing returns

### v3 — Local VLM with RAG (late 2025 / early 2026)
- **Took it local.** Ollama + `qwen2.5vl` (3B baseline, 7B for production runs) — no more cloud OCR, no per-card cost, no data leaving the machine
- The blocking system is **gone**. Modern vision-language models read the whole card in one pass — they understand the layout instead of needing it pre-segmented
- Single-shot full-card extraction → structured 22-field JSON (`rag_prompt.py`)
- **RAG layer for context:** taxonomy hints injected per card based on detected genus / collector range (`rag_context_builder.py`, `rag.db`). Helps the model disambiguate handwritten species names against what UBC actually has in its accession history.
- JSON repair for model output drift
- Zero-padded legacy accession format support
- Synonym-aware taxonomy
- DPI-aware extraction (175 DPI is the sweet spot — higher hits the model's combined text+image token budget and triggers empty responses)
- Streamlit `db_viewer.py` for inspection and DB comparison

### v4 — Privacy redaction capability (May 2026)
- **`privacy_redaction.py`** — conservative regex detector for titled personal names, emails, NA/intl phone, street addresses, Canadian postal codes
- **`scrub_existing_db.py`** — retroactive scrubber over the extractions table; writes redacted text to canonical column, preserves original in `*_raw` shadow column, logs every match to a `redactions` audit table
- **Idempotent and reversible** — re-running with tuned regex only touches unprocessed rows; raw text always recoverable
- **Deliberately not wired into the forward pipeline** — extraction stays fast and verbatim. Redaction is opt-in, post-hoc.
- Designed around real false-positive traps: botanical authorities ("Douglas", "L.", "Hook.") only match with explicit title prefix; legacy accession codes don't trigger phone regex (negative lookbehinds); "+200 seeds" isn't an international phone number (requires 7+ digits after country code).
- **Purpose:** capability demonstration for institutional stakeholders, and downstream-sharing safety (publishing extracts, handing the DB to another garden). Not a privacy requirement of extraction itself — that's already covered by local-first.

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

PII-prone fields (`source_info`, `curators_info`, `collection_info`, `propagation_text`) get `*_raw` shadow columns once the scrubber runs.

---

## Further Reading

- `docs/paper-outline.md` — BGCI Technical Review draft outline
- `docs/paper-structural-notes-s1-s5.md` — section scaffolding (§1 intro, §5 local-first argument)
- `ACCESSION-FORMATS.md` — legacy vs. modern accession number formats
- `SPEC-RAG-PIPELINE.md` — RAG taxonomy design

---

## License

See `LICENSE`.
