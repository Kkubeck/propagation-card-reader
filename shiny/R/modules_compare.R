compare_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h4("Compare Two Databases"),
    shiny::p("Select a second database to compare field coverage and success rates."),
    shiny::uiOutput(ns("compare_choice_ui")),
    shiny::textInput(ns("compare_manual_db_path"), "Comparison database path", placeholder = "/path/to/other.db"),
    shiny::fileInput(ns("compare_db_upload"), "Choose comparison .db file", accept = c(".db", ".sqlite", ".sqlite3")),
    shiny::uiOutput(ns("compare_result_ui"))
  )
}

compare_server <- function(id, conn, validation, app_defaults) {
  shiny::moduleServer(id, function(input, output, session) {
    compare_db_path <- shiny::reactive({
      upload_datapath <- if (!is.null(input$compare_db_upload)) input$compare_db_upload$datapath else NULL
      resolve_db_path(input$compare_db_choice, upload_datapath, input$compare_manual_db_path)
    })

    output$compare_choice_ui <- shiny::renderUI({
      choices <- c(stats::setNames("", ""), stats::setNames(app_defaults, vapply(app_defaults, db_choice_label, character(1))))
      shiny::selectInput(session$ns("compare_db_choice"), "Comparison default database", choices = choices, selected = "")
    })

    output$compare_result_ui <- shiny::renderUI({
      path2 <- compare_db_path()
      if (is.null(path2) || !nzchar(path2)) {
        return(shiny::div("Select a comparison database."))
      }

      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      validation2 <- validate_database(path2)
      shiny::validate(shiny::need(validation2$valid, validation2$message))

      conn2 <- open_sqlite_readonly(path2)
      on.exit(DBI::dbDisconnect(conn2), add = TRUE)
      comparison <- compare_databases(conn(), conn2)

      shiny::tagList(
        shiny::p(shiny::strong("DB 1:"), shiny::code(attr(conn(), "dbname") %||% "selected database")),
        shiny::p(sprintf("Success: %s | Failed: %s", status_count_value(comparison$status1, "success"), status_count_value(comparison$status1, "failed"))),
        shiny::p(shiny::strong("DB 2:"), shiny::code(path2)),
        shiny::p(sprintf("Success: %s | Failed: %s", status_count_value(comparison$status2, "success"), status_count_value(comparison$status2, "failed"))),
        shiny::p(sprintf("Avg time (DB1): %s", if (!is.na(comparison$avg1)) sprintf("%.1fs", comparison$avg1) else "-")),
        shiny::p(sprintf("Avg time (DB2): %s", if (!is.na(comparison$avg2)) sprintf("%.1fs", comparison$avg2) else "-")),
        DT::dataTableOutput(session$ns("compare_table"))
      )
    })

    output$compare_table <- DT::renderDataTable({
      path2 <- compare_db_path()
      shiny::req(path2)
      validation2 <- validate_database(path2)
      shiny::validate(shiny::need(validation2$valid, validation2$message))
      conn2 <- open_sqlite_readonly(path2)
      on.exit(DBI::dbDisconnect(conn2), add = TRUE)

      DT::datatable(
        compare_databases(conn(), conn2)$coverage |>
          dplyr::mutate(`DB1 %` = db1_pct, `DB2 %` = db2_pct, `Delta %` = sprintf("%+.1f%%", delta_pct)) |>
          dplyr::select(Field = field, `DB1 %`, `DB2 %`, `Delta %`),
        rownames = FALSE,
        options = list(dom = "tip", pageLength = 25, scrollX = TRUE)
      )
    })
  })
}
