# Accession Number Formats — UBC Botanical Garden

## Legacy Format (pre-~2012)
- Pattern: `NNNNN-NNN-NN` (e.g. `21420-027-82`)
- Called "conserved accession numbers"
- Cards only got an accession number when germination succeeded
- Failed germination cards have NO accession — just the taxon name
- These "no accession" cards are still valuable (germination failure data)

## Modern Format (post-~2012)
- Pattern: `YYYY-NNNNN` (e.g. `2015-00444`) — 4-digit year + 5-digit sequence
- No conserved number, only modern number
- Assigned at sowing, not germination

## Accession Item Suffixes
- Pattern: `YYYY-NNNN.NN` (e.g. `2019-0082.99`)
- Decimal suffix = accession item number
- Common suffixes: {80, 81, 82, ... 88, 89, 99}
- Each suffix = different treatment or separate sowing of same accession
- More recent cards may have multiple item suffixes

## Cards With No Accession
- Pre-~2012: if germination failed, no accession was assigned
- These cards still have taxon name and propagation notes
- Model should NOT hallucinate an accession — leave blank/null
- The taxon name becomes the primary identifier for these cards

## Implications for OCR
- A bare number like "1" or "3" is NOT a valid accession — likely a misread
- "..." or blank accession may be legitimate (pre-2012 failed germination)
- 5-digit sequences like `2015-00444` ARE valid modern accessions
- Decimal suffixes ARE real, not OCR artifacts
