"""Prompt templates for baseline and RAG-guided OCR."""

BASELINE_PROMPT = """Read this scanned botanical garden propagation card. Extract as JSON:
{"accession_number": ["..."], "botanical_name": "...", "propagation_text": "full text as written"}
If multiple accession numbers exist, list all. Read numbers precisely."""

RAG_PROMPT_TEMPLATE = """You are reading a scanned botanical garden propagation card.

Your job is transcription first, not invention.
Use the provided garden context only to guide recognition and validation.
Do not hallucinate accession numbers that are not visible.
If the card has no accession number, return an empty list.
A bare number like "1" or "3" is not a valid accession unless it is clearly part of a full accession format.

Return JSON only using this schema:
{{
  "accession_number": ["..."],
  "botanical_name": "...",
  "propagation_text": "full text as written",
  "notes": "optional brief note about uncertainty"
}}

{context_block}

Instructions:
- Read what is on the card.
- If the visible accession differs from the examples, transcribe what is visible.
- If botanical spelling is unclear, prefer the closest visible spelling rather than guessing.
- Keep propagation_text as a faithful transcription."""


def build_prompt(context_text: str | None = None, mode: str = "rag_prompt") -> str:
    """Build the OCR prompt for the requested pipeline mode."""
    if mode == "ocr_only":
        return BASELINE_PROMPT
    if mode != "rag_prompt":
        raise ValueError(f"Unsupported prompt mode: {mode}")

    cleaned_context = (context_text or "").strip()
    context_block = cleaned_context or "Garden accession rules:\n- No garden-specific retrieval context available."
    return RAG_PROMPT_TEMPLATE.format(context_block=context_block)
