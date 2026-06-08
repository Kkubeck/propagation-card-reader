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
    shiny::uiOutput(ns("card_detail_ui"))
  )
}

cards_server <- function(id, conn, validation, images_dir = NULL) {
  shiny::moduleServer(id, function(input, output, session) {
    observe({
      current_validation <- validation()
      if (!current_validation$valid) return()
      status <- get_status_summary(conn())
      shiny::updateSelectInput(session, "status_filter", choices = c("All", status$status), selected = "All")
    })

    filtered_total <- shiny::reactive({
      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      get_card_count(conn(), status_filter = input$status_filter, search = input$search_text)
    })

    observe({
      total <- filtered_total()
      per_page <- as.integer(input$per_page)
      max_pages <- max(1L, ceiling(total / per_page))
      current_page <- min(max(1L, as.integer(input$page %||% 1L)), max_pages)
      shiny::updateNumericInput(session, "page", value = current_page, min = 1, max = max_pages)
    })

    cards_df <- shiny::reactive({
      current_validation <- validation()
      shiny::validate(shiny::need(current_validation$valid, current_validation$message))
      per_page <- as.integer(input$per_page)
      current_page <- max(1L, as.integer(input$page %||% 1L))
      offset <- (current_page - 1L) * per_page
      get_extractions_df(conn(), limit = per_page, offset = offset, search = input$search_text, status_filter = input$status_filter)
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

    output$card_detail_ui <- shiny::renderUI({
      row <- selected_card()
      if (is.null(row)) {
        return(shiny::div("Select a row above to see card details."))
      }

      card <- row[1, , drop = FALSE]
      detail_blocks <- list(
        shiny::h4(sprintf("%s - %s", card$botanical_name[[1]] %||% "Unknown", card$accession_number[[1]] %||% "-"))
      )

      img_tag <- NULL
      if (!is.null(images_dir) && !is.null(card$image_path[[1]]) && nzchar(card$image_path[[1]])) {
        img_file <- basename(card$image_path[[1]])
        img_full <- file.path(images_dir, img_file)
        if (file.exists(img_full)) {
          img_tag <- shiny::tags$img(
            src = paste0("card_images/", img_file),
            style = "max-width: 100%; border: 1px solid #ccc; margin-bottom: 1em;"
          )
        }
      }

      if (!is.null(img_tag)) {
        detail_blocks <- c(detail_blocks, list(img_tag))
      }

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
