cards_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::fluidRow(
      shiny::column(6, shiny::textInput(ns("search_text"), "Search", placeholder = "name, accession, propagation text, or id=123")),
      shiny::column(3, shiny::selectInput(ns("status_filter"), "Status", choices = "All", selected = "All")),
      shiny::column(3, shiny::selectInput(ns("per_page"), "Per page", choices = c(10, 25, 50, 100), selected = 25))
    ),
    shiny::fluidRow(
      shiny::column(4, shiny::numericInput(ns("page"), "Page", value = 1, min = 1, step = 1)),
      shiny::column(8, shiny::div(style = "padding-top: 30px;", shiny::textOutput(ns("page_caption"))))
    ),
    DT::DTOutput(ns("cards_table")),
    shiny::hr(),
    shiny::fluidRow(
      shiny::column(6, shiny::uiOutput(ns("card_image_ui"))),
      shiny::column(6, shiny::uiOutput(ns("card_detail_ui")))
    )
  )
}

cards_server <- function(id, conn, validation, images_dir = NULL, pdf_roots = character(0)) {
  shiny::moduleServer(id, function(input, output, session) {
    observe({
      current_validation <- validation()
      shiny::req(current_validation$valid)
      db <- tryCatch(conn(), error = function(e) NULL)
      shiny::req(db)
      status <- get_status_summary(db)
      shiny::updateSelectInput(session, "status_filter", choices = c("All", status$status), selected = "All")
    })

    filtered_total <- shiny::reactive({
      current_validation <- validation()
      shiny::req(current_validation$valid)
      db <- tryCatch(conn(), error = function(e) NULL)
      shiny::req(db)
      get_card_count(db, status_filter = input$status_filter, search = input$search_text)
    })

    observe({
      total <- tryCatch(filtered_total(), error = function(e) NULL)
      shiny::req(total)
      per_page <- as.integer(input$per_page)
      max_pages <- max(1L, ceiling(total / per_page))
      current_page <- min(max(1L, as.integer(input$page %||% 1L)), max_pages)
      shiny::updateNumericInput(session, "page", value = current_page, min = 1, max = max_pages)
    })

    cards_df <- shiny::reactive({
      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      db <- conn()
      shiny::validate(shiny::need(!is.null(db), "No database connection."))
      per_page <- as.integer(input$per_page)
      current_page <- max(1L, as.integer(input$page %||% 1L))
      offset <- (current_page - 1L) * per_page
      get_extractions_df(db, limit = per_page, offset = offset, search = input$search_text, status_filter = input$status_filter)
    })

    output$page_caption <- shiny::renderText({
      total <- filtered_total()
      per_page <- as.integer(input$per_page)
      max_pages <- max(1L, ceiling(total / per_page))
      sprintf("Showing page %s of %s (%s cards)", input$page %||% 1L, max_pages, total)
    })

    output$cards_table <- DT::renderDT({
      df <- cards_df()
      shiny::validate(shiny::need(nrow(df) > 0, "No cards match the current filters."))
      display_cols <- c("card_id", "status", "accession_number", "botanical_name", "family", "received_as", "date_received", "all_accession_numbers", "processing_time_s")
      DT::datatable(
        df[, intersect(display_cols, names(df)), drop = FALSE],
        selection = "single",
        rownames = FALSE,
        filter = "none",
        options = list(pageLength = as.integer(input$per_page), dom = "tip", scrollX = TRUE)
      )
    })

    selected_card <- shiny::reactive({
      df <- cards_df()
      row_index <- input$cards_table_rows_selected
      if (length(row_index) != 1 || nrow(df) == 0) return(NULL)
      df[row_index, , drop = FALSE]
    })

    output$card_image_ui <- shiny::renderUI({
      row <- selected_card()
      if (is.null(row)) return(shiny::div())

      card <- row[1, , drop = FALSE]
      pdf_path_val <- card$pdf_path[[1]]
      page_num_val <- card$page_num[[1]]

      if (is.null(pdf_path_val) || !nzchar(pdf_path_val) || is.null(page_num_val) || is.na(page_num_val)) {
        return(shiny::p(shiny::em("No PDF reference for this card.")))
      }

      resolved <- resolve_pdf_path(pdf_path_val, pdf_roots)
      if (is.null(resolved)) {
        return(shiny::p(shiny::em(sprintf("PDF not found: %s", basename(pdf_path_val)))))
      }

      if (!has_pdftools()) {
        return(shiny::p(shiny::em("Install the 'pdftools' and 'png' packages to view card images.")))
      }

      tmp_png <- render_pdf_page(resolved, page_num_val)
      if (is.null(tmp_png)) {
        return(shiny::p(shiny::em("Could not render PDF page.")))
      }

      png_data <- base64enc::dataURI(file = tmp_png, mime = "image/png")
      shiny::tagList(
        shiny::p(shiny::strong(sprintf("%s, page %s", basename(pdf_path_val), page_num_val))),
        shiny::tags$img(src = png_data, style = "max-width: 100%; border: 1px solid #ccc;")
      )
    })

    output$card_detail_ui <- shiny::renderUI({
      row <- selected_card()
      if (is.null(row)) {
        return(shiny::div("Select a row above to see card details."))
      }

      card <- row[1, , drop = FALSE]
      detail_blocks <- list(
        shiny::h4(sprintf("%s - %s", card$botanical_name[[1]] %||% "Unknown", card$accession_number[[1]] %||% "-"))
      )

      if (!is.null(card$pdf_path[[1]]) && nzchar(card$pdf_path[[1]])) {
        detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong("PDF path:"), shiny::code(card$pdf_path[[1]]))))
      }
      if (!is.null(card$page_num[[1]]) && !is.na(card$page_num[[1]])) {
        detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong("Page:"), card$page_num[[1]])))
      }
      if (!is.null(card$error_message[[1]]) && nzchar(card$error_message[[1]])) {
        detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong("Error:"), card$error_message[[1]])))
      }

      for (group_name in names(field_groups)) {
        fields <- field_groups[[group_name]]
        populated <- fields[vapply(fields, function(field_name) {
          value <- card[[field_name]][[1]]
          !is.null(value) && !is.na(value) && nzchar(trimws(as.character(value)))
        }, logical(1))]
        if (length(populated) == 0) next

        detail_blocks <- c(detail_blocks, list(shiny::tags$h5(group_name)))
        for (field_name in populated) {
          value <- card[[field_name]][[1]]
          if (field_name == "propagation_text") {
            detail_blocks <- c(detail_blocks, list(shiny::tags$pre(style = "white-space: pre-wrap;", as.character(value))))
          } else if (field_name == "iris_data_entered") {
            detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong(field_name), if (isTRUE(as.logical(value))) "Yes" else "No")))
          } else {
            detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong(field_name), as.character(value))))
          }
        }
      }

      if (!is.null(card$all_accession_numbers[[1]]) && !is.na(card$all_accession_numbers[[1]]) && nzchar(card$all_accession_numbers[[1]])) {
        detail_blocks <- c(detail_blocks, list(shiny::p(shiny::strong("All accession numbers"), card$all_accession_numbers[[1]])))
      }

      for (json_col in c("parsed_table_json", "parsed_other_sowings_json", "parsed_replicate_json")) {
        parsed_df <- safe_json_rows(card[[json_col]][[1]])
        if (!is.null(parsed_df) && nrow(parsed_df) > 0) {
          detail_blocks <- c(detail_blocks, list(shiny::h5(json_col), simple_html_table(parsed_df)))
        }
      }

      time_s <- card$processing_time_s[[1]]
      detail_blocks <- c(detail_blocks, list(
        shiny::h5("Processing"),
        shiny::p(sprintf(
          "Model: %s | DPI: %s | Time: %s",
          card$model[[1]] %||% "-",
          card$dpi[[1]] %||% "-",
          if (!is.null(time_s) && !is.na(time_s)) sprintf("%.1fs", time_s) else "-"
        ))
      ))

      do.call(shiny::tagList, detail_blocks)
    })
  })
}
