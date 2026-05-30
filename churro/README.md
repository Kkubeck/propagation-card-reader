# churro/ — CHURRO vs qwen2.5vl head-to-head

Sub-module of `propagation-card-reader`. Runs Stanford CHURRO over the
same UBC propagation-card scans the qwen pipeline already processed,
writes the results to a parallel SQLite DB (`churro_cards.db`), and
emits a per-card comparison report so we can quote head-to-head
numbers in the BGCI paper on local-VLM OCR.

This directory is meant to run on Kevin's M4 MacBook Air against the
"DeweyRunner" USB stick. **Nothing here writes outside `churro/`.**

## Prereqs (already done on Kevin's Mac)

- `uv tool install churro-ocr` — CLI on PATH as `churro-ocr`.
- Python 3.10+.

## One extra Python dep

```sh
cd propagation-card-reader/churro
pip install -r requirements.txt   # only adds pymupdf for PDF rasterization
```

## Usage

```sh
# 1. Run CHURRO on the card scans.
python3 run_churro.py \
    --cards-dir /Volumes/DeweyRunner/OCR_test \
    --db churro_cards.db \
    --model stanford-oval/churro-3B \
    --backend hf \
    --dpi 175

# 2. Compare against the qwen cards.db sitting in the repo root.
python3 compare.py \
    --qwen-db ../cards.db \
    --churro-db churro_cards.db \
    --output comparison.md
```

`run_churro.py` is idempotent: re-running skips PDFs already
inventoried and cards already at `status='success'`. Render outputs
land in `<cards-dir>/_pages/<stem>_pNNNN.png`, matching the qwen
pipeline's naming convention so a human can eyeball the same images
both pipelines saw.

## Files

| File | What it does |
|---|---|
| `churro_schema.py` | SQLite schema mirror of relevant `cards.db` tables. |
| `run_churro.py` | Walks `--cards-dir` alphabetically, rasterizes PDFs, shells out to `churro-ocr transcribe`, extracts {accession, botanical_name, propagation_text} from the transcript, writes to `churro_cards.db`. |
| `compare.py` | Joins `cards.db` and `churro_cards.db` on `(pdf_basename, page_num)`; emits `comparison.md` with summary stats + per-card table. |
| `requirements.txt` | `pymupdf` only. |

## Self-tests (no CHURRO required)

```sh
python3 churro_schema.py                    # schema smoke test
CHURRO_SELFTEST=1 python3 run_churro.py     # pure-function tests
COMPARE_SELFTEST=1 python3 compare.py       # pairing + render tests
```

## Design notes

- **Schema mirror, not schema reuse.** `churro_cards.db` has its own
  `churro_processing_runs` / `churro_cards` / `churro_extractions`
  tables — same key columns (`pdf_path`, `page_num`) and same status
  vocabulary as the qwen `cards.db`, but renamed so the two DBs can
  even be attached and joined in the same `sqlite3` session without
  collision.
- **CHURRO returns plain text only** (`transcribe --output file.txt`).
  Structured fields (`botanical_name`, `accession_number`,
  `propagation_text`) are extracted from the transcript via the same
  regex shapes used in `../post_processing.py`. We keep the full
  transcript in `transcript_text` so we can re-extract later without
  re-running CHURRO.
- **Field extraction is intentionally coarse.** The qwen pipeline has
  a 22-field structured prompt; CHURRO does free-form OCR. Comparing
  the three most-audited fields is the apples-to-apples we have.

## What Kevin should sanity-check before a real run

1. The exact `churro-ocr transcribe` invocation in `run_churro.run_churro`
   matches what works on your machine. The flags come from the Stanford
   CLI docs — `--image`, `--backend`, `--model`, `--output` — but if
   the CLI was updated, edit `DEFAULT_CLI` / the subprocess argv list.
2. `stanford-oval/churro-3B` is the right model handle for `--backend hf`.
   The README mentions a 3B baseline; if you want the larger variant
   pass `--model stanford-oval/churro-7B` (or whatever the actual
   handle is — I didn't verify it exists).
3. `--dpi 175` matches what the qwen pipeline found optimal. CHURRO
   may prefer something else; revisit if outputs look truncated.
