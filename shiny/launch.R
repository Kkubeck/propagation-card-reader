# Auto-install missing packages and launch the Propagation Card Viewer
# Just run this file — it handles everything.

required <- c("shiny", "DBI", "RSQLite", "DT", "dplyr",
              "stringr", "fs", "bslib", "jsonlite")
optional <- c("pdftools", "base64enc")

missing_req <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
missing_opt <- optional[!vapply(optional, requireNamespace, logical(1), quietly = TRUE)]

if (length(missing_req) > 0) {
  message("Installing required packages: ", paste(missing_req, collapse = ", "))
  install.packages(missing_req, repos = "https://cloud.r-project.org")
}

if (length(missing_opt) > 0) {
  message("Installing image packages: ", paste(missing_opt, collapse = ", "))
  tryCatch(
    install.packages(missing_opt, repos = "https://cloud.r-project.org"),
    error = function(e) message("Note: card images won't display without pdftools. App still works for data.")
  )
}

shiny::runApp(".", launch.browser = TRUE)
