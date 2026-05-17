# Propagation Card Layout & Field Mapping

> Source: Kevin Kubeck, May 16 2026. Authoritative reference for OCR field extraction.

## Card Formats

Two eras of cards:
- **Old cards**: Batch-printed with carbon copy triplicate. More fields. Used pre-IrisBG adoption (~2017).
- **New cards**: In-house printed on card stock, single layer. Dropped some fields that became redundant once IrisBG began capturing propagation data digitally.

Field naming and general position have remained consistent across both formats.

---

## Row-by-Row Layout

### Row 1 (both formats)

| Card Field | Position | CSV Reference | Notes |
|---|---|---|---|
| **BOTANICAL NAME** | Top-left, often truncated by scanning | `TaxonName` (both CSVs), may include `SynonymName`, `SpeciesAuthor`, `Genus`, `Species`, `InfraGroup`, `CultivarGroup`, `InfraName1` from taxonomy CSV | Primary identification field |
| **FAMILY NAME** | Top-right | `Family` in taxonomy CSV | Plant family |

### Row 2 (old cards only — removed in new format)

Typically empty field on old cards. Not present on new cards.

### Row 3 (old) / Row 2 (new)

| Card Field | Position | CSV Reference | Notes |
|---|---|---|---|
| **GEOGRACODE (ORIGIN)** | Left | None | Obsolete geographic code, no longer used |
| **REC'D AS** | Left-center | `MaterialTypeCode` or `MaterialType` from taxonomy CSV (95% of cases). Occasionally `Propagule` in item history CSV when established plants were re-propagated differently (e.g., vegetative clone from plant originally received as SEED) | |
| **QUANTITY** | Center | Post-2017: `ItemSpecCount` where `ItemStatus` == "Prop: Culturing" | Seed quantity |
| **DAY / MONTH / YEAR** | Center | `RecDate` in both CSVs | Date material received by the Garden. Should be on or near this date |
| **PRESENT LOCATION** | Center-right | `ItemLocationCode` in item history CSV | "8" = Nursery. Location codes for some garden spots have changed over years — old alpha-numerics may differ from current codes but mean the same thing |
| **WANTED FOR AREA** | Right | `Purpose` in item history CSV | Target garden section for planting |

### Row 4 (old) / Row 3 (new)

| Card Field | Position | CSV Reference | Notes |
|---|---|---|---|
| **SOURCE** | Left (first field in new cards Row 3) | Numeric code. Part of the conserved accession number format: Number-Source-Year. Source info removed from CSVs for privacy | |
| **MISC. SOU. INFO** | Left-center (old only) | Removed from CSVs for privacy | Written form of source. Not on new cards |
| **COLLECTOR NO.** | Center | `OriginRef` in taxonomy CSV or `ProjectCode` in item history CSV | Inconsistent data entry across eras |
| **OTHER NUMBER** | Center-right | No CSV reference | Usually references another institution's accession number or Index Seminum catalogue number |
| **NO. OF LABELS** | Right (old only) | No CSV reference | Number of labels requested. Not on new cards |
| **MAXIMUM QTY REQUIRED** | Right | Post-2017: part of `ItemComment` during "Prop: Culturing" and "Prop: Observed" status updates. No CSV reference pre-2017. Called "Quantity Requested" on new cards | |
| **PARENT ACCESSION** | Right (new cards only) | No direct CSV cross-reference | Replaces "EX" field on old cards. Tracks when propagation material was taken from on-site material. New plants get a new accession number with the parent noted here. Rules for re-accessioning applied unevenly. When used, presents a 'parent' accession number |

### Row 5 (old cards only — not present on new cards)

| Card Field | Position | CSV Reference | Notes |
|---|---|---|---|
| **COLLECTION INFORMATION** | Full width | `ParentageComment`, `TaxonDistributionNote`, `CommonName_en`, `LifeForm`, `OriginRef` from taxonomy CSV. `AtrA_Variant` (attribute: Variants), `AtrT_Flower_color` (attribute: flower color) from item history CSV | Location data of the collection |

### Row 6 (old cards) / Row 2 right side (new cards)

| Card Field | Position | CSV Reference | Notes |
|---|---|---|---|
| **DISTRIBUTION** | Left (old only) | `TaxonDistributionNote` in taxonomy CSV | Often country of origin |
| **ACCESSION NUMBER** | **Primary target of OCR work** | Conserved number (`AccNoCons`) or modern accession (`AccNoFull`) from both CSVs | **Old cards**: this row. **New cards**: right side of Row 2, below FAMILY, above PARENT ACCESSION |

### Row 7+ (old cards) / Row 4+ (new cards) — Propagation Area

**New cards Row 4 header**: "Propagation notes" (left) and "IRIS data entered ..." (right)

#### Left side (¾ card width): **PROPAGATION**

Chronological propagation log, read left-to-right, top-to-bottom. General flow:

1. **Treatment description** — what was done to the material
   - Modern cards: this info populates propagation fields during "Prop: Culturing" status in IrisBG
2. **Treatment start date** (date sown) — first date at top, typically a date stamp
3. **Germination date** — mentions "G.", "Germ.", or "Germinated"
   - Modern cards: `ItemStatusDate` of "Prop: Success" observations
   - Kevin adds "germination date" in `ItemComment` for this status
4. **Prick-out date** — mentions number of seedlings, media, pot type
   - Modern cards/IrisBG: info entered into "Prop: Observed" status (tracks initial pricking out and subsequent transplantings)
5. **Date discarded** (if failed to germinate) — when no germination date exists; some variation of "discarded" or "dead"

#### Right side (¼ card width): **CURATOR'S INFORMATION**

| Card Field | CSV Reference | Notes |
|---|---|---|
| **CURATOR'S INFORMATION** (old) / untitled blank field (new) | `ParentageComment`, `TaxonDistributionNote`, `CommonName_en`, `LifeForm`, `OriginRef` from taxonomy CSV. `AtrA_Variant`, `AtrT_Flower_color` from item history. `PropComment` in item history (modern usage for dormancy types, other references) | Kevin uses this area on modern cards for dormancy types and references |

---

## Card Content Patterns

Three distinct patterns appear across the collection. The OCR pipeline must handle all three.

### Pattern 1: Standard Seed Card (most common)

Linear propagation narrative in the PROPAGATION field, read top-to-bottom:

```
[Treatment description]
[Date sown — typically a date stamp]
[Germination note — "G.", "Germ.", "Germinated" + date]
[Prick-out note — count, media, pot type, date]
[Outcome — success/transplant OR "DEAD"/"discarded" + date]
```

Typically **one accession number per card**. The card tracks a single seed lot from receipt through to garden planting or failure.

### Pattern 2: Condensed Multi-Sowing Table

When the same taxon is re-sown from different seed lots over multiple years, propagators condensed the data into a **hand-drawn table** in the propagation area. Common column headings:

| Column | Meaning |
|---|---|
| **OTHER** | The other accession number (each row = different seed lot) |
| **# OF SEED** | Number of seeds sown |
| **SOWN** | Date sown |
| *(location, often no heading)* | Where sown (e.g., PSH = Poly Shadehouse) |
| **GERM** | Germination date |
| **QTY** | Quantity germinated |
| **TREATMENT** | Treatment type (not always present) |

**Critical for OCR**: These cards contain **multiple accession numbers** — the primary one in the ACCESSION NUMBER field, plus one per table row. A single card can span 10+ years and 5+ accessions. The model must recognize the tabular structure and extract all accession numbers, not just the header one.

### Pattern 3: Vegetative Propagation (URCU) Card

Similar overall layout but different milestones and more detailed methodology:

- **REC'D AS**: URCU (unrooted cuttings), or occasionally divisions, bulbs, etc.
- **Methodology section**: Often detailed — sanitation soak, hormone treatment, rooting medium ratios, environment (poly tent, mist bench, etc.)
- **Tracking table** instead of narrative:
  - **DATE ROOTED** | **QUANTITY** (often with success percentage)
- **Accession number** may be blank on cultivar cards (clonal material inherits parent accession)
- Key milestone is **rooting**, not germination

### Other Material Types

The bulk of observations are SEED and URCU, but some cards cover plants received as:
- Plants (PLNT)
- Bulbs (BULB)
- Corms (CORM)
- Divisions (DIVI)

These are "outside propagated material" — they went through propagation at their source, not at the Garden's nursery. Cards are retained because the OCR may still need the accession/taxonomy information.

### Duplex (Back-of-Card) Content

Some cards have content on the reverse side (the duplex PDFs, currently excluded from processing). The back side may contain:
- **Continuation of the same accession** — more propagation actions that didn't fit on the front
- **A completely different accession** of the same taxon — essentially a second card sharing the physical card stock

Duplex processing is a future phase.

---

## Key OCR Targets (Priority Order)

1. **ACCESSION NUMBER** — primary goal of the project
2. **BOTANICAL NAME** — validation against taxonomy CSV
3. **PROPAGATION** field — full text extraction of propagation history
4. **FAMILY NAME** — additional validation
5. **REC'D AS** / **DAY/MONTH/YEAR** / **SOURCE** — supporting context

## Format-Era Differences Summary

| Feature | Old Cards | New Cards |
|---|---|---|
| Row 2 (empty) | Present | Removed |
| MISC. SOU. INFO | Present | Removed |
| NO. OF LABELS | Present | Removed |
| COLLECTION INFORMATION (full row) | Present | Removed |
| DISTRIBUTION | Present | Removed |
| CURATOR'S INFORMATION header | Present | Untitled blank field |
| EX field | Present | Replaced by PARENT ACCESSION |
| ACCESSION NUMBER position | Row 6 | Row 2 right side |
| IRIS data entered header | Not present | Row 4 right header |
| Carbon copy triplicate | Yes | No (single card stock) |
