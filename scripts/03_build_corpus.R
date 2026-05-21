# 03_build_corpus.R
# Assemble extracted (and translated) texts into a quanteda corpus
# with document-level metadata for filtering and analysis

library(quanteda)
library(readr)
library(dplyr)
library(stringr)

# --- Config ---
text_dir <- here::here("text")
translated_dir <- here::here("translated")
corpus_dir <- here::here("corpus")
metadata_path <- here::here("metadata.csv")

meta <- read_csv(metadata_path, show_col_types = FALSE)

# --- Load texts ---
# For English docs: use text/ directly
# For non-English docs: prefer translated/ version if available, else use original
load_text <- function(file_id, language) {
  # Check for English translation first (for non-EN docs)
  if (language != "en") {
    translated_path <- file.path(translated_dir, paste0(file_id, "_en.txt"))
    if (file.exists(translated_path)) {
      return(read_file(translated_path))
    }
  }

  # Fall back to original extracted text
  txt_path <- file.path(text_dir, paste0(file_id, ".txt"))
  if (file.exists(txt_path)) {
    return(read_file(txt_path))
  }

  return(NA_character_)
}

meta <- meta |>
  rowwise() |>
  mutate(text = load_text(file_id, language)) |>
  ungroup()

# Filter to documents with text
available <- meta |> filter(!is.na(text))
message(nrow(available), " of ", nrow(meta), " documents loaded\n")

# --- Build quanteda corpus ---
corp <- corpus(available, text_field = "text", docid_field = "file_id")

message("Corpus summary:")
print(summary(corp, n = 5))

# --- Save ---
saveRDS(corp, file.path(corpus_dir, "corpus.rds"))
message("\nCorpus saved to corpus/corpus.rds")

# --- Optional: build and save a document-feature matrix ---
# Useful as a starting point for keyword analysis, tf-idf, etc.
dfmat <- corp |>
  tokens(remove_punct = TRUE, remove_numbers = TRUE) |>
  tokens_remove(stopwords("en")) |>
  tokens_tolower() |>
  dfm()

saveRDS(dfmat, file.path(corpus_dir, "dfm.rds"))
message("DFM saved to corpus/dfm.rds")
message("Features: ", nfeat(dfmat), " | Documents: ", ndoc(dfmat))
