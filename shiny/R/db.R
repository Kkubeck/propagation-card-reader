`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

find_images_dir <- function(app_dir = ".") {
  candidates <- c(
    fs::path(app_dir, "images"),
    fs::path(app_dir, "..", "images")
  )
  for (candidate in candidates) {
    if (fs::dir_exists(candidate)) return(fs::path_abs(candidate))
  }
  NULL
}

extraction_fields <- c(
  "botanical_name", "family", "geocode", "received_as", "quantity",
  "date_received", "present_location", "wanted_for_area", "source",
  "source_info", "collector_number", "other_number", "labels_requested",
  "max_quantity", "parent_accession", "collection_info", "distribution",
  "accession_number", "propagation_text", "curators_info", "iris_data_entered"
)

field_groups <- list(
  "Identity" = c("botanical_name", "family", "accession_number"),
  "Received" = c("received_as", "quantity", "date_received", "source", "source_info"),
  "Location" = c("present_location", "wanted_for_area", "geocode"),
  "References" = c("collector_number", "other_number", "parent_accession", "labels_requested", "max_quantity"),
  "Notes" = c("collection_info", "distribution", "curators_info"),
  "Propagation" = c("propagation_text"),
  "Meta" = c("iris_data_entered")
)

default_query_sql <- paste(
  "SELECT",
  "    e.botanical_name,",
  "    e.accession_number,",
  "    e.family,",
  "    e.received_as,",
  "    e.propagation_text",
  "FROM extractions e",
  "JOIN cards c ON c.id = e.card_id",
  "WHERE c.status = 'success'",
  "LIMIT 20;",
  sep = "\n"
)

default_db_candidates <- function(app_dir = ".") {
  candidate <- fs::path(app_dir, "cards.db")
  if (fs::file_exists(candidate)) fs::path_abs(candidate) else character(0)
}

db_choice_label <- function(path) {
  sprintf("%s (%s)", fs::path_file(path), fs::path_dir(path))
}

resolve_db_path <- function(selected, uploaded_datapath, manual_path) {
  manual_trimmed <- stringr::str_trim(manual_path %||% "")
  if (nzchar(manual_trimmed)) {
    return(path.expand(manual_trimmed))
  }
  if (!is.null(uploaded_datapath) && nzchar(uploaded_datapath)) {
    return(uploaded_datapath)
  }
  if (!is.null(selected) && nzchar(selected) && selected != "") {
    return(selected)
  }
  NULL
}

status_count_value <- function(status_df, key) {
  idx <- which(status_df$status == key)
  if (length(idx) == 0) 0L else status_df$n[[idx[[1]]]]
}

safe_json_rows <- function(json_text) {
  if (is.null(json_text) || !nzchar(stringr::str_trim(as.character(json_text)))) {
    return(NULL)
  }

  parsed <- tryCatch(jsonlite::fromJSON(json_text, simplifyDataFrame = TRUE), error = function(...) NULL)
  if (is.null(parsed)) {
    return(NULL)
  }
  if (!is.null(parsed$rows)) return(as.data.frame(parsed$rows, stringsAsFactors = FALSE))
  if (!is.null(parsed$records)) return(as.data.frame(parsed$records, stringsAsFactors = FALSE))
  if (!is.null(parsed$replicates)) return(as.data.frame(parsed$replicates, stringsAsFactors = FALSE))
  NULL
}

simple_html_table <- function(df) {
  if (is.null(df) || nrow(df) == 0) {
    return(NULL)
  }

  header <- shiny::tags$tr(lapply(names(df), shiny::tags$th))
  body_rows <- lapply(seq_len(nrow(df)), function(i) {
    shiny::tags$tr(lapply(df[i, , drop = FALSE], function(value) {
      shiny::tags$td(as.character(value[[1]] %||% ""))
    }))
  })

  shiny::tags$table(
    class = "table table-sm table-striped",
    shiny::tags$thead(header),
    shiny::tags$tbody(body_rows)
  )
}

open_sqlite_readonly <- function(db_path) {
  DBI::dbConnect(RSQLite::SQLite(), dbname = db_path, flags = RSQLite::SQLITE_RO)
}

db_tables <- function(conn) {
  DBI::dbGetQuery(conn, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")$name
}

validate_database <- function(db_path) {
  result <- list(valid = FALSE, message = NULL, tables = character(0))

  if (is.null(db_path) || !nzchar(db_path)) {
    result$message <- "No database path provided."
    return(result)
  }

  normalized <- path.expand(db_path)
  if (!fs::file_exists(normalized)) {
    result$message <- sprintf("Database not found: %s", normalized)
    return(result)
  }

  conn <- NULL
  tryCatch({
    conn <- open_sqlite_readonly(normalized)
    result$tables <- db_tables(conn)
    missing <- setdiff(c("cards", "extractions"), result$tables)
    if (length(missing) > 0) {
      result$message <- sprintf("Missing required table(s): %s", paste(missing, collapse = ", "))
      return(result)
    }
    result$valid <- TRUE
    result$message <- "Database is compatible."
    result
  }, error = function(err) {
    result$message <- conditionMessage(err)
    result
  }, finally = {
    if (!is.null(conn)) DBI::dbDisconnect(conn)
  })
}

available_extraction_columns <- function(conn) {
  DBI::dbGetQuery(conn, "PRAGMA table_info(extractions)")$name
}

apply_search_filter <- function(search, where_clauses, params) {
  trimmed <- stringr::str_trim(search)
  id_match <- stringr::str_match(trimmed, "^(?i)id\\s*=\\s*(\\d+)$")

  if (!is.na(id_match[1, 2])) {
    where_clauses <- c(where_clauses, "c.id = ?")
    params <- c(params, as.integer(id_match[1, 2]))
  } else {
    term <- sprintf("%%%s%%", trimmed)
    where_clauses <- c(
      where_clauses,
      "(e.botanical_name LIKE ? OR e.propagation_text LIKE ? OR e.accession_number LIKE ?)"
    )
    params <- c(params, term, term, term)
  }

  list(where_clauses = where_clauses, params = params)
}

get_status_summary <- function(conn) {
  DBI::dbGetQuery(conn, "SELECT status, count(*) AS n FROM cards GROUP BY status ORDER BY status")
}

get_field_coverage <- function(conn) {
  total <- DBI::dbGetQuery(conn, "SELECT count(*) AS n FROM extractions")$n[[1]]
  if (is.na(total) || total == 0) {
    return(dplyr::tibble())
  }

  dplyr::bind_rows(lapply(extraction_fields, function(field_name) {
    filled <- tryCatch({
      sql <- sprintf(
        "SELECT count(*) AS n FROM extractions WHERE %s IS NOT NULL AND %s != ''",
        field_name,
        field_name
      )
      DBI::dbGetQuery(conn, sql)$n[[1]]
    }, error = function(...) 0)

    dplyr::tibble(
      field = field_name,
      populated = filled,
      total = total,
      coverage_pct = round(filled / total * 100, 1)
    )
  }))
}

build_extractions_query <- function(conn, where_sql = "") {
  cols_available <- available_extraction_columns(conn)
  select_fields <- vapply(extraction_fields, function(field_name) {
    if (field_name %in% cols_available) sprintf("e.%s", field_name) else sprintf("NULL AS %s", field_name)
  }, character(1))

  paste(
    "SELECT",
    "c.id AS card_id,",
    "c.pdf_path,",
    "c.page_num,",
    "c.status,",
    "c.error_message,",
    "c.image_path,",
    "e.processing_time_s,",
    "e.model,",
    "e.dpi,",
    paste(select_fields, collapse = ", "),
    ", e.parsed_table_json,",
    "e.parsed_other_sowings_json,",
    "e.parsed_replicate_json,",
    "GROUP_CONCAT(a.accession_number, ' | ') AS all_accession_numbers",
    "FROM cards c",
    "LEFT JOIN extractions e ON e.card_id = c.id",
    "LEFT JOIN accession_numbers a ON a.extraction_id = e.id",
    where_sql,
    "GROUP BY c.id",
    "ORDER BY c.id",
    "LIMIT ? OFFSET ?"
  )
}

get_extractions_df <- function(conn, limit = 500L, offset = 0L, search = NULL, status_filter = NULL) {
  where_clauses <- character(0)
  params <- list()

  if (!is.null(status_filter) && nzchar(status_filter) && status_filter != "All") {
    where_clauses <- c(where_clauses, "c.status = ?")
    params <- c(params, status_filter)
  }
  if (!is.null(search) && nzchar(stringr::str_trim(search))) {
    filtered <- apply_search_filter(search, where_clauses, params)
    where_clauses <- filtered$where_clauses
    params <- filtered$params
  }

  where_sql <- if (length(where_clauses) > 0) paste("WHERE", paste(where_clauses, collapse = " AND ")) else ""
  DBI::dbGetQuery(conn, build_extractions_query(conn, where_sql), params = c(params, list(as.integer(limit), as.integer(offset))))
}

get_card_count <- function(conn, status_filter = NULL, search = NULL) {
  where_clauses <- character(0)
  params <- list()

  if (!is.null(status_filter) && nzchar(status_filter) && status_filter != "All") {
    where_clauses <- c(where_clauses, "c.status = ?")
    params <- c(params, status_filter)
  }
  if (!is.null(search) && nzchar(stringr::str_trim(search))) {
    filtered <- apply_search_filter(search, where_clauses, params)
    where_clauses <- filtered$where_clauses
    params <- filtered$params
  }

  where_sql <- if (length(where_clauses) > 0) paste("WHERE", paste(where_clauses, collapse = " AND ")) else ""
  DBI::dbGetQuery(
    conn,
    paste("SELECT count(DISTINCT c.id) AS n FROM cards c LEFT JOIN extractions e ON e.card_id = c.id", where_sql),
    params = params
  )$n[[1]]
}

is_readonly_select <- function(sql) {
  trimmed <- stringr::str_trim(sql)
  if (!nzchar(trimmed)) return(FALSE)

  without_semicolon <- stringr::str_replace(trimmed, ";+$", "")
  starts_select <- stringr::str_detect(without_semicolon, stringr::regex("^(select|with)\\b", ignore_case = TRUE))
  banned <- stringr::str_detect(
    without_semicolon,
    stringr::regex("\\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate)\\b", ignore_case = TRUE)
  )
  starts_select && !banned
}

run_readonly_query <- function(conn, sql) {
  if (!is_readonly_select(sql)) {
    stop("Only read-only SELECT or WITH queries are allowed.")
  }
  DBI::dbGetQuery(conn, sql)
}

compare_databases <- function(conn1, conn2) {
  status1 <- get_status_summary(conn1)
  status2 <- get_status_summary(conn2)
  coverage1 <- get_field_coverage(conn1)
  coverage2 <- get_field_coverage(conn2)

  coverage_compare <- dplyr::tibble(field = extraction_fields) |>
    dplyr::left_join(dplyr::select(coverage1, field, db1_pct = coverage_pct), by = "field") |>
    dplyr::left_join(dplyr::select(coverage2, field, db2_pct = coverage_pct), by = "field") |>
    dplyr::mutate(
      db1_pct = dplyr::coalesce(db1_pct, 0),
      db2_pct = dplyr::coalesce(db2_pct, 0),
      delta_pct = round(db2_pct - db1_pct, 1)
    )

  avg1 <- DBI::dbGetQuery(conn1, "SELECT AVG(processing_time_s) AS avg_time FROM extractions")$avg_time[[1]]
  avg2 <- DBI::dbGetQuery(conn2, "SELECT AVG(processing_time_s) AS avg_time FROM extractions")$avg_time[[1]]

  list(status1 = status1, status2 = status2, coverage = coverage_compare, avg1 = avg1, avg2 = avg2)
}
