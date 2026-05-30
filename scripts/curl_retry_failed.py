"""
curl_retry_failed.py
Second-pass downloader for entries that the requests-based retry could not fetch.

Python's urllib3/requests TLS ClientHello is blocked by some anti-bot front ends
(Cloudflare/Akamai), which return "Connection error: Max retries exceeded" even
though the URL is perfectly live. curl uses a different TLS stack and sails through.

Reads raw/_inbox/retry_results.csv, takes rows with result == 'fail', and re-tries
each URL with curl. Validates the %PDF magic bytes before keeping the file.
Rewrites retry_results.csv in place with updated result/note columns.
"""
import csv
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "raw"
INBOX = RAW / "_inbox"
RESULTS = INBOX / "retry_results.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def curl_download(url, dest):
    """Try to fetch url -> dest with curl. Return (ok, note)."""
    tmp = dest.with_suffix(".part")
    cmd = [
        "curl", "-sS", "-L", "--max-time", "90",
        "--retry", "2", "--retry-delay", "2",
        "-A", UA,
        "-H", "Accept: application/pdf,text/html,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-e", url,  # self-referer
        "-o", str(tmp), "-w", "%{http_code} %{content_type}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        if tmp.exists():
            tmp.unlink()
        return False, "curl timeout"
    meta = (proc.stdout or "").strip()
    if not tmp.exists() or tmp.stat().st_size == 0:
        return False, f"empty ({meta or proc.stderr.strip()[:80]})"
    head = tmp.read_bytes()[:5]
    size = tmp.stat().st_size
    if head == b"%PDF-":
        if size < 1024:
            tmp.unlink()
            return False, f"PDF too small ({size} bytes)"
        tmp.replace(dest)
        return True, f"{size//1024} KB; {meta}"
    # Not a PDF — keep nothing, report content type
    snippet = tmp.read_bytes()[:200].decode("latin-1", "replace").replace("\n", " ")
    tmp.unlink()
    return False, f"not PDF ({meta}); head={snippet[:60]}"


def main():
    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8")))
    fieldnames = list(rows[0].keys())
    ok = still = 0
    for r in rows:
        if r.get("result") != "fail":
            continue
        fid = r["file_id"]
        url = r["source_url"]
        dest = RAW / f"{fid}.pdf"
        success, note = curl_download(url, dest)
        if success:
            ok += 1
            r["result"] = "ok"
            r["note"] = "curl: " + note
            print(f"OK   {fid}  ({note})")
        else:
            still += 1
            r["note"] = (r.get("note", "") + " | curl: " + note).strip(" |")
            print(f"FAIL {fid}  ({note})")

    with RESULTS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\n=== curl retry summary ===")
    print(f"  Newly recovered: {ok}")
    print(f"  Still failing:   {still}")


if __name__ == "__main__":
    main()
