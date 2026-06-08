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

## Launch

From Terminal on Mac:

```bash
cd /home/hevek/Desktop/codex_project/prop-card-viewer-shiny
Rscript -e "shiny::runApp('.', launch.browser = TRUE)"
```

Or from R:

```r
setwd("/home/hevek/Desktop/codex_project/prop-card-viewer-shiny")
shiny::runApp(".")
```

## Database Selection

The app does not scan your filesystem recursively.

It supports only these explicit database selection methods:

- default app-local `cards.db` if present
- manual path entry
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
