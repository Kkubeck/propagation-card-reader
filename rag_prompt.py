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

If a "Valid botanical names" list is provided in the context below, prefer matching names from that list over your own OCR interpretation. Many cards contain handwritten names that may be misspelled — use the closest match from the list.

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


# --- Back-side prompt (duplex pairing) ---------------------------------------
#
# A FrontContext is the subset of front-side extraction we pass as RAG context
# when OCRing the back. Shape:
#   { "botanical_name": str | None,
#     "accession_number": str | None,
#     "family": str | None,
#     "propagation_tail": str }    # last ~200 chars of front propagation_text
#
# The back prompt asks the model to classify each card into one of three modes
# and transcribe accordingly. The mode enum is strict — we post-validate.

BACK_PROMPT_TEMPLATE = """You are reading the BACK SIDE of a scanned botanical garden propagation card. The FRONT side has already been transcribed; key context from the front is provided below.

Backs of these cards typically appear in one of three modes. Detect which mode this card is in and transcribe accordingly:

  1. TABLE_CONTINUATION — A handwritten table with the same columns as the front (Other | Qty | Sown | Treatments | Germ | Qty). Column headers may or may not be re-drawn on the back. Transcribe row by row.

  2. NARRATIVE_NOTES — Free-text handwritten paragraph(s) describing propagation methods, observations, or outcomes. Transcribe verbatim.

  3. BLANK — The back has no meaningful content (a few stray marks, faint bleed-through from the front, or a fully empty card). Set mode to "blank" and leave content fields empty.

IMPORTANT:
- The back will usually NOT have an accession number. Do not invent one from the front-side context.
- If you see faint mirrored writing, that is bleed-through from the front — ignore it.
- The "Other" column on continuation tables sometimes contains a separate accession number for related material. Capture any such numbers in all_accession_numbers, but do NOT promote them to a primary accession number.

ACCESSION NUMBER FORMATS:
- Legacy: NNNNN-NNN-NN (e.g. 31748-167-94)
- Modern: YYYY-NNNNN (e.g. 2015-00634)
Handwritten numbers sometimes have trailing zeros dropped or spacing collapsed. Capture what is written; do not pad or invent digits.

Return ONLY valid JSON. The "mode" value must be exactly one of: "table_continuation", "narrative_notes", "blank".

{{
  "mode": "table_continuation",
  "propagation_text": "string — full transcription, empty string if blank",
  "all_accession_numbers": ["array of any accession-format strings visible"],
  "curators_info": "string or null — right-side notes if present",
  "notes": "string or null — anything that doesn't fit the above"
}}

FRONT-SIDE CONTEXT (for reference only, do not copy):
{front_context}"""


VALID_BACK_MODES = ("table_continuation", "narrative_notes", "blank")


def format_front_context(front: dict) -> str:
    """Render a FrontContext dict into the text block injected into the back prompt.

    Keeps it short to anchor the back without polluting the transcription.
    """
    bn = front.get("botanical_name") or "(unknown)"
    fam = front.get("family") or "(unknown)"
    acc = front.get("accession_number") or "(none recorded on front)"
    tail = (front.get("propagation_tail") or "").strip()
    if len(tail) > 200:
        tail = tail[-200:]
    tail_line = f"Last lines of front propagation log: {tail}" if tail else "Front propagation log: (empty)"
    return (
        f"Botanical name: {bn}\n"
        f"Family: {fam}\n"
        f"Accession number (front): {acc}\n"
        f"{tail_line}"
    )


def build_back_prompt(front: dict | None = None) -> str:
    """Build the OCR prompt for a duplex back-side card.

    `front` is a FrontContext dict; pass None to render an empty context block
    (useful for ad-hoc back-only experiments).
    """
    context = format_front_context(front) if front else "(no front context provided)"
    return BACK_PROMPT_TEMPLATE.format(front_context=context)
