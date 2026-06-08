library(shiny)
library(DBI)
library(RSQLite)
library(DT)
library(dplyr)
library(stringr)
library(fs)
library(bslib)
library(jsonlite)

source("R/db.R")
source("R/modules_cards.R")
source("R/modules_coverage.R")
source("R/modules_query.R")
source("R/modules_compare.R")

images_dir <- find_images_dir(".")

ui <- bslib::page_sidebar(
  title = "Propagation Card Reader - DB Viewer",
  theme = bslib::bs_theme(version = 5, bootswatch = "minty"),
  sidebar = bslib::sidebar(
    width = 340,
    shiny::h4("Database"),
    shiny::uiOutput("db_choice_ui"),
    shiny::textInput("manual_db_path", "Manual database path", placeholder = "/path/to/cards.db"),
    shiny::fileInput("db_upload", "Choose SQLite .db file", accept = c(".db", ".sqlite", ".sqlite3")),
    shiny::uiOutput("active_db_ui"),
    shiny::hr(),
    shiny::h4("Status"),
    shiny::uiOutput("status_ui")
  ),
  bslib::navset_tab(
    bslib::nav_panel("Card Browser", cards_ui("cards")),
    bslib::nav_panel("Field Coverage", coverage_ui("coverage")),
    bslib::nav_panel("SQL Query", query_ui("query")),
    bslib::nav_panel("Compare DBs", compare_ui("compare"))
  )
)

server <- function(input, output, session) {
  if (!is.null(images_dir)) {
    shiny::addResourcePath("card_images", images_dir)
  }

  app_defaults <- default_db_candidates(".")
  conn_state <- reactiveVal(NULL)

  active_db_path <- reactive({
    upload_datapath <- if (!is.null(input$db_upload)) input$db_upload$datapath else NULL
    resolve_db_path(input$db_choice, upload_datapath, input$manual_db_path)
  })

  active_db_validation <- reactive({
    req(active_db_path())
    validate_database(active_db_path())
  })

  observeEvent(active_db_path(), {
    path <- active_db_path()
    old_conn <- conn_state()
    if (!is.null(old_conn)) {
      try(DBI::dbDisconnect(old_conn), silent = TRUE)
      conn_state(NULL)
    }
    if (is.null(path) || !nzchar(path)) return()
    validation <- validate_database(path)
    if (!validation$valid) return()
    conn_state(open_sqlite_readonly(path))
  }, ignoreNULL = FALSE)

  session$onSessionEnded(function() {
    conn <- conn_state()
    if (!is.null(conn)) try(DBI::dbDisconnect(conn), silent = TRUE)
  })

  active_conn <- reactive({
    validation <- active_db_validation()
    req(validation$valid)
    conn <- conn_state()
    req(conn)
    conn
  })

  output$db_choice_ui <- renderUI({
    choices <- c(stats::setNames("", ""), stats::setNames(app_defaults, vapply(app_defaults, db_choice_label, character(1))))
    selectInput("db_choice", "Default database", choices = choices, selected = if (length(app_defaults) > 0) app_defaults[[1]] else "")
  })

  output$active_db_ui <- renderUI({
    path <- active_db_path()
    if (is.null(path) || !nzchar(path)) return(div("No database selected."))
    validation <- validate_database(path)
    size_text <- if (fs::file_exists(path)) sprintf("%.0f KB", as.numeric(fs::file_size(path)) / 1024) else "n/a"
    color <- if (validation$valid) "#1a7f37" else "#b42318"
    div(
      p(strong("Active DB:"), br(), code(path)),
      p(style = sprintf("color:%s;", color), validation$message %||% ""),
      p(strong("Size:"), size_text)
    )
  })

  output$status_ui <- renderUI({
    validation <- active_db_validation()
    validate(need(validation$valid, validation$message %||% "Database not ready."))
    conn <- active_conn()
    req(conn)
    status <- get_status_summary(conn)
    success <- status_count_value(status, "success")
    failed <- status_count_value(status, "failed")
    error_count <- status_count_value(status, "error")
    completed <- success + failed + error_count
    rate <- if (completed > 0) round(success / completed * 100, 1) else NA_real_

    tagList(
      p(strong("Total:"), sum(status$n)),
      p(strong("Success:"), success),
      if (!is.na(rate)) p(strong("Success rate:"), sprintf("%.1f%%", rate)),
      tags$ul(lapply(seq_len(nrow(status)), function(i) tags$li(sprintf("%s: %s", status$status[[i]], status$n[[i]]))))
    )
  })

  cards_server("cards", active_conn, active_db_validation, images_dir)
  coverage_server("coverage", active_conn, active_db_validation)
  query_server("query", active_conn, active_db_validation)
  compare_server("compare", active_conn, active_db_validation, app_defaults)
}

shinyApp(ui, server)
