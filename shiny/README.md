# Propagation Card Viewer Shiny

Read-only R Shiny replacement for the Python Streamlit propagation card database viewer.

## Requirements

- R 4.1+ (Windows, macOS, or Linux)
- SQLite database file such as `cards.db`
- R packages:
  - `shiny`
  - `DBI`
  - `RSQLite`
  - `DT`
  - `dplyr`
  - `stringr`
  - `fs`
  - `bslib`
  - `jsonlite`

## Install Packages

Open R or RStudio and run:

```r
install.packages(c(
  "shiny", "DBI", "RSQLite", "DT", "dplyr",
  "stringr", "fs", "bslib", "jsonlite",
  "pdftools", "base64enc"
))
```

The last two (`pdftools`, `base64enc`) are optional — needed only for
displaying card images from PDFs. The app works without them (data only).

## Folder Layout

Put everything in one parent folder on a shared drive or local disk:

```
propagation_cards/                  (or any name you like)
├── prop-card-viewer-shiny/         (this app — all files from the ZIP)
│   ├── app.R
│   ├── R/
│   ├── launch.R
│   ├── launch.bat
│   └── cards.db                    (copy your database here)
└── propagation_cards_historical/   (the original PDF scans)
```

The app auto-detects the PDF folder as a sibling directory.

## Launch (Windows — one click)

Double-click **`launch.bat`** inside the app folder. First run installs
packages automatically (~30 seconds). After that it opens instantly.

No R knowledge required. No typing.

## Launch (Mac / Linux)

Open a terminal in the app folder and run:

```bash
Rscript launch.R
```

Or from RStudio: open `app.R` and click the green **Run App** button.

## Database Selection

The app looks for `cards.db` inside its own folder by default.

It also supports:

- manual path entry in the sidebar
- file picker upload

Each selected database is validated by checking that it contains at least the `cards` and `extractions` tables.

## Features

- card browser with search, status filter, pagination, and row detail
- field coverage summary for the extraction fields used by the Python app
- read-only SQL query tab with CSV download
- comparison tab for two databases

## Read-only Guarantees

- SQLite connections are opened through `DBI` + `RSQLite`
- connections use `RSQLite::SQLITE_RO`
- the app does not modify schema or write to the database
- SQL query execution is restricted to read-only `SELECT` or `WITH` statements

## Validation Script

Run the compatibility check against a database:

```bash
Rscript tests/validate_db.R test.db
```

This checks that the file exists, opens it read-only, and confirms the required tables are present.
