# Extraction Schema — Card Field to JSON to CSV Mapping

> Every card field gets its own JSON key. Empty/absent fields return null.
> Old-only and new-only fields naturally self-select based on card era.

| Card Field (Old) | Card Field (New) | JSON Key | CSV Validation Source | Notes |
|---|---|---|---|---|
| BOTANICAL NAME | Botanical Name | `botanical_name` | `TaxonName`, `SynonymName`, `SpeciesAuthor`, `Genus`, `Species`, `InfraGroup`, `CultivarGroup`, `InfraName1` (taxonomy); `TaxonName` (items) | May include author, infraspecific ranks |
| FAMILY NAME | Family | `family` | `Family` (taxonomy) | |
| *(row 2 — usually empty)* | *(removed)* | — | — | Not extracted |
| GEOGRACODE (ORIGIN) | *(removed)* | `geocode` | — | Obsolete code, old cards only |
| REC'D AS | Received as | `received_as` | `MaterialTypeCode`, `MaterialType` (taxonomy); `MaterialTypeCode`, `Propagule` (items) | SEED, URCU, PLNT, etc. |
| QUANTITY | Quantity | `quantity` | `ItemSpecCount` where `ItemStatus` == "Prop: Culturing" (items, post-2017) | Seed/material count |
| DAY / MONTH / YEAR | Date – Y/M/D | `date_received` | `RecDate` (both CSVs) | D/M/Y on old, Y/M/D on new |
| PRESENT LOCATION | *(removed)* | `present_location` | `ItemLocationCode` (items) | 8 = nursery; old cards only |
| WANTED FOR AREA | Wanted for Area | `wanted_for_area` | `Purpose` (items) | Target garden section |
| SOURCE | Source | `source` | — | Numeric code; privacy-stripped from CSVs |
| MISC. SOU. INFO | *(removed)* | `source_info` | — | Old cards only; privacy-stripped |
| COLLECTOR NO. | Collector # | `collector_number` | `OriginRef` (taxonomy); `ProjectCode` (items) | Inconsistent across eras |
| OTHER NUMBER | Other # | `other_number` | — | External institution accession or Index Seminum |
| NO. OF LABELS | *(removed)* | `labels_requested` | — | Old cards only |
| MAXIMUM QTY REQUIRED | Quantity Requested | `max_quantity` | `ItemComment` during "Prop: Culturing"/"Prop: Observed" (items, post-2017) | |
| EX. | *(removed — replaced by Parent Accession)* | `parent_accession` | — | Old: right side above Curator's Info. New: dedicated field. Same meaning — source accession for re-propagated material |
| *(n/a)* | Parent accession | `parent_accession` | — | Same key as EX. |
| COLLECTION INFORMATION | *(removed)* | `collection_info` | `ParentageComment`, `TaxonDistributionNote`, `CommonName_en`, `LifeForm`, `OriginRef` (taxonomy); `AtrA_Variant`, `AtrT_Flower_color` (items) | Full-width row, old cards only |
| DISTRIBUTION | *(removed)* | `distribution` | `TaxonDistributionNote` (taxonomy) | Old cards only |
| ACCESSION NUMBER | Accession number | `accession_number` | `AccNoFull`, `AccNoCons` (both CSVs) | **Primary target.** List — may contain multiple. Position differs between eras |
| PROPAGATION | propagation notes | `propagation_text` | Propagation fields in items CSV (`PropComment`, `PropContainer`, `PropDuration`, `PropEnvironment`, `PropMedium`, `PropTreatment`); status dates from `ItemStatusDate` | Full transcription of propagation area |
| CURATOR'S INFORMATION | *(untitled blank field)* | `curators_info` | `ParentageComment`, `TaxonDistributionNote`, `CommonName_en`, `LifeForm`, `OriginRef` (taxonomy); `AtrA_Variant`, `AtrT_Flower_color`, `PropComment` (items) | Right ¼ of card. Kevin uses for dormancy notes on modern cards |
| *(n/a)* | IRIS data entered | `iris_data_entered` | — | New cards only, checkbox |

## JSON Output Schema

```json
{
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
  "accession_number": ["string array — all visible accession numbers"],
  "propagation_text": "string — full propagation area transcription",
  "curators_info": "string or null",
  "iris_data_entered": "boolean or null"
}
```

All values are the model's best transcription of what is written/stamped/printed on the card. Null means the field is not visible or not present on the card format.
