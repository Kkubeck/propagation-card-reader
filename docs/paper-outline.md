# Paper outline — UBC propagation card digitization

**Status:** working draft, 2026-05-25. Numbers are placeholders pending the qwen2.5vl:7B full-corpus run + possible CHURRO bake-off.

---

## Working title options

1. **"Reading the cards: a local-first vision-language pipeline for fifty years of UBC propagation records"**
2. **"The dawn of local models in the garden: digitizing handwritten propagation cards on consumer hardware"**
3. **"No cloud required: practitioner-scale OCR for botanical garden archives with a 3B open-weight VLM"**
4. **"From shoebox to SQLite: a local-VLM case study in living-collection record digitization"**

Recommend #1 for BGjournal (descriptive), #2 for a Technical Review or blog companion (rhetorical).

## Target venue

**Primary:** BGCI Technical Review (long-form practitioner monograph) *or* BGjournal feature article.
**Companion:** BGCI blog post + preprint on Zenodo or arXiv (cs.DL or cs.CV) for citability.

Rationale: BGCI's own publication series 2017–2024 has covered zero digitization/AI topics. The lane inside their venues is empty; the right framing is "practitioner monograph for fellow garden staff," not "CS benchmark paper."

## One-paragraph abstract (placeholder — fill after final numbers)

> UBC Botanical Garden's propagation card archive contains roughly fifty years of handwritten records — accession numbers, taxonomy, sowing dates, germination notes, propagation methods — across {N} cards in {N} PDF volumes. We describe a fully local digitization pipeline using {qwen2.5vl:7B | CHURRO-3B} on a single consumer Mac (M4, 24 GB) with post-processing for accession-format normalization and a RAG-augmented taxonomy fallback. The pipeline achieved {X}% field-level extraction without manual review, completing the corpus in {Y} hours of unattended runtime. We argue that the era of local vision-language models has arrived for botanical garden archives, and that the institutional cost of cloud OCR — measured not only in dollars but in data sovereignty, vendor lock-in, and model deprecation risk — outweighs the wall-clock cost of patient inference on hardware many gardens already own.

---

## Section structure

### 1. Introduction (~800 words)

- **The hook:** A drawer of index cards in a horticulture office. Half a century of propagation knowledge written by people now retired or deceased. The cards are scanned but unsearchable — they are images, not data.
- **The institutional problem:** Botanic gardens hold immense paper archives (propagation records, accession books, field notebooks, herbarium labels). The digital-transformation conversation has focused on born-digital workflows (IrisBG, BG-BASE) and on herbarium-label OCR for specimen sheets. *Living-collection paper records have been comparatively neglected.*
- **The two cheap defaults that don't fit:** (a) crowdsourced transcription (Notes from Nature et al.) — too slow, too narrow a volunteer base for a single garden's archive; (b) commercial cloud OCR APIs — work technically, but pose institutional questions we'll spend the paper unpacking.
- **The thesis:** A third path is now viable. Open-weight vision-language models running on consumer hardware can do this work overnight, in-house, with no API spend and no data leaving the institution. This paper is a practitioner case study of that third path at UBC Botanical Garden.
- **What you'll get out of this paper:** a replication-ready description of the pipeline, honest accuracy numbers, a cost comparison vs cloud APIs, and an argument about institutional posture that the technical literature is not making.

Citations: Drinkwater/Cubey/Haston 2014 (OCR-in-garden-workflows origin); Turnbull et al. 2025 Hespi (current AI-for-biocollections SOTA); BGCI ITF2 (records-schema target); BGCI Technical Review series (institutional context).

### 2. Background: the cards, the archive, the field (~600 words)

- **2.1 What a UBC propagation card looks like.** One image, annotated. Twenty fields per card: accession number, botanical name, source, propagation method, sowing/germination dates, notes. Handwriting from multiple curators across decades, some pre-printed templates, some freeform.
- **2.2 The archive at a glance.** {N} cards across {N} PDFs (514 in current scope), spanning {date range}. Already scanned (the easy part) but image-only PDFs.
- **2.3 Prior work on AI for botanical collections.** Brief positioning: herbarium-label OCR (Drinkwater 2014, Hespi 2025, LeafMachine2 2023) has matured; living-collection records have not been a focus. Cloud-LLM pipelines for specimen labels exist (Ren et al. 2025 BDJ) but pose the cost/sovereignty issues we'll address.
- **2.4 What's changed in 2024–2025.** Open-weight vision-language models (Qwen-VL family, LLaVA, MiniCPM-V, Molmo) have closed enough of the gap with closed-source frontier models to be practical for archival OCR. CHURRO (Frunza et al. 2025) demonstrated benchmark-level superiority of an open 3B Qwen-2.5-VL fine-tune over Gemini 2.5 Pro on historical OCR at a fraction of the cost. Our work is the practitioner downstream of that demonstration.

Citations: Drinkwater 2014; Turnbull 2025 Hespi; Ren 2025 BDJ; Frunza 2025 CHURRO.

### 3. The pipeline (~1200 words, with diagram)

- **3.1 Hardware.** Mac M4, 24 GB unified memory. Explicitly framed: "the kind of machine many garden directors already have for email." Earlier work on a TUF workstation (6 GB VRAM) is noted as the lower bound.
- **3.2 Software stack.** Ollama + qwen2.5vl:7B (the production run) and/or churro-ocr + CHURRO-3B (the bake-off / final run, TBD). Python orchestration (`auto_batch.sh`, batch scripts). SQLite as the destination — chosen because it's a single file any garden's IT can back up.
- **3.3 Card → JSON: the extraction prompt.** The 20-field schema (point to `extraction-schema.md` and `card-layout-field-mapping.md`). What the model gets (an image at 150 DPI), what it returns (a JSON object).
- **3.4 Post-processing.** Why raw model output isn't enough:
  - Accession-number normalization (multiple historical formats, regex extraction)
  - Botanical-name validation via a local taxonomy backbone (RAG-augmented fallback)
  - Duplicate detection across page/PDF boundaries
  - Confidence-scored flagging of cards needing human review
- **3.5 The DPI/token-budget gotcha we hit.** A page on this — it's the kind of thing a fellow practitioner will recognize and value. Empty model responses at higher DPI, traced to image tokens consuming the text prompt buffer; resolved by tuning DPI down to 175. Generalizable lesson about VLM token economics.
- **3.6 Audit trail and human-in-the-loop review.** Failed-card-samples directory; the audit-report mechanism that classifies failures so review effort is targeted, not blanket.

Figures: (a) pipeline diagram; (b) a sample card and its extracted JSON side-by-side; (c) the audit-report dashboard / a representative slice of it.

### 4. Results (~800 words, placeholder)

- **4.1 Headline numbers (placeholders pending full run).**
  - Cards processed: {N}
  - Field-level extraction rate (no manual review needed): {X}%
  - Cards flagged for human review: {Y}%
  - Mean wall-clock per card: {Z} seconds
  - Total unattended runtime: {H} hours, completed over {D} days
- **4.2 Where the pipeline does well.** Printed-template fields (dates, pre-printed labels). Latin binomials when curator handwriting is legible. Common propagation methods.
- **4.3 Where it struggles.** Pre-1980 handwriting from specific curators; faded ink on yellowed cards; cards with marginal annotations in non-English notes; ambiguous abbreviations.
- **4.4 Optional: CHURRO vs qwen2.5vl:7B head-to-head** on {N} representative cards. If CHURRO wins on the hard cases, we make the stronger claim. If it doesn't, we report honestly and stay with qwen2.5vl:7B.

Tables: (a) accuracy by field; (b) accuracy by decade / curator handwriting era; (c) model-vs-model comparison if bake-off happened.

### 5. The local-first argument (~1000 words — this is the paper's actual contribution)

This is the section a CS benchmark paper would never write. It is what makes this a BGCI piece.

- **5.1 The dollar cost comparison.** Pencil out: {N} cards × cloud OCR cost (Gemini 1.5 Pro Vision, Claude Sonnet, GPT-4o) at our image size and field-extraction prompt. Compare to: electricity cost of running a Mac M4 unattended for {D} days. Show the order-of-magnitude gap, but don't make this the whole argument — it's the easiest argument, not the most important.
- **5.2 The data sovereignty argument.** Propagation records can contain culturally significant taxa, source-attribution to Indigenous gatherers, and information about wild populations that should not be uploaded to a third-party API operated under a different jurisdiction's data laws. The CARE Principles (Carroll 2020; Jennings et al. 2023) apply to ecology and biodiversity research, including living-collection records. *This is not a hypothetical concern at a garden like UBCBG.*
- **5.3 The vendor lock-in / deprecation argument.** Cloud LLMs are deprecated on commercial timelines (Gemini 1.0, GPT-4-vision-preview, Claude 2 — all gone or going within ~18 months of release). A digitization project that takes a year and depends on a model that ships breaking changes mid-project is a liability. Open weights pinned to a checksum are stable indefinitely.
- **5.4 The patience-as-affordance argument.** Kevin's framing, fully developed: archival digitization is a "set it and forget it" workload, not interactive. The wall-clock cost of slow local inference is borne by a machine sitting in a corner overnight, not by staff time. Gardens already own this hardware (the director's-office Mac wasted on email); the marginal cost of "let it run for a week" is essentially zero.
- **5.5 What this looks like at other gardens.** A short replication checklist: what hardware threshold (M2/M3/M4 + ≥16 GB), what software (ollama or churro-ocr), what staff time (~{X} hours for initial setup and review tooling, then unattended).

Citations: Carroll 2020; Jennings 2023; CHURRO; Ren 2025 BDJ (as the cloud foil); BGCI Technical Review series.

### 6. Limitations and honest caveats (~400 words)

- Single-institution sample; UBC card conventions don't represent every garden's archive.
- {X}% manual review rate isn't zero; we describe but don't quantify staff time on the review loop.
- We didn't fine-tune; a CHURRO-style domain fine-tune on propagation cards specifically would likely improve numbers and is a natural follow-up.
- The Qwen Research license on CHURRO is research-leaning; gardens deploying this commercially (e.g., for paid digitization services) need to read the license.
- We make a posture argument, not a security audit; gardens with formal infosec requirements will need to do their own threat modeling.

### 7. Future work and call to action (~300 words)

- A propagation-card fine-tune dataset (CHURRO-style, open) drawn from a consortium of gardens.
- ben0 as a generalizable "garden in a box" deployment of this pipeline for institutions without in-house technical staff.
- Invitation to BGCI member gardens: ship us 50 of your hardest cards, we'll run them and report back; this is how a community-of-practice forms around local-first archival AI.

### 8. Data and code availability

Code: GitHub repo URL. License: TBD (MIT or Apache for code; CC-BY-4.0 for the extracted data; per-card licensing inherited from UBCBG's record-sharing policy).
Trained artifacts: none (off-the-shelf models, no fine-tune yet).
Sample extracted records: a representative subset on Zenodo with DOI.

### 9. Acknowledgments

UBC Botanical Garden curatorial staff; the Stanford-OVAL team for CHURRO; the Qwen team for qwen2.5-vl; Alibaba; (Kevin to add specific people).

---

## Figures and tables (master list)

1. **Fig 1.** A sample propagation card (anonymized if needed) + its extracted JSON, side by side.
2. **Fig 2.** Pipeline diagram (PDF → page render → VLM → JSON → post-process → SQLite → audit).
3. **Fig 3.** Sample of `failed-card-samples/` with brief failure-mode captions.
4. **Fig 4.** Cost comparison: per-card $ on cloud APIs vs amortized electricity on M4.
5. **Fig 5.** Optional — CHURRO vs qwen2.5vl:7B output on the same hard card.
6. **Table 1.** Field-level extraction accuracy.
7. **Table 2.** Accuracy by decade / handwriting era.
8. **Table 3.** Model bake-off results (if performed).

## Open questions (for Kevin)

1. **Venue first choice:** BGCI Technical Review (long, monograph-ish) or BGjournal feature article (~3000–5000 words)?
2. **Co-authors:** who at UBCBG should be on this? Daniel Mosquin? Andy Hill? Curatorial staff who maintained the cards?
3. **Anonymization policy:** any cards we shouldn't show in figures (rare-taxon location data, donor identifying info, Indigenous-source attribution)?
4. **Companion preprint:** Zenodo (data + paper), or arXiv (cs.DL or cs.CV)? Both?
5. **Timing:** target submission window? BGCI Technical Reviews appear ~annually; what's the calendar pressure?

## Next actions

- [ ] Wait for current qwen2.5vl:7B full-corpus run to complete; Kevin shares DB.
- [ ] Smoke-test CHURRO on 5–10 hard cards from `failed-card-samples/`.
- [ ] If smoke test promising: bake-off on ~100–200 representative cards.
- [ ] Decide: stay on qwen2.5vl:7B, or re-run full corpus on CHURRO.
- [ ] Work out cost-comparison methodology (which cloud APIs, what unit pricing, fair multi-pass accounting).
- [ ] First draft of §1, §2, §5 (no numbers needed) — can start anytime.
- [ ] Draft §3, §4 once numbers are in.
