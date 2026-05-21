# 02_translate.R
# Translate non-English extracted texts to English
# Placeholder — choose your translation backend below

library(readr)
library(dplyr)
library(stringr)

# --- Config ---
text_dir <- here::here("text")
translated_dir <- here::here("translated")
metadata_path <- here::here("metadata.csv")

meta <- read_csv(metadata_path, show_col_types = FALSE)

# Filter to non-English documents that have extracted text
to_translate <- meta |>
  filter(language != "en") |>
  filter(file.exists(file.path(text_dir, paste0(file_id, ".txt"))))

message(nrow(to_translate), " documents to translate\n")

# --- Translation function (stub) ---
# Replace this with your preferred translation API:
#   - DeepL API (free tier: 500k chars/month)
#   - Google Cloud Translation (free tier available)
#   - Claude API (good for preserving document structure)
#
# Example structure:
# translate_text <- function(text, source_lang, target_lang = "en") {
#   # Call your API here
#   # Return translated text
# }

# --- Run translations ---
for (i in seq_len(nrow(to_translate))) {
  row <- to_translate[i, ]
  txt_path <- file.path(text_dir, paste0(row$file_id, ".txt"))
  out_path <- file.path(translated_dir, paste0(row$file_id, "_en.txt"))

  if (file.exists(out_path)) {
    message("  SKIP (already translated): ", row$file_id)
    next
  }

  message("  TODO: ", row$file_id, " (", row$language, ")")
  # text <- read_file(txt_path)
  # translated <- translate_text(text, source_lang = row$language)
  # write_file(translated, out_path)
}
