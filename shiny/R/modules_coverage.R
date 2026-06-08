coverage_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h4("Field Population Across Extractions"),
    DT::DTOutput(ns("coverage_table")),
    shiny::uiOutput(ns("coverage_summary_ui"))
  )
}

coverage_server <- function(id, conn, validation) {
  shiny::moduleServer(id, function(input, output, session) {
    coverage_df <- shiny::reactive({
      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      get_field_coverage(conn()) |>
        dplyr::mutate(bar = paste0(strrep("\u2588", floor(coverage_pct / 5)), strrep("\u2591", 20 - floor(coverage_pct / 5))))
    })

    output$coverage_table <- DT::renderDT({
      df <- coverage_df()
      shiny::validate(shiny::need(nrow(df) > 0, "No extractions yet."))
      DT::datatable(
        dplyr::rename(df, Field = field, Populated = populated, Total = total, `Coverage %` = coverage_pct, Bar = bar),
        rownames = FALSE,
        options = list(dom = "tip", pageLength = 25, scrollX = TRUE)
      )
    })

    output$coverage_summary_ui <- shiny::renderUI({
      df <- coverage_df()
      if (nrow(df) == 0) return(NULL)
      shiny::p(shiny::strong("Fields with data:"), sprintf("%s/%s", sum(df$populated > 0), length(extraction_fields)))
    })
  })
}
