# 01_extract_text.R
# Extract plain text from PDFs in raw/, saving to text/
# Uses pdftools for native text; falls back to tesseract OCR when needed

library(pdftools)
library(tesseract)
library(readr)
library(dplyr)
library(stringr)

# --- Config ---
raw_dir <- here::here("raw")
text_dir <- here::here("text")
metadata_path <- here::here("metadata.csv")

# Minimum characters per page to consider text "present" (not scanned)
min_chars_per_page <- 50

# --- Load metadata ---
meta <- read_csv(metadata_path, show_col_types = FALSE)

if (nrow(meta) == 0) {
  stop("metadata.csv is empty. Add document entries before running extraction.")
}

# --- Helper: extract text from a single PDF ---
extract_one <- function(file_id, raw_dir, text_dir, min_chars_per_page) {
  pdf_path <- file.path(raw_dir, paste0(file_id, ".pdf"))
  txt_path <- file.path(text_dir, paste0(file_id, ".txt"))

  if (!file.exists(pdf_path)) {
    message("  SKIP (file not found): ", pdf_path)
    return(tibble(file_id = file_id, ocr_needed = NA, pages = NA, status = "missing"))
  }

  # Try native text extraction first
  text <- tryCatch(pdf_text(pdf_path), error = function(e) NULL)

  if (is.null(text)) {
    message("  ERROR reading: ", pdf_path)
    return(tibble(file_id = file_id, ocr_needed = NA, pages = NA, status = "error"))
  }

  n_pages <- length(text)
  chars_per_page <- nchar(text)
  needs_ocr <- median(chars_per_page) < min_chars_per_page

  if (needs_ocr) {
    message("  OCR needed for: ", file_id)
    # OCR each page via tesseract
    text <- tryCatch({
      imgs <- pdf_convert(pdf_path, dpi = 300)
      ocr_text <- sapply(imgs, ocr)
      # Clean up temp image files
      file.remove(imgs)
      ocr_text
    }, error = function(e) {
      message("  OCR FAILED for: ", file_id, " — ", e$message)
      return(text)  # fall back to whatever pdftools got
    })
  }

  # Collapse pages, normalize whitespace
  full_text <- paste(text, collapse = "\n\n--- PAGE BREAK ---\n\n")
  full_text <- str_replace_all(full_text, "\r", "")

  write_file(full_text, txt_path)
  message("  OK: ", file_id, " (", n_pages, " pp, OCR=", needs_ocr, ")")

  tibble(file_id = file_id, ocr_needed = needs_ocr, pages = n_pages, status = "ok")
}

# --- Run extraction ---
message("Extracting text from ", nrow(meta), " documents...\n")

results <- purrr::map_dfr(meta$file_id, extract_one,
                           raw_dir = raw_dir,
                           text_dir = text_dir,
                           min_chars_per_page = min_chars_per_page)

# --- Update metadata with extraction results ---
meta <- meta |>
  left_join(results |> select(file_id, ocr_needed_detected = ocr_needed, pages_detected = pages),
            by = "file_id") |>
  mutate(
    ocr_needed = coalesce(ocr_needed, ocr_needed_detected),
    pages = coalesce(pages, pages_detected)
  ) |>
  select(-ocr_needed_detected, -pages_detected)

write_csv(meta, metadata_path)

# --- Summary ---
message("\n--- Summary ---")
message("Total: ", nrow(results))
message("OK: ", sum(results$status == "ok"))
message("Missing: ", sum(results$status == "missing"))
message("Errors: ", sum(results$status == "error"))
message("OCR applied: ", sum(results$ocr_needed, na.rm = TRUE))
