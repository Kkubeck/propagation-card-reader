query_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h4("Custom SQL Query"),
    shiny::p("Read-only. Tables: cards, extractions, accession_numbers, processing_runs, rag_contexts"),
    shiny::textAreaInput(ns("sql_query"), "SQL", value = default_query_sql, rows = 8),
    shiny::actionButton(ns("run_query"), "Run Query"),
    shiny::downloadButton(ns("download_query_csv"), "Download CSV"),
    shiny::br(),
    shiny::br(),
    shiny::textOutput(ns("query_status")),
    DT::DTOutput(ns("query_table"))
  )
}

query_server <- function(id, conn, validation) {
  shiny::moduleServer(id, function(input, output, session) {
    query_result <- shiny::eventReactive(input$run_query, {
      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      run_readonly_query(conn(), input$sql_query)
    }, ignoreNULL = FALSE)

    output$query_status <- shiny::renderText({
      df <- tryCatch(query_result(), error = function(err) err)
      if (inherits(df, "error")) sprintf("Query error: %s", conditionMessage(df)) else sprintf("%s rows returned", nrow(df))
    })

    output$query_table <- DT::renderDT({
      DT::datatable(query_result(), rownames = FALSE, options = list(scrollX = TRUE))
    })

    output$download_query_csv <- shiny::downloadHandler(
      filename = function() "query_results.csv",
      content = function(file) utils::write.csv(query_result(), file, row.names = FALSE)
    )
  })
}
