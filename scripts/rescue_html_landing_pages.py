"""
rescue_html_landing_pages.py
For each .html file in raw/, try to find the actual PDF link and download it.

Strategy:
  1. Parse the HTML and collect candidate PDF URLs (anchor hrefs, iframe srcs,
     embed srcs, JS viewer ?file= params, meta refresh, og:url).
  2. Score candidates by filename/keyword heuristics, resolve relative URLs
     against the original source URL from metadata.csv.
  3. Try candidates in rank order; on the first PDF that downloads cleanly,
     replace the .html with the .pdf and update metadata.csv.

Manual cases (no embedded PDF link found) are listed at the end for review.
"""

import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from html.parser import HTMLParser

# Force UTF-8 stdout so non-ASCII anchor text doesn't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "raw"
METADATA_PATH = REPO_ROOT / "metadata.csv"

DELAY = 2
TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (research corpus builder; contact: lorenznoe@gmail.com)"
}


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []            # (url, anchor_text)
        self.iframes = []          # iframe/embed src
        self.meta_refresh = None
        self.og_url = None
        self._a_open = False
        self._a_href = None
        self._a_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._a_open = True
            self._a_href = a["href"]
            self._a_text = []
        elif tag in ("iframe", "embed") and a.get("src"):
            self.iframes.append(a["src"])
        elif tag == "meta":
            if (a.get("http-equiv") or "").lower() == "refresh" and a.get("content"):
                m = re.search(r"url=([^;]+)", a["content"], re.I)
                if m:
                    self.meta_refresh = m.group(1).strip().strip("'\"")
            if a.get("property") == "og:url" and a.get("content"):
                self.og_url = a["content"]

    def handle_endtag(self, tag):
        if tag == "a" and self._a_open:
            self.links.append((self._a_href, " ".join(self._a_text).strip()))
            self._a_open = False
            self._a_href = None
            self._a_text = []

    def handle_data(self, data):
        if self._a_open:
            self._a_text.append(data.strip())


DOC_TYPE_KEYWORDS = re.compile(
    r"(strateg|plan|nsds|snds|programme|program|programa|"
    r"corporate|departmental|estrateg|development|nsdgs|"
    r"sds|pen|pei|sndgs|ende|sndd|sdnss)",
    re.I,
)

NOISE = re.compile(
    r"(privacy|terms|contact|cookie|login|signup|guidelines|"
    r"newsletter|brochure|leaflet|template|form|annex|appendix|"
    r"survey-report|monthly|quarterly|annual-report|workshop)",
    re.I,
)

STOPWORDS = {
    "the", "of", "for", "and", "a", "an", "in", "on", "to", "by",
    "de", "del", "la", "le", "les", "el", "des", "du", "et", "en",
    "noyr", "plan", "national",  # too generic on their own
}


def file_id_tokens(file_id: str) -> set:
    """Extract meaningful tokens from a file_id, e.g. 'btn_2024_national_strategy_for_the_development_of' -> {'btn','2024','strategy','development'}."""
    parts = re.split(r"[_\-]+", file_id.lower())
    return {p for p in parts if p and p not in STOPWORDS and len(p) > 2}


def title_tokens(title: str) -> set:
    if not title:
        return set()
    parts = re.split(r"[\s_\-/]+", title.lower())
    return {re.sub(r"[^a-z0-9]", "", p) for p in parts if p and p not in STOPWORDS and len(p) > 2}


def is_pdf_url(url: str) -> bool:
    """Treat as a PDF candidate if URL ends in .pdf or has a ?file=...pdf query."""
    u = url.lower()
    if u.endswith(".pdf"):
        return True
    if ".pdf?" in u or ".pdf#" in u:
        return True
    # PDF.js viewers: ...viewer.html?file=...pdf
    if "file=" in u and ".pdf" in u:
        return True
    return False


def score_candidate(url: str, anchor: str, want_tokens: set) -> int:
    """Higher = better. want_tokens is the set of meaningful file_id+title tokens we want to see in the URL or anchor."""
    score = 0
    u = url.lower()
    a = (anchor or "").lower()

    if u.endswith(".pdf"):
        score += 10
    if "file=" in u and ".pdf" in u:
        score += 8

    # Generic doc-type vocabulary
    if DOC_TYPE_KEYWORDS.search(url):
        score += 2
    if DOC_TYPE_KEYWORDS.search(a):
        score += 2

    # Strong signal: tokens from the expected file_id / title appearing in URL or anchor
    hay = u + " " + a
    matched = sum(1 for tok in want_tokens if tok in hay)
    score += 5 * matched

    # Noise penalty
    if NOISE.search(u) or NOISE.search(a):
        score -= 8

    return score


def extract_candidates(html_path: Path, base_url: str, want_tokens: set):
    """Return ranked list of (candidate_url, anchor_text)."""
    text = html_path.read_text(encoding="utf-8", errors="replace")
    p = LinkExtractor()
    try:
        p.feed(text)
    except Exception:
        pass

    cands = []

    # Anchors
    for href, anchor in p.links:
        if is_pdf_url(href):
            absolute = urljoin(base_url, href)
            # If it's a viewer ?file=..., unwrap to the underlying PDF
            parsed = urlparse(absolute)
            qs = parse_qs(parsed.query)
            if "file" in qs and ".pdf" in qs["file"][0].lower():
                inner = unquote(qs["file"][0])
                cands.append((urljoin(base_url, inner), anchor or "(viewer file=)"))
            cands.append((absolute, anchor))

    # iframes/embeds
    for src in p.iframes:
        absolute = urljoin(base_url, src)
        if is_pdf_url(absolute):
            parsed = urlparse(absolute)
            qs = parse_qs(parsed.query)
            if "file" in qs and ".pdf" in qs["file"][0].lower():
                inner = unquote(qs["file"][0])
                cands.append((urljoin(base_url, inner), "(iframe file=)"))
            cands.append((absolute, "(iframe)"))

    # meta refresh + og:url, only if .pdf
    for u in (p.meta_refresh, p.og_url):
        if u and is_pdf_url(u):
            cands.append((urljoin(base_url, u), "(meta/og)"))

    # Also scrape raw text for naked .pdf URLs we may have missed
    for m in re.finditer(r'https?://[^\s"\'<>]+\.pdf', text, re.I):
        cands.append((m.group(0), "(regex)"))

    # Deduplicate, keep highest-scoring instance per URL
    best = {}
    for url, anchor in cands:
        s = score_candidate(url, anchor, want_tokens)
        if url not in best or s > best[url][0]:
            best[url] = (s, anchor)

    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    return [(url, anchor, score) for url, (score, anchor) in ranked]


def download(url: str, dest: Path):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                         allow_redirects=True, stream=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").lower()
        is_pdf = (
            "application/pdf" in ct
            or url.lower().split("?")[0].endswith(".pdf")
            or r.content[:5] == b"%PDF-"
        )
        if not is_pdf:
            return False, f"not-PDF (Content-Type: {ct})"
        dest.write_bytes(r.content)
        size = dest.stat().st_size
        if size < 1024:
            dest.unlink(missing_ok=True)
            return False, f"too-small ({size} bytes)"
        return True, f"{size // 1024} KB"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP {e.response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, "Connection error"
    except Exception as e:
        return False, str(e)


def load_metadata():
    rows = []
    with open(METADATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    return fieldnames, rows


def save_metadata(fieldnames, rows):
    with open(METADATA_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    html_files = sorted(RAW_DIR.glob("*.html"))
    if not html_files:
        print("No .html files in raw/ — nothing to do.")
        return

    fieldnames, rows = load_metadata()
    by_id = {r["file_id"]: r for r in rows}

    rescued, manual, failed = [], [], []

    for i, html in enumerate(html_files, 1):
        file_id = html.stem
        row = by_id.get(file_id)
        if not row:
            print(f"[{i}/{len(html_files)}] {file_id}: no metadata row, skipping")
            continue
        base_url = row.get("source_url") or ""
        print(f"\n[{i}/{len(html_files)}] {file_id}")
        print(f"  source: {base_url[:90]}")

        want = file_id_tokens(file_id) | title_tokens(row.get("title") or "")
        cands = extract_candidates(html, base_url, want)
        if not cands:
            print("  -> no PDF candidates found in HTML")
            manual.append(file_id)
            continue

        # Reject candidates whose score is non-positive (likely noise / unrelated PDFs)
        viable = [c for c in cands if c[2] > 0]
        if not viable:
            top_score = cands[0][2]
            print(f"  -> {len(cands)} candidates but all noisy (best score {top_score}); manual review")
            manual.append(file_id)
            continue

        # Try up to top 4 candidates
        success = False
        for url, anchor, score in viable[:4]:
            anchor_safe = anchor.encode("ascii", "replace").decode("ascii")
            print(f"  try (score {score}): {url[:90]}  [{anchor_safe[:30]}]")
            dest = RAW_DIR / f"{file_id}.pdf"
            ok, note = download(url, dest)
            if ok:
                print(f"    OK ({note})")
                html.unlink()
                row["source_url"] = url
                row["notes"] = (row.get("notes") or "")
                extra = f"PDF rescued from landing page via {url[:80]}"
                row["notes"] = extra if not row["notes"] else row["notes"] + "; " + extra
                rescued.append(file_id)
                success = True
                break
            else:
                print(f"    fail: {note}")
            time.sleep(DELAY)

        if not success:
            failed.append(file_id)

    save_metadata(fieldnames, rows)

    print("\n" + "=" * 50)
    print(f"Rescued (PDF now in raw/): {len(rescued)}")
    for fid in rescued:
        print(f"  + {fid}")
    print(f"\nNo candidates found (need manual review): {len(manual)}")
    for fid in manual:
        print(f"  ? {fid}")
    print(f"\nCandidates exhausted (no working PDF): {len(failed)}")
    for fid in failed:
        print(f"  - {fid}")


if __name__ == "__main__":
    main()
