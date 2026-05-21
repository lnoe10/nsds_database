# NSO Strategy Corpus

A structured corpus of ~100 national statistical office (NSO) strategy documents (NSDSs, strategic plans, and related frameworks) for text analysis.

## Repository structure

```
nso-strategy-corpus/
├── raw/              # Original downloaded PDFs, untouched
│   └── archive/      # Superseded strategies (moved here when replaced)
├── text/             # Extracted plain text (one .txt per document)
├── translated/       # English translations of non-EN documents
├── scripts/
│   ├── download_pdfs.py      # One-time bulk download from Excel source list
│   ├── 01_extract_text.R
│   ├── 02_translate.R
│   └── 03_build_corpus.R
├── corpus/           # Analysis-ready outputs (quanteda corpus, DTM)
├── metadata.csv      # Document-level metadata (the spine of the corpus)
└── .gitattributes    # Git LFS tracking rules for PDFs
```

## Pipeline

0. **Download** (one-time): Place `NSDS_Financing_2025_update.xlsx` in the repo root, then run `python scripts/download_pdfs.py`. This downloads all accessible PDFs into `raw/` and populates `metadata.csv`.
1. **Collect** (ongoing): When new strategies are published, download them manually into `raw/` and add a row to `metadata.csv`. Move superseded documents to `raw/archive/`.
2. **Extract**: Run `scripts/01_extract_text.R` to convert PDFs to plain text in `text/`. OCR is applied automatically where needed.
3. **Translate**: Run `scripts/02_translate.R` to produce English translations in `translated/` for non-English documents.
4. **Build corpus**: Run `scripts/03_build_corpus.R` to assemble a `quanteda` corpus object with document-level metadata, saved to `corpus/`.

## Metadata fields

| Field              | Description                                      |
|--------------------|--------------------------------------------------|
| `file_id`          | Unique identifier: `{iso3}_{year}_{slug}`        |
| `country_iso3`     | ISO 3166-1 alpha-3 country code                  |
| `country_name`     | Country name (English)                            |
| `region`           | UN/WB regional grouping (from IDA list)           |
| `income_group`     | World Bank income classification (from IDA list)  |
| `year`             | Start year of plan coverage                       |
| `year_range`       | Full coverage period as written (e.g. 2015-2025)  |
| `title`            | Document title (original language)                |
| `language`         | ISO 639-1 language code (en, fr, es, etc.)        |
| `doc_type`         | Document type (nsds, gender_stats_plan, other)    |
| `pages`            | Page count (filled by extraction script)          |
| `ocr_needed`       | Whether OCR was required (filled by extraction)   |
| `source_url`       | URL where the document was downloaded             |
| `accessible`       | Whether the URL was accessible at download time   |
| `has_budget`       | Detailed budget available (from source Excel)     |
| `has_gender_budget`| Gender data mentioned in budget (from source)     |
| `ida_country`      | Whether the country is IDA-eligible               |
| `date_added`       | Date added to the corpus (YYYY-MM-DD)             |
| `notes`            | Free-text notes (download issues, etc.)           |

## Naming convention

Files follow the pattern `{iso3}_{year}_{doctype}`:
- `nga_2024_nsds.pdf` → Nigeria's 2024 NSDS
- `sen_2022_snds.pdf` → Senegal's 2022 SNDS
- `col_2023_plan.pdf` → Colombia's 2023 strategic plan

The same base name is used across `raw/`, `text/`, and `translated/` (with `_en` suffix for translations).

## Requirements

- Python ≥ 3.8 with `openpyxl`, `requests` (for the download script)
- R ≥ 4.0
- R packages: `pdftools`, `tesseract`, `quanteda`, `readr`, `dplyr`, `stringr`, `here`, `purrr`
- For translation: API access (e.g., DeepL, Google Translate, or Claude)

## Notes

- Raw PDFs are tracked with Git LFS. Run `git lfs install` before cloning.
- The `translated/` folder contains machine translations for analytical convenience. Always verify findings against the original-language text in `text/`.
