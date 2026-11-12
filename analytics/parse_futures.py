#!/usr/bin/env python3
"""
parse_futures.py — archive ICE futures Daily Market Reports to data/csv/<T>_FUTURES.csv: one row per date and
contract with every column of the report: open, high, low, close (first/last trade), settle, change, volume,
open interest, OI change, block, EFP, EFS and spread volume.
The report is recognised by its content ("Futures Daily Market Report"), so re-uploads with any file suffix work;
for a date with several uploads the largest file is used and replaces earlier rows for that date.
ICE notes that open interest on a report is the previous business day's figure.
Run before options_csv_archiver_single.py --delete-processed (which removes the PDFs).
"""
import re, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdfs"
CSV = ROOT / "data" / "csv"
MON = {"Jan": "JAN", "Feb": "FEB", "Mar": "MAR", "Apr": "APR", "May": "MAY", "Jun": "JUN", "Jul": "JUL", "Aug": "AUG", "Sep": "SEP", "Oct": "OCT", "Nov": "NOV", "Dec": "DEC"}
COLS = ["date", "contract", "open", "high", "low", "close", "settle", "change", "volume", "open_interest", "oi_change", "block", "efp", "efs", "spread_volume"]


def text_of(path):
    try:
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def num(t):
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def report_date(text):
    m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text[:400])
    if not m:
        return None
    mm = list(MON).index(m.group(2).title()) + 1
    return f"{m.group(3)}-{mm:02d}-{int(m.group(1)):02d}"


def parse(text, T):
    date = report_date(text)
    rows = []
    for line in text.split("\n"):
        tk = line.strip().split()
        if len(tk) < 4 or tk[0] != T or not re.match(r"^[A-Z][a-z]{2}-\d{2}$", tk[1]):
            continue
        mon, yy = tk[1].split("-")
        n = [num(x) for x in tk[2:]]
        if any(v is None for v in n):
            continue
        r = {"date": date, "contract": f"{MON[mon]}{yy}"}
        if len(n) >= 13:      # traded: open high low close settle chg vol oi oichg block efp efs spread
            r.update(zip(["open", "high", "low", "close", "settle", "change", "volume", "open_interest", "oi_change", "block", "efp", "efs", "spread_volume"], n[:13]))
        elif len(n) == 9:     # untraded: settle chg vol oi oichg block efp efs spread
            r.update(zip(["settle", "change", "volume", "open_interest", "oi_change", "block", "efp", "efs", "spread_volume"], n))
        elif len(n) == 8:     # untraded with no OI change printed
            r.update(zip(["settle", "change", "volume", "open_interest", "block", "efp", "efs", "spread_volume"], n))
        else:
            continue
        rows.append(r)
    return date, rows


def main():
    for T in ("CT", "KC", "SB", "CC"):
        out = CSV / f"{T}_FUTURES.csv"
        old = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=COLS)
        best = {}
        for f in sorted(PDF.glob(f"{T}_*.pdf")):
            if f.stat().st_size < 1000:
                continue
            t = text_of(f)
            if "Futures Daily Market Report" not in t[:300]:
                continue
            d, rows = parse(t, T)
            if d and rows and (d not in best or f.stat().st_size > best[d][0]):
                best[d] = (f.stat().st_size, rows)
        new = [r for _, rows in best.values() for r in rows]
        if new:
            nd = pd.DataFrame(new)
            df = pd.concat([old[~old.date.astype(str).isin(nd.date.unique())], nd], ignore_index=True)
            df = df.reindex(columns=COLS).sort_values(["date", "contract"])
            for c in ["volume", "open_interest", "oi_change", "block", "efp", "efs", "spread_volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
            df.to_csv(out, index=False)
        print(f"{T}: {len(best)} report days parsed -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
