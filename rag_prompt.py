"""Prompt templates for baseline and RAG-guided OCR."""

BASELINE_PROMPT = """Read this scanned botanical garden propagation card. Extract as JSON:
{"accession_number": ["..."], "botanical_name": "...", "propagation_text": "full text as written"}
If multiple accession numbers exist, list all. Read numbers precisely."""

# NOTE: With 22 fields the model response will be longer.
# Ollama num_predict should be >= 2048 (set in worker.py).

RAG_PROMPT_TEMPLATE = """You are reading a scanned botanical garden propagation card. Two card formats exist:
- OLD cards: batch-printed carbon copy triplicates with more fields (pre-~2017).
- NEW cards: in-house printed on card stock, fewer fields, single layer.

Extract every field visible on the card into the JSON schema below. If a field is not visible or does not exist on this card format, use null. Transcribe exactly what is written — do not invent or correct values.

FIELD GUIDE:
- botanical_name: Top-left of card. Genus, species, and sometimes author or infraspecific ranks.
- family: Top-right. The plant family name.
- geocode: Old cards only. A short geographic origin code near the left side, row 3. Obsolete.
- received_as: Material type code — SEED, URCU (unrooted cuttings), PLNT, BULB, CORM, DIVI, etc.
- quantity: Number of seeds or material units received.
- date_received: Date material was received. Old cards: D/M/Y. New cards: Y/M/D. Transcribe as written.
- present_location: Location code (e.g. "8" = nursery). Old cards only.
- wanted_for_area: Target garden section where the plant is destined.
- source: Numeric source code (part of the conserved accession number format: Number-Source-Year).
- source_info: Written description of the source. Old cards only.
- collector_number: Collector or collection reference number.
- other_number: External institution accession or Index Seminum catalogue number.
- labels_requested: Number of labels requested. Old cards only.
- max_quantity: Maximum quantity or "Quantity Requested" on new cards.
- parent_accession: Source accession for re-propagated material. Old cards label this "EX." (right side). New cards have a dedicated "Parent accession" field.
- collection_info: Full-width row of collection location, habitat, or miscellaneous notes. Old cards only.
- distribution: Country or region of origin. Old cards only.
- accession_number: The PRIMARY accession number from the bordered, labeled ACCESSION NUMBER field. This is the card's identity. Old cards: row 6. New cards: right side, row 2. Formats: NNNNN-NNN-NN (legacy) or YYYY-NNNNN (modern). Return as a single string, or null if not visible.
- all_accession_numbers: ALL accession numbers visible anywhere on the card — the primary one plus any from hand-drawn multi-sowing tables, "OTHER" columns, or re-sowing references. Return as an array of strings.
- propagation_text: Full transcription of the propagation area (left ¾ of the lower card). Chronological log: treatment, sowing date, germination, prick-out, outcome. For tabular cards, transcribe the table contents row by row.
- curators_info: Text from the right ¼ notes area (labeled "CURATOR'S INFORMATION" on old cards, unlabeled on new). Kevin uses this for dormancy notes on modern cards.
- iris_data_entered: New cards only — checkbox "IRIS data entered". true/false/null.

Accession number formats: NNNNN-NNN-NN (legacy) or YYYY-NNNNN (modern).
Some cards have hand-drawn tables with multiple accession numbers — capture ALL of them in all_accession_numbers.

Return ONLY valid JSON:
{{
  "botanical_name": "string or null",
  "family": "string or null",
  "geocode": "string or null",
  "received_as": "string or null",
  "quantity": "string or null",
  "date_received": "string or null",
  "present_location": "string or null",
  "wanted_for_area": "string or null",
  "source": "string or null",
  "source_info": "string or null",
  "collector_number": "string or null",
  "other_number": "string or null",
  "labels_requested": "string or null",
  "max_quantity": "string or null",
  "parent_accession": "string or null",
  "collection_info": "string or null",
  "distribution": "string or null",
  "accession_number": "string or null",
  "all_accession_numbers": ["string array"],
  "propagation_text": "string",
  "curators_info": "string or null",
  "iris_data_entered": true/false/null
}}

{context_block}"""


def build_prompt(context_text: str | None = None, mode: str = "rag_prompt") -> str:
    """Build the OCR prompt for the requested pipeline mode."""
    if mode == "ocr_only":
        return BASELINE_PROMPT
    if mode != "rag_prompt":
        raise ValueError(f"Unsupported prompt mode: {mode}")

    cleaned_context = (context_text or "").strip()
    context_block = cleaned_context or ""
    return RAG_PROMPT_TEMPLATE.format(context_block=context_block)
