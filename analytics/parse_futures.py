#!/usr/bin/env python3
"""
parse_futures.py — archive ICE futures Daily Market Reports (<T>_YYYY_MM_DD-2.pdf) to data/csv/<T>_FUTURES.csv:
one row per date and contract with settle, change, volume, open interest and OI change.
(ICE notes that OI on a report is the previous business day's figure.)
"""
import re, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdfs"
CSV = ROOT / "data" / "csv"
MON = {"Jan": "JAN", "Feb": "FEB", "Mar": "MAR", "Apr": "APR", "May": "MAY", "Jun": "JUN", "Jul": "JUL", "Aug": "AUG", "Sep": "SEP", "Oct": "OCT", "Nov": "NOV", "Dec": "DEC"}


def num(t):
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def parse(path, T):
    import pdfplumber
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})-2\.pdf$", path.name)
    if not m:
        return []
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    rows = []
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    for line in text.split("\n"):
        tk = line.strip().split()
        if len(tk) < 4 or tk[0] != T or not re.match(r"^[A-Z][a-z]{2}-\d{2}$", tk[1]):
            continue
        mon, yy = tk[1].split("-")
        n = [num(x) for x in tk[2:]]
        if any(v is None for v in n):
            continue
        if len(n) >= 13:      # traded: open high low close settle chg vol oi oichg block efp efs spread
            settle, chg, vol, oi, oic = n[4], n[5], n[6], n[7], n[8]
        elif len(n) >= 9:     # untraded: settle chg vol oi oichg block efp efs spread
            settle, chg, vol, oi, oic = n[0], n[1], n[2], n[3], n[4]
        else:
            continue
        rows.append({"date": date, "contract": f"{MON[mon]}{yy}", "settle": settle, "change": chg, "volume": int(vol), "open_interest": int(oi), "oi_change": int(oic)})
    return rows


def main():
    for T in ("CT", "KC", "SB"):
        out = CSV / f"{T}_FUTURES.csv"
        old = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=["date", "contract"])
        have = set(old.date.astype(str)) if len(old) else set()
        new = []
        for f in sorted(PDF.glob(f"{T}_*-2.pdf")):
            r = parse(f, T)
            if r and r[0]["date"] not in have:
                new += r
        if new:
            df = pd.concat([old, pd.DataFrame(new)], ignore_index=True)
            df = df.drop_duplicates(["date", "contract"], keep="last").sort_values(["date", "contract"])
            df.to_csv(out, index=False)
        print(f"{T}: +{len({r['date'] for r in new})} days -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
