#!/usr/bin/env python3
"""
fetch_staged.py: collect ICE settlement PDFs uploaded through the softs desk drop box.

The desk (public repo BMR-Com/Brazil--trade) identifies each uploaded report and keeps a renamed copy in
data/ice_staging/pdfs/ (<T>_YYYY_MM_DD.pdf options, <T>_YYYY_MM_DD-2.pdf futures), listed in
data/ice_staging/manifest.json. This downloads every staged report whose date is not yet in data/csv
(options: <T>_MASTER.csv, futures: <T>_FUTURES.csv) into data/pdfs/, unless the same file is already there.
For an options date not yet ingested the futures report of that date is fetched too (the archiver needs the pair).
Writes new=<count> to $GITHUB_OUTPUT. Standard library only, so it runs before the dependencies are installed.
"""
import csv, hashlib, json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF, CSV = ROOT / "data" / "pdfs", ROOT / "data" / "csv"
SRC = "https://raw.githubusercontent.com/BMR-Com/Brazil--trade/main/"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "softs-options-archive", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def dates(path):
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {r[0] for r in csv.reader(f) if r and r[0][:2] == "20"}


def main():
    try:
        files = json.loads(get(SRC + "data/ice_staging/manifest.json"))["files"]   # raw files are cached up to 5 minutes
    except Exception as e:
        print(f"no drop-box manifest ({e}); nothing to collect")
        files = []
    have = {}
    by_key = {(f["sym"], f["date"], f["kind"]): f for f in files}
    want = []
    for f in files:
        T, d, k = f["sym"], f["date"], f["kind"]
        if T not in ("CT", "KC", "SB", "CC"):
            continue
        if (T, "options") not in have:
            have[(T, "options")], have[(T, "futures")] = dates(CSV / f"{T}_MASTER.csv"), dates(CSV / f"{T}_FUTURES.csv")
        if d in have[(T, k)]:
            continue
        want.append(f)
        if k == "options" and (T, d, "futures") in by_key:
            want.append(by_key[(T, d, "futures")])
    new = 0
    PDF.mkdir(parents=True, exist_ok=True)
    for f in {x["file"]: x for x in want}.values():
        dst = PDF / f["file"]
        if dst.exists() and hashlib.sha256(dst.read_bytes()).hexdigest() == f["sha256"]:
            continue
        try:
            b = get(SRC + f["path"])
        except Exception as e:
            print(f"::warning::could not download staged {f['file']}: {e}")
            continue
        if b[:5] != b"%PDF-" or hashlib.sha256(b).hexdigest() != f["sha256"]:
            print(f"::warning::staged {f['file']} did not match its manifest entry; skipped (will retry next run)")
            continue
        dst.write_bytes(b)
        new += 1
        print(f"collected {f['file']} ({f['sym']} {f['kind']} {f['date']}) from the drop box")
    print(f"drop box: {len(files)} staged, {new} new for this archive")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"new={new}\n")


if __name__ == "__main__":
    sys.exit(main())
