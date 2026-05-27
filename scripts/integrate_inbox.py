"""
integrate_inbox.py
Process PDFs in raw/_inbox/ into the curated corpus.

For each PDF, infers the ISO3 code from the filename prefix, finds the matching
metadata row(s) (preferring file_ids whose .html stub still exists in raw/),
moves the PDF to raw/{file_id}.pdf, deletes the .html stub, and updates
metadata.csv (source_url, notes, date_added, and year/year_range when the
filename clearly indicates a newer edition).

Inbox layout:
  raw/_inbox/{ISO3}_{slug}_{year}_{year}.pdf   (or _noyr)
  raw/_inbox/inbox_source_urls.txt             (CSV: country, iso3, url)
"""
import csv
import re
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
INBOX = REPO_ROOT / "raw" / "_inbox"
RAW = REPO_ROOT / "raw"
METADATA = REPO_ROOT / "metadata.csv"
URL_TXT = INBOX / "inbox_source_urls.txt"

# ISO3 aliases for non-standard prefixes a user might use
ALIAS = {"DEN": "DNK"}  # extend as needed


def parse_urls():
    """Return {ISO3: url} from inbox_source_urls.txt."""
    out = {}
    if not URL_TXT.exists():
        return out
    for line in URL_TXT.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().lower().startswith("country"):
            continue
        parts = [p.strip() for p in line.split(",", 2)]
        if len(parts) >= 3 and parts[1]:
            iso = parts[1].upper()
            out[ALIAS.get(iso, iso)] = parts[2]
    return out


def parse_years_from_filename(stem):
    """Return (start_year, year_range_str) inferred from the inbox filename, or (None, None)."""
    # Match the last cluster of year-like tokens (handles 2025_2026, 2022_23_2026_27, 2023, etc.)
    yrs = re.findall(r"(20\d{2})", stem)
    if not yrs:
        return None, None
    start = yrs[0]
    end = yrs[-1] if len(yrs) > 1 and yrs[-1] != yrs[0] else None
    rng = f"{start}-{end}" if end else start
    return start, rng


def main():
    pdfs = sorted([p for p in INBOX.glob("*.pdf")])
    if not pdfs:
        print("No PDFs in raw/_inbox/ — nothing to do.")
        return

    urls = parse_urls()

    # Load metadata
    with open(METADATA, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fieldnames = rdr.fieldnames
        rows = list(rdr)
    rows_by_iso = {}
    for r in rows:
        rows_by_iso.setdefault(r["country_iso3"].upper(), []).append(r)

    # Pre-index existing stubs so we prefer matching file_ids that still have an .html
    html_stems = {p.stem for p in RAW.glob("*.html")}

    today = date.today().isoformat()
    integrated, ambiguous, unmatched, year_changes = [], [], [], []

    for pdf in pdfs:
        stem = pdf.stem
        m = re.match(r"^([A-Z]{3})[_\-]", stem)
        if not m:
            unmatched.append((pdf.name, "filename does not start with ISO3 prefix"))
            continue
        iso = ALIAS.get(m.group(1), m.group(1))
        candidates = rows_by_iso.get(iso, [])
        if not candidates:
            unmatched.append((pdf.name, f"no metadata row for ISO3 {iso}"))
            continue

        # Prefer rows whose .html stub still exists in raw/
        stub_candidates = [r for r in candidates if r["file_id"] in html_stems]
        if not stub_candidates:
            # Fall back to all rows for this country
            stub_candidates = candidates

        # Disambiguate: GHA has two rows that point to the same source URL — assign to both.
        # Otherwise if there are still multiple, try a slug-token match.
        targets = stub_candidates
        if len(stub_candidates) > 1:
            slug = stem[4:].lower()
            # If any candidate file_id token cluster matches the slug strongly, prefer it
            scored = []
            for r in stub_candidates:
                fid_tokens = set(re.split(r"_", r["file_id"].lower()))
                hits = sum(1 for t in re.split(r"[_\-]+", slug) if t in fid_tokens and len(t) > 2)
                scored.append((hits, r))
            scored.sort(key=lambda x: -x[0])
            top = scored[0][0]
            # If two or more candidates share the same source_url, integrate to all of them.
            url_groups = {}
            for _, r in scored:
                url_groups.setdefault(r.get("source_url"), []).append(r)
            if len(url_groups) == 1:
                targets = [r for _, r in scored]  # all share a URL → all
            elif scored[0][0] > 0 and (len(scored) == 1 or scored[1][0] < top):
                targets = [scored[0][1]]
            else:
                ambiguous.append((pdf.name, [r["file_id"] for _, r in scored]))
                continue

        # Year inference from filename
        new_start, new_range = parse_years_from_filename(stem)

        new_url = urls.get(iso)

        for tgt in targets:
            fid = tgt["file_id"]
            dest_pdf = RAW / f"{fid}.pdf"
            stub_html = RAW / f"{fid}.html"

            # Copy (not move) so a single inbox PDF can satisfy multiple file_ids (e.g. GHA)
            shutil.copyfile(pdf, dest_pdf)
            if stub_html.exists():
                stub_html.unlink()

            # Update metadata fields
            old_start = tgt.get("year")
            old_range = tgt.get("year_range")

            if new_url:
                tgt["source_url"] = new_url
            tgt["date_added"] = today

            # Strip any prior "Not a PDF" or "Download failed" note
            note = tgt.get("notes") or ""
            note = re.sub(r"Not a PDF[^;]*;?\s*", "", note).strip()
            note = re.sub(r"PDF rescued from landing page[^;]*;?\s*", "", note).strip()
            note = re.sub(r"rescue attempt found wrong document[^;]*;?\s*", "", note).strip()
            note = re.sub(r"Download failed[^;]*;?\s*", "", note).strip()
            note = note.strip(" ;")

            year_change_note = None
            if new_start and old_start and new_start != old_start:
                year_change_note = f"PDF is {new_range} (metadata had {old_range}); replaced older edition"
                tgt["year"] = new_start
                tgt["year_range"] = new_range
                year_changes.append((fid, old_range, new_range))
            elif new_range and not old_range:
                tgt["year"] = new_start
                tgt["year_range"] = new_range

            if year_change_note:
                note = (note + "; " + year_change_note).strip("; ").strip()

            tgt["notes"] = note
            integrated.append((pdf.name, fid))

        # Remove the inbox file after successful integration
        pdf.unlink()

    # Persist
    with open(METADATA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Optionally remove urls.txt if all inbox PDFs were consumed
    remaining = list(INBOX.glob("*.pdf"))
    if not remaining and URL_TXT.exists():
        URL_TXT.unlink()
        # Remove the empty _inbox folder
        try:
            INBOX.rmdir()
        except OSError:
            pass

    # Report
    print(f"\n=== Integrated ({len(integrated)}) ===")
    for src, fid in integrated:
        print(f"  {src}  ->  {fid}.pdf")

    if year_changes:
        print(f"\n=== Year/range updated (newer edition than source spreadsheet) ({len(year_changes)}) ===")
        for fid, old, new in year_changes:
            print(f"  {fid}: {old}  ->  {new}")

    if ambiguous:
        print(f"\n=== Ambiguous, skipped ({len(ambiguous)}) ===")
        for src, opts in ambiguous:
            print(f"  {src}  -> candidates: {opts}")

    if unmatched:
        print(f"\n=== Unmatched, skipped ({len(unmatched)}) ===")
        for src, why in unmatched:
            print(f"  {src}: {why}")


if __name__ == "__main__":
    main()
