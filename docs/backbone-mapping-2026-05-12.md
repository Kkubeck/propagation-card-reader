# Backbone Mapping for New IrisBG Exports

_Date: 2026-05-12_

This document maps the new backbone CSV exports onto the current RAG schema and notes the practical changes needed to keep the propagation card reader aligned with the new data sources.

## 1. Column-to-Column Mapping Tables

### A. `2026-05-11_all-accession_nomentature.csv` → `rag_accessions` / `rag_taxa`

| New CSV column | Target RAG column(s) | Notes / transformation |
|---|---|---|
| `AccNoFull` | `rag_accessions.accession_number` | Primary accession identifier. Also best join key to item history. |
| `AccNoCons` | `rag_accessions.accession_format_type` or retained as source-only field if needed | Current schema does not have a dedicated `AccNoCons` field. If accession parsing logic already infers format parts from accession number, keep `AccNoCons` as source context only. |
| `TaxonNameFull` | `rag_accessions.taxon_name_full`; `rag_taxa.taxon_name_full` | Full taxonomic string as exported. |
| `Family` | `rag_accessions.family`; `rag_taxa.family` | Direct map. |
| `Genus` | `rag_accessions.genus`; `rag_taxa.genus` | Direct map. Also used for filename genus index. |
| `Species` | `rag_accessions.species` | Direct map. |
| `InfraType1` | contributes to `rag_accessions.infra_text` | Combine with `InfraName1` into a single infraspecific text field if present. |
| `InfraName1` | contributes to `rag_accessions.infra_text` | Combine with `InfraType1`; blank if missing. |
| `Cultivar` | not currently represented | New field. Should be added if cultivar-level matching matters. At minimum, append into `taxon_name_full` normalization logic or store in a new column. |

**Derived / inferred for `rag_accessions`:**

| Target RAG column | Source / derivation | Notes |
|---|---|---|
| `accession_year` | derive from `AccNoFull` | Existing builder already derives this from accession number. |
| `taxon_name` | derive from `Genus` + `Species` + infra text, or normalize from `TaxonNameFull` | Prefer normalized short name without authorship. |
| `collector` | `NULL` | No longer present in nomenclature file. |
| `collection_date` | `NULL` | No longer present. |
| `country` | `NULL` | No longer present. |
| `provenance_code` | `NULL` from nomenclature file | Could be backfilled from item history if needed. |
| `is_current` | derive from item history `Current` marker | Not present in nomenclature export. |
| `source_row_hash` | computed | No change. |

### B. `2026-05-11_all_item_history_edited.csv` → `rag_items`

| New CSV column | Target RAG column(s) | Notes / transformation |
|---|---|---|
| `Current` | contributes to `rag_accessions.is_current` and/or item current flag | `>>>` appears to mark current rows. Can be used to derive current accession/item status. |
| `AccNoCons` | source-only / optional helper | Useful for debugging, but no current schema field. |
| `AccNoFull` | `rag_items.parent_accession_number` | Also join key back to nomenclature file. |
| `ItemAccNoFull` | `rag_items.item_accession_number` | Primary item identifier. |
| `ItemLocationCode` | proposed `rag_items.item_location_code` | New useful context field. |
| `ItemLocationName` | proposed `rag_items.item_location_name` | New useful context field. |
| `ItemStatus` | `rag_items.item_status` | Direct map. |
| `ItemStatusDate` | proposed `rag_items.item_status_date` | Useful for dating changes. |
| `MaterialType` | proposed `rag_items.material_type` | Replaces or supplements old `ItemType`; not identical, so map explicitly. |
| `Propagule` | `rag_items.propagule` | Direct map. |
| `ProjectCode` | proposed `rag_items.project_code` | New contextual field. |
| `PropComment` | `rag_items.prop_comment` | Direct map. |
| `PropContainer` | proposed `rag_items.prop_container` | New propagation backbone field. |
| `PropDuration` | proposed `rag_items.prop_duration` | New propagation backbone field. |
| `PropEnvironment` | proposed `rag_items.prop_environment` | New propagation backbone field. |
| `PropFailure` | proposed `rag_items.prop_failure` | New propagation backbone field. |
| `PropHistCode` | proposed `rag_items.prop_hist_code` | New propagation backbone field. |
| `PropMedium` | proposed `rag_items.prop_medium` | New propagation backbone field. |
| `PropQuantity` | proposed `rag_items.prop_quantity` | New propagation backbone field. |
| `PropTreatment` | proposed `rag_items.prop_treatment` | New propagation backbone field. |
| `ProvenanceCode` | proposed `rag_accessions.provenance_code` or optional `rag_items.provenance_code` | Now available at item-history level. Decide whether to promote to accession summary and/or keep at item level. |
| `RecDate` | proposed `rag_items.rec_date` | Useful for dating card context. |
| `TaxonName` | `rag_items.taxon_name` | Direct map; genus may need parsing or join. |

**Derived / inferred for `rag_items`:**

| Target RAG column | Source / derivation | Notes |
|---|---|---|
| `item_suffix` | derive from `ItemAccNoFull` | Existing parsing logic likely already does this. |
| `genus` | join from nomenclature on `AccNoFull`, or parse from `TaxonName` | Needed because new item file does not include a separate `Genus` column. |
| `item_type` | `NULL` or mapped from `MaterialType` with care | Old `ItemType` is gone. Do not assume exact equivalence without checking. |
| `source_row_hash` | computed | No change. |

### C. `rag_taxa` and `rag_filename_genus_index`

These continue to be built primarily from the nomenclature file:

| Target table | Source columns | Notes |
|---|---|---|
| `rag_taxa` | `Genus`, derived normalized genus, derived `taxon_name`, normalized `taxon_name`, `TaxonNameFull`, `Family` | Observation counts and accession year ranges can still be computed from accession-level records. |
| `rag_filename_genus_index` | `Genus` | No major change; still driven by accession taxonomy. |

## 2. What's Lost (old → new)

The old backbone exports were broad administrative exports (`171` accession columns, `76` item columns). The new files are much leaner (`9` and `23` columns), so several fields the current builder expects are no longer present.

### Missing from nomenclature file

- `Collector`
- `CollDate` / `CollectionDate`
- `CountryCode` / `Country`
- `AccYear` as an explicit column
- `Current`

### Missing from item history file

- `Genus` as a standalone column
- `ItemType`

### Practical impact

- `AccYear` is not a real blocker because it can already be derived from `AccNoFull`.
- `Genus` in item history can be recovered by joining to the nomenclature file on `AccNoFull`, or parsed from `TaxonName` as fallback.
- `Current` is missing from the nomenclature file, but the item history file still has a `Current` marker (`>>>`), so current-state logic can be derived there.
- `ItemType` is genuinely absent; `MaterialType` may be a workable replacement, but that should be treated as a mapping decision rather than assumed equivalence.

Most importantly: **most of the lost fields were not actually used by the OCR guidance flow.** They were stored in the RAG backbone, but they were not the fields doing the heavy lifting during card processing.

## 3. What's Gained

The new exports are much better aligned with propagation-card use.

### New or more explicit useful fields

- `Cultivar` in the nomenclature file
- Explicit propagation fields in item history:
  - `PropContainer`
  - `PropDuration`
  - `PropEnvironment`
  - `PropFailure`
  - `PropHistCode`
  - `PropMedium`
  - `PropQuantity`
  - `PropTreatment`
  - `PropComment`
- `ItemLocationCode`
- `ItemLocationName`
- `MaterialType`
- `ProjectCode`
- `ProvenanceCode` in item history
- `RecDate` (material received date)

### Why this matters

These `Prop*` fields are the digital analog of the information written on the physical propagation cards. That makes the new backbone more useful for OCR validation than the older, broader exports. Instead of merely carrying administrative context, the backbone can now directly support comparison between OCR-extracted card content and known digital records.

## 4. `config.yaml` Changes Needed

### Recommended changes

- Add a new data source key: `accession_nomenclature`
  - Point it to `2026-05-11_all-accession_nomentature.csv`
- Change `accession_item_history`
  - Point it to `2026-05-11_all_item_history_edited.csv`
- Old `accession_history`
  - Either remove it entirely, or keep it as a secondary/legacy reference source if there is still occasional need for collector/country metadata

### Practical config direction

The builder should stop treating `accession_history` as the sole accession backbone. The new taxonomy backbone is now the nomenclature file, with item history used as the operational enrichment layer.

## 5. `rag_index_builder.py` Changes Needed

### Core strategy shift: two-file backbone

Use a **two-file strategy**:

1. Build `rag_accessions` primarily from the nomenclature file
   - taxonomy
   - accession identifiers
   - family/genus/species/infra/cultivar context
2. Enrich from item history where needed
   - `is_current`
   - `provenance_code`
   - propagation-related context if accession-level rollups are ever needed

### Specific builder changes

- Switch accession-source logic from old `accession_history.csv` to `accession_nomenclature`
- Use `AccNoFull` as the join key between nomenclature and item history
- Adjust column lookups for removed fields:
  - `collector` → set `NULL`
  - `collection_date` → set `NULL`
  - `country` → set `NULL`
- Keep existing accession-year derivation from accession number
- Derive `is_current` from item history `Current` field (`>>>`)
- For `rag_items.genus`, either:
  - join from nomenclature on `AccNoFull` (**preferred**), or
  - parse genus from `TaxonName` as fallback
- Handle missing `ItemType`
  - likely set `item_type = NULL`
  - optionally map from `MaterialType` if validated as semantically compatible

### New item-field population

The builder should be expanded to populate the propagation fields now available in the item history file:

- `PropContainer`
- `PropDuration`
- `PropEnvironment`
- `PropFailure`
- `PropHistCode`
- `PropMedium`
- `PropQuantity`
- `PropTreatment`

This is the biggest practical improvement in the new backbone.

## 6. Schema Additions for Propagation Context

The current `rag_items` table only stores:

- `propagule`
- `prop_comment`

That is too thin now that the backbone includes much richer propagation detail.

### Proposed additions to `rag_items`

Add these propagation-specific columns:

- `prop_container`
- `prop_duration`
- `prop_environment`
- `prop_failure`
- `prop_hist_code`
- `prop_medium`
- `prop_quantity`
- `prop_treatment`

Also add these operational context columns:

- `item_location_code`
- `item_location_name`
- `material_type`
- `project_code`
- `rec_date`
- `item_status_date`

### Why add them

These are not peripheral metadata anymore. They are the exact kind of fields the OCR pipeline is trying to extract from handwritten cards. Storing them in the RAG layer means OCR output can be checked against known digital records, improving validation, confidence scoring, and ambiguity resolution.

## 7. Synonym-Aware Matching Design

The new nomenclature export has **no synonymy field**, so synonym handling has to come from a separate source.

### Two resolution paths

#### A. IrisBG synonym export (**preferred if available**)
Ask Kevin to check whether IrisBG can export accepted-name/synonym relationships separately.

#### B. POWO backbone dictionary
Kevin has already used Plants of the World Online in related work. That makes POWO the obvious external fallback for synonym normalization.

### Proposed new table: `rag_synonyms`

| Column | Purpose |
|---|---|
| `accepted_name` | Accepted taxon name |
| `synonym_name` | Alternate/synonym name |
| `synonym_name_normalized` | Normalized lookup form |
| `source` | `irisBG` or `powo` |
| `confidence` | Confidence or trust level for the synonym link |

### Matching strategy

1. Exact match on `taxon_name_normalized`
2. If no hit, check `rag_synonyms`
3. If still no hit, try fuzzy genus + epithet matching
4. If still no hit, fall back to genus-only match and flag it as weak

### Key design insight

The synonym logic should be **bidirectional**.

That matters because:

- a card may carry an older name while IrisBG has since updated it
- less likely, but possible: a card may use a newer name while IrisBG still carries an older one

So the system should support both:

- card name → accepted IrisBG name
- IrisBG stored name → alternate name likely to appear on a card

That makes synonym handling a lookup layer, not just a one-way cleanup pass.

---

## Bottom Line

The new exports drop a lot of broad accession metadata, but they improve the backbone for the actual propagation-card problem.

The main architectural change is simple:

- use the nomenclature file as the accession/taxonomy backbone
- use the item history file as the operational/propagation backbone
- extend `rag_items` so the digital propagation record is actually represented in the schema

That should make the RAG context both leaner and more relevant to OCR validation.