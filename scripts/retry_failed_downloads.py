"""
retry_failed_downloads.py
Re-attempt the failed downloads listed in raw/_inbox/failed_downloads.csv using a
realistic browser User-Agent and session headers. Many of the original failures
were 403/timeout/connection errors caused by bot-blocking, not dead links.

Saves successful PDFs to raw/{file_id}.pdf and writes a results CSV to
raw/_inbox/retry_results.csv so a second pass can web-search whatever still fails.
"""
import csv
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "raw"
INBOX = RAW / "_inbox"
FAILED = INBOX / "failed_downloads.csv"
RESULTS = INBOX / "retry_results.csv"

TIMEOUT = 45
DELAY = 1.5

# Realistic desktop Chrome headers
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def looks_like_pdf(resp, url):
    ct = resp.headers.get("Content-Type", "").lower()
    if "application/pdf" in ct:
        return True
    if resp.content[:5] == b"%PDF-":
        return True
    if url.lower().split("?")[0].endswith(".pdf") and resp.content[:5] == b"%PDF-":
        return True
    return False


def attempt(url):
    """Return (status, note, content-or-None)."""
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        # Set a Referer to the URL's own origin — some servers require it
        from urllib.parse import urlparse
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
        sess.headers["Referer"] = origin
        resp = sess.get(url, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        if looks_like_pdf(resp, resp.url):
            if len(resp.content) < 1024:
                return "fail", f"PDF too small ({len(resp.content)} bytes)", None
            return "ok", f"{len(resp.content)//1024} KB; final={resp.url}", resp.content
        ct = resp.headers.get("Content-Type", "")
        return "notpdf", f"Not a PDF (content-type: {ct}); final={resp.url}", None
    except requests.exceptions.Timeout:
        return "fail", "Timeout", None
    except requests.exceptions.HTTPError as e:
        return "fail", f"HTTP {e.response.status_code}", None
    except requests.exceptions.ConnectionError as e:
        return "fail", f"Connection error: {str(e)[:80]}", None
    except Exception as e:
        return "fail", f"{type(e).__name__}: {str(e)[:80]}", None


def main():
    rows = list(csv.DictReader(FAILED.open(encoding="utf-8")))
    results = []
    ok = notpdf = fail = 0
    for i, r in enumerate(rows, 1):
        fid = r["file_id"]
        url = r["source_url"]
        dest = RAW / f"{fid}.pdf"
        if dest.exists():
            print(f"[{i}/{len(rows)}] SKIP exists: {fid}")
            results.append({**r, "result": "already_have", "note": ""})
            continue
        status, note, content = attempt(url)
        if status == "ok":
            dest.write_bytes(content)
            ok += 1
            print(f"[{i}/{len(rows)}] OK   {fid}  ({note})")
        elif status == "notpdf":
            notpdf += 1
            print(f"[{i}/{len(rows)}] HTML {fid}  ({note})")
        else:
            fail += 1
            print(f"[{i}/{len(rows)}] FAIL {fid}  ({note})")
        results.append({**r, "result": status, "note": note})
        time.sleep(DELAY)

    with RESULTS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + ["result", "note"])
        w.writeheader()
        w.writerows(results)

    print(f"\n=== Retry summary ===")
    print(f"  OK (PDF saved): {ok}")
    print(f"  Not a PDF (landing/HTML): {notpdf}")
    print(f"  Still failing:  {fail}")
    print(f"  Results written to {RESULTS}")


if __name__ == "__main__":
    main()
