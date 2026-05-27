"""
download_pdfs.py
One-time script to download NSO strategy PDFs from the NSDS Financing spreadsheet.

Usage:
    python scripts/download_pdfs.py

Reads:  NSDS_Financing_2025_update.xlsx (place in repo root or adjust path below)
Writes: PDFs to raw/, rows to metadata.csv

Requirements:
    pip install openpyxl requests
"""

import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import openpyxl
import requests

# --- Config ---
REPO_ROOT = Path(__file__).resolve().parent.parent
EXCEL_PATH = REPO_ROOT / "NSDS Financing 2025 update.xlsx"
RAW_DIR = REPO_ROOT / "raw"
METADATA_PATH = REPO_ROOT / "metadata.csv"

# Polite delay between downloads (seconds)
DELAY = 2
# Request timeout (seconds)
TIMEOUT = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research corpus builder; contact: your-email@example.com)"
}

METADATA_FIELDS = [
    "file_id", "country_iso3", "country_name", "region", "income_group",
    "year", "year_range", "title", "language", "doc_type", "pages",
    "ocr_needed", "source_url", "accessible", "has_budget", "has_gender_budget",
    "ida_country", "date_added", "notes"
]


# --- Helpers ---

def parse_start_year(year_str):
    """Extract the start year from varied formats like '2015-2025', '2017 - 2027', '2015/16-2035'."""
    if not year_str:
        return None
    year_str = str(year_str).strip()
    # Match the first 4-digit year
    match = re.search(r'(\d{4})', year_str)
    return match.group(1) if match else None


def slugify_name(name, max_len=40):
    """Turn a plan name into a short filesystem-safe slug."""
    if not name:
        return "plan"
    # Lowercase, keep only alphanumeric and spaces
    s = re.sub(r'[^\w\s-]', '', name.lower())
    # Collapse whitespace to underscores
    s = re.sub(r'[\s-]+', '_', s).strip('_')
    # Truncate
    if len(s) > max_len:
        s = s[:max_len].rstrip('_')
    return s or "plan"


def build_file_id(iso3, start_year, name):
    """Construct a unique file_id like 'nga_2024_nsds'."""
    iso = iso3.lower() if iso3 else "xxx"
    yr = start_year or "noyr"
    slug = slugify_name(name)
    return f"{iso}_{yr}_{slug}"


def guess_language(lang_str):
    """Map language names to ISO 639-1 codes."""
    if not lang_str:
        return None
    mapping = {
        "english": "en", "french": "fr", "spanish": "es",
        "portuguese": "pt", "german": "de", "dutch": "nl",
        "arabic": "ar", "russian": "ru", "chinese": "zh",
        "catalan": "ca", "italian": "it", "turkish": "tr",
        "mongolian": "mn", "thai": "th", "vietnamese": "vi",
        "korean": "ko", "japanese": "ja", "malay": "ms",
        "indonesian": "id", "swedish": "sv", "norwegian": "no",
        "danish": "da", "finnish": "fi", "estonian": "et",
        "latvian": "lv", "lithuanian": "lt", "polish": "pl",
        "czech": "cs", "hungarian": "hu", "romanian": "ro",
        "bulgarian": "bg", "serbian": "sr", "croatian": "hr",
        "slovenian": "sl", "slovak": "sk", "greek": "el",
        "hebrew": "he",
    }
    return mapping.get(lang_str.strip().lower(), lang_str.strip().lower()[:2])


def download_file(url, dest_path):
    """Download a file, returning (success, content_type, notes)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=True, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").lower()

        # Check if it's actually a PDF
        is_pdf = (
            "application/pdf" in content_type
            or url.lower().endswith(".pdf")
            or resp.content[:5] == b"%PDF-"
        )

        if not is_pdf:
            # Save it anyway but flag it
            dest_path = dest_path.with_suffix(".html")
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return False, content_type, f"Not a PDF (content-type: {content_type}). Saved as .html for inspection."

        with open(dest_path, "wb") as f:
            f.write(resp.content)

        # Sanity check: file should be > 1KB
        size = dest_path.stat().st_size
        if size < 1024:
            return False, content_type, f"File suspiciously small ({size} bytes)"

        return True, content_type, None

    except requests.exceptions.Timeout:
        return False, None, "Timeout"
    except requests.exceptions.HTTPError as e:
        return False, None, f"HTTP {e.response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, None, "Connection error"
    except Exception as e:
        return False, None, str(e)


# --- Main ---

def read_main_sheet(wb):
    """Read the WORKING VERSION sheet and return list of document dicts."""
    ws = wb["WORKING VERSION"]
    docs = []

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        country = row[0]
        iso3 = row[1]
        ida = row[2]
        name = row[3]
        years = row[4]
        url = row[5]
        accessible = row[10]
        language = row[11]
        has_budget = row[12]
        has_gender_budget = row[13]

        # Skip rows without URLs
        if not url or not str(url).startswith("http"):
            continue

        # Skip inaccessible docs
        if str(accessible).strip().lower() == "no":
            continue

        # Skip entries marked "Not available"
        if name and "not available" in str(name).lower():
            continue

        start_year = parse_start_year(years)
        file_id = build_file_id(iso3, start_year, name)

        docs.append({
            "file_id": file_id,
            "country_iso3": iso3,
            "country_name": country,
            "region": None,
            "income_group": None,
            "year": start_year,
            "year_range": str(years) if years else None,
            "title": name,
            "language": guess_language(language) if language else None,
            "doc_type": "nsds",
            "pages": None,
            "ocr_needed": None,
            "source_url": str(url).strip(),
            "accessible": str(accessible) if accessible else None,
            "has_budget": str(has_budget) if has_budget else None,
            "has_gender_budget": str(has_gender_budget) if has_gender_budget else None,
            "ida_country": bool(ida),
            "date_added": None,
            "notes": None,
            "sheet": "main",
        })

    return docs


def read_gender_sheet(wb):
    """Read the Gender Statistics plans sheet."""
    ws = wb["Gender Statistics plans"]
    docs = []

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        country = row[0]
        iso3 = row[1]
        url = row[2]

        if not url or not str(url).startswith("http"):
            continue

        file_id = f"{iso3.lower()}_gender_stats_plan"

        docs.append({
            "file_id": file_id,
            "country_iso3": iso3,
            "country_name": country,
            "region": None,
            "income_group": None,
            "year": None,
            "year_range": None,
            "title": f"{country} Gender Statistics Plan",
            "language": None,
            "doc_type": "gender_stats_plan",
            "pages": None,
            "ocr_needed": None,
            "source_url": str(url).strip(),
            "accessible": None,
            "has_budget": None,
            "has_gender_budget": None,
            "ida_country": None,
            "date_added": None,
            "notes": None,
            "sheet": "gender",
        })

    return docs


def enrich_with_ida(wb, docs):
    """Add region and income_group from the IDA country list sheet."""
    ws = wb["IDA country list"]
    lookup = {}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        code = row[1]
        if code:
            lookup[code] = {"region": row[2], "income_group": row[3]}

    for doc in docs:
        info = lookup.get(doc["country_iso3"], {})
        doc["region"] = doc["region"] or info.get("region")
        doc["income_group"] = doc["income_group"] or info.get("income_group")

    return docs


def deduplicate(docs):
    """If multiple rows share a file_id, append a suffix."""
    seen = {}
    for doc in docs:
        fid = doc["file_id"]
        if fid in seen:
            seen[fid] += 1
            doc["file_id"] = f"{fid}_{seen[fid]}"
        else:
            seen[fid] = 0
    return docs


def main():
    if not EXCEL_PATH.exists():
        print(f"ERROR: Excel file not found at {EXCEL_PATH}")
        print(f"Place the file in the repo root or edit EXCEL_PATH in this script.")
        sys.exit(1)

    RAW_DIR.mkdir(exist_ok=True)

    print(f"Reading {EXCEL_PATH.name}...")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)

    docs = read_main_sheet(wb)
    gender_docs = read_gender_sheet(wb)
    all_docs = docs + gender_docs
    all_docs = enrich_with_ida(wb, all_docs)
    all_docs = deduplicate(all_docs)

    print(f"Found {len(all_docs)} documents to download ({len(docs)} main + {len(gender_docs)} gender)\n")

    # Download
    from datetime import date
    today = date.today().isoformat()

    results = {"ok": 0, "not_pdf": 0, "failed": 0, "skipped": 0}

    for i, doc in enumerate(all_docs, 1):
        fid = doc["file_id"]
        dest = RAW_DIR / f"{fid}.pdf"

        # Skip if already downloaded
        if dest.exists():
            print(f"  [{i}/{len(all_docs)}] SKIP (exists): {fid}")
            results["skipped"] += 1
            doc["date_added"] = doc["date_added"] or today
            continue

        print(f"  [{i}/{len(all_docs)}] Downloading: {fid}")
        print(f"    URL: {doc['source_url'][:80]}...")

        success, content_type, note = download_file(doc["source_url"], dest)
        doc["date_added"] = today

        if success:
            size_kb = dest.stat().st_size / 1024
            print(f"    OK ({size_kb:.0f} KB)")
            results["ok"] += 1
        elif note and "Not a PDF" in note:
            print(f"    WARNING: {note}")
            doc["notes"] = note
            results["not_pdf"] += 1
        else:
            print(f"    FAILED: {note}")
            doc["notes"] = f"Download failed: {note}"
            results["failed"] += 1

        time.sleep(DELAY)

    # Write metadata.csv
    print(f"\nWriting metadata to {METADATA_PATH}...")
    with open(METADATA_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for doc in all_docs:
            writer.writerow(doc)

    print(f"\n{'='*50}")
    print(f"DONE")
    print(f"  Downloaded:  {results['ok']}")
    print(f"  Skipped:     {results['skipped']} (already exist)")
    print(f"  Not PDF:     {results['not_pdf']} (saved as .html for inspection)")
    print(f"  Failed:      {results['failed']}")
    print(f"  Total docs:  {len(all_docs)}")
    print(f"\nNext steps:")
    print(f"  1. Check raw/ for any .html files — these may be landing pages, not PDFs.")
    print(f"     You may need to manually find the direct PDF link.")
    print(f"  2. Review metadata.csv and fill in any missing language codes.")
    print(f"  3. Run scripts/01_extract_text.R to extract text from the PDFs.")


if __name__ == "__main__":
    main()
