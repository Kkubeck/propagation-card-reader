#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(DBI)
  library(RSQLite)
  library(fs)
  library(stringr)
  library(dplyr)
  library(jsonlite)
  library(shiny)
})

args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
script_dir <- if (length(file_arg) == 1) fs::path_dir(sub("^--file=", "", file_arg)) else "."

source(fs::path(script_dir, "..", "R", "db.R"))

args <- commandArgs(trailingOnly = TRUE)
db_path <- if (length(args) > 0) args[[1]] else "test.db"

result <- validate_database(db_path)
cat(sprintf("Path: %s\n", fs::path_abs(path.expand(db_path))))
cat(sprintf("Valid: %s\n", result$valid))
cat(sprintf("Message: %s\n", result$message %||% ""))
if (length(result$tables) > 0) {
  cat(sprintf("Tables: %s\n", paste(result$tables, collapse = ", ")))
}

quit(status = if (isTRUE(result$valid)) 0 else 1)
