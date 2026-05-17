"""Prompt templates for baseline and RAG-guided OCR."""

BASELINE_PROMPT = """Read this scanned botanical garden propagation card. Extract as JSON:
{"accession_number": ["..."], "botanical_name": "...", "propagation_text": "full text as written"}
If multiple accession numbers exist, list all. Read numbers precisely."""

RAG_PROMPT_TEMPLATE = """Read this scanned botanical garden propagation card. Transcribe each field visible on the card.

Accession number formats: NNNNN-NNN-NN (legacy) or YYYY-NNNNN (modern).
Some cards have hand-drawn tables with multiple accession numbers — list ALL of them.
If a field is not visible or not on this card style, use null.

Return JSON only:
{{
  "botanical_name": "top-left, genus species author",
  "family": "top-right, family name",
  "geocode": "geographic origin code",
  "received_as": "material type: SEED, URCU, PLNT, etc.",
  "quantity": "seed or material count",
  "date_received": "date as written on card",
  "present_location": "location code",
  "wanted_for_area": "target garden section",
  "source": "numeric source code",
  "source_info": "written source description",
  "collector_number": "collector or collection number",
  "other_number": "external accession or catalogue number",
  "labels_requested": "number of labels",
  "max_quantity": "maximum quantity or quantity requested",
  "parent_accession": "parent or EX. accession number",
  "collection_info": "collection location or habitat notes",
  "distribution": "country or region of origin",
  "accession_number": ["all visible accession numbers"],
  "propagation_text": "full propagation area text, line by line",
  "curators_info": "text from right side notes area",
  "iris_data_entered": true/false/null
}}

Transcribe exactly what you see. Do not invent numbers or names.

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
