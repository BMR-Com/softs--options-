#!/usr/bin/env python3
"""roll_tracker.py — front-month roll and delivery tracker for the softs (data/web/roll.json).

For the contract heading into first notice (sugar: expiry), from the ICE futures reports in data/csv/<T>_FUTURES.csv:
- remaining open interest as % of its level K0 business days before first notice, against the 2005-2026 range for
  the same contract month (data/hist/roll_bands.json: 10th / median / 90th percentile at each day);
- day-by-day open-interest change and volume through the index roll (GSCI 5th-9th, BCOM 6th-10th business day of the
  month before delivery), EFP volume, and the spread to the next contract;
- a plain-language read and a spread idea.
Exchange dates: cotton FND 5 business days before the first business day of the delivery month; coffee 7; cocoa 10;
sugar No.11 has no notice day and expires on the last business day of the month before delivery.
Open interest on an ICE report is the previous business day's figure (dates here are report dates).
"""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "csv"
OUT = ROOT / "data" / "web" / "roll.json"
BANDS = ROOT / "data" / "hist" / "roll_bands.json"
MONS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
CODE = "FGHJKMNQUVXZ"
CYCLE = {"CT": "HKNZ", "KC": "HKNUZ", "SB": "HKNV", "CC": "HKNUZ"}
NOTICE = {"CT": 5, "KC": 7, "CC": 10, "SB": None}
# delivery stopping rules that turn open interest into "how many stoppers": cotton >300 lots needs exchange permission
# 5 business days before first notice; coffee 500 lots max per stopper
STOP = {"CT": (300, "cotton: stopping more than 300 lots needs exchange permission 5 business days before first notice"),
        "KC": (500, "coffee: at most 500 lots per stopper, so a big delivery needs several")}
NAME = {"CT": "Cotton", "KC": "Coffee", "SB": "Sugar No. 11", "CC": "Cocoa"}
UNIT = {"CT": "¢", "KC": "¢", "SB": "¢", "CC": "$"}
LOTSIZE = {"CT": "50,000 lb", "KC": "37,500 lb", "SB": "112,000 lb", "CC": "10 t"}


@lru_cache(maxsize=None)
def holidays(y):
    from pandas.tseries.holiday import USFederalHolidayCalendar, GoodFriday
    cal = USFederalHolidayCalendar()
    hs = {h.date() for h in cal.holidays(f"{y - 1}-12-01", f"{y + 1}-01-31") if not (h.month == 10 or (h.month == 11 and h.day == 11) or (h.month == 11 and h.weekday() == 0 and h.day <= 12))}
    hs |= {d.date() for d in pd.DatetimeIndex(GoodFriday.dates(f"{y}-01-01", f"{y}-12-31"))}
    return frozenset(hs)


def isb(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def shift(d, n):
    step = 1 if n > 0 else -1
    while n:
        d += timedelta(days=step)
        if isb(d):
            n -= step
    return d


def first_bday(y, m):
    d = date(y, m, 1)
    while not isb(d):
        d += timedelta(days=1)
    return d


def t0(sym, y, m):
    if NOTICE[sym]:
        return shift(first_bday(y, m), -NOTICE[sym])
    d = date(y, m, 1) - timedelta(days=1)
    while not isb(d):
        d -= timedelta(days=1)
    return d


def bdays_between(a, b):
    """business days after a up to and including b"""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if isb(d):
            n += 1
    return n


def roll_window(y, m):
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    f = first_bday(py, pm)
    return shift(f, 4), shift(f, 9)          # 5th .. 10th business day of the month before delivery


def opt_exp(sym, y, m):
    """standard options on this future: cotton last Friday with at least 5 business days before FND; coffee and cocoa
    second Friday of the month before delivery; sugar the 15th of the month before (previous business day if not)."""
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    if sym == "CT":
        d = shift(t0(sym, y, m), -6)
        while d.weekday() != 4:
            d -= timedelta(days=1)
        return d
    if sym in ("KC", "CC"):
        d, fr = date(py, pm, 1), 0
        while True:
            if d.weekday() == 4:
                fr += 1
                if fr == 2:
                    return d
            d += timedelta(days=1)
    d = date(py, pm, 15)
    while not isb(d):
        d -= timedelta(days=1)
    return d


def pct_rank(v, lo, mid, hi):
    if v is None or lo is None:
        return None
    if v <= lo:
        return 10.0 * v / lo if lo else 0
    if v <= mid:
        return 10 + 40 * (v - lo) / (mid - lo) if mid > lo else 50
    if v <= hi:
        return 50 + 40 * (v - mid) / (hi - mid) if hi > mid else 50
    return min(99.0, 90 + 10 * (v - hi) / max(hi, 1))


def track(sym, B):
    f = CSV / f"{sym}_FUTURES.csv"
    if not f.exists():
        return None
    u = pd.read_csv(f, parse_dates=["date"]).sort_values("date")
    last = u.date.max().date()
    # contracts in the delivery cycle, nearest notice date ahead (or within its delivery run-in)
    cands = []
    for c in u.contract.unique():
        mon, yy = c[:3], 2000 + int(c[3:])
        mi = MONS.index(mon) + 1
        if CODE[mi - 1] not in CYCLE[sym]:
            continue
        T0 = t0(sym, yy, mi)
        if T0 >= last - timedelta(days=3):
            cands.append((T0, c, yy, mi))
    if not cands:
        return None
    T0, con, y, m = min(cands)
    K0 = B["K0"]
    mk = CODE[m - 1]
    band = B["bands"].get(mk)
    nxt_list = sorted([(t0(sym, 2000 + int(c[3:]), MONS.index(c[:3]) + 1), c) for c in u.contract.unique() if CODE[MONS.index(c[:3])] in CYCLE[sym] and c != con and t0(sym, 2000 + int(c[3:]), MONS.index(c[:3]) + 1) > T0])
    nxt = nxt_list[0][1] if nxt_list else None
    g = u[u.contract == con].set_index("date")
    n2 = u[u.contract == nxt].set_index("date") if nxt else None
    tot = u.groupby("date").open_interest.sum()
    rows = []
    for d, r in g.iterrows():
        k = bdays_between(d.date(), T0) if d.date() <= T0 else -bdays_between(T0, d.date())
        if k > K0 + 5:
            continue
        s2 = n2.settle.get(d) if n2 is not None else None
        rows.append({"date": d.strftime("%Y-%m-%d"), "k": k, "oi": int(r.open_interest) if pd.notna(r.open_interest) else None,
                     "doi": int(r.oi_change) if pd.notna(r.oi_change) else None, "vol": int(r.volume) if pd.notna(r.volume) else None,
                     "efp": int(r.efp) if "efp" in r and pd.notna(r.efp) else None, "settle": float(r.settle),
                     "next_settle": float(s2) if s2 is not None and pd.notna(s2) else None,
                     "spread": round(float(r.settle - s2), 4) if s2 is not None and pd.notna(s2) else None,
                     "next_oi": int(n2.open_interest.get(d)) if n2 is not None and pd.notna(n2.open_interest.get(d)) else None,
                     "share": round(float(r.open_interest / tot.get(d) * 100), 1) if pd.notna(r.open_interest) and tot.get(d) else None})
    if not rows:
        return None
    # base: open interest K0 business days before T0 (from the ICE file, or the Bloomberg value stored for this contract)
    code = f"{mk}{y}"
    base_bb = B.get("base", {}).get(code, {}).get("oi_k0")
    at_k0 = [r for r in rows if r["k"] >= K0]
    base = at_k0[-1]["oi"] if at_k0 and at_k0[-1]["oi"] else base_bb
    base_src = "ICE report" if at_k0 and at_k0[-1]["oi"] else ("Bloomberg history" if base_bb else None)
    if not base:
        base = max(r["oi"] or 0 for r in rows); base_src = "highest OI in the uploaded reports (base day missing)"
    for r in rows:
        r["rem"] = round(r["oi"] / base * 100, 1) if r["oi"] else None
    cur = rows[-1]
    k = cur["k"]
    lo = mid = hi = None
    if band and k in band["k"]:
        i = band["k"].index(k)
        lo, mid, hi = band["p10"][i], band["p50"][i], band["p90"][i]
    pr = pct_rank(cur["rem"], lo, mid, hi)
    llo = lmid = lhi = None
    if band and k in band["k"] and band.get("lots_p50"):
        i = band["k"].index(k)
        llo, lmid, lhi = band["lots_p10"][i], band["lots_p50"][i], band["lots_p90"][i]
    lots_pr = pct_rank(cur["oi"], llo, lmid, lhi)
    w0, w1 = roll_window(y, m)
    in_roll = [r for r in rows if w0 <= pd.Timestamp(r["date"]).date() <= shift(w1, 1)]   # report the day after holds the last roll day's OI
    rolled = -sum(r["doi"] or 0 for r in in_roll)
    k10 = [r for r in rows if r["k"] >= 10]
    spr10 = k10[-1]["spread"] if k10 else None
    lots_left = cur["oi"]
    heavy_pct = pr is not None and pr >= 85
    heavy_lots = lots_pr is not None and lots_pr >= 90
    state = "heavy" if (heavy_pct or heavy_lots) else "light" if pr is not None and pr <= 15 and (lots_pr is None or lots_pr <= 50) else "normal"
    # read
    u_ = UNIT[sym]
    sp = cur["spread"]
    lines = []
    lines.append(f"{NAME[sym]} {MONS[m - 1].title()} {str(y)[2:]}: {('first notice' if NOTICE[sym] else 'expiry')} {T0.isoformat()} ({k} business days after the latest report). "
                 f"Open interest {lots_left:,} lots ({cur['share']:.1f}% of all {NAME[sym].lower()} open interest; it was {rows[0]['share']:.1f}% on {rows[0]['date']}), {cur['rem']:.0f}% of its level {K0} business days before" + (f" (past {MONS[m - 1].title()} contracts at this stage: {lo:.0f}–{hi:.0f}%, median {mid:.0f}%" if mid is not None else "")
                 + (f"; in lots since 2016: {llo:,.0f}–{lhi:,.0f}, median {lmid:,.0f})" if lmid is not None else (")" if mid is not None else "")) + ".")
    ox = opt_exp(sym, y, m)
    after_ox = [r for r in rows if pd.Timestamp(r["date"]).date() > ox]
    after_re = [r for r in rows if pd.Timestamp(r["date"]).date() > shift(w1, 0) + timedelta(days=0) and pd.Timestamp(r["date"]).date() > w1]
    lv = lambda key: band.get(key) if band else None
    if after_re and lv("after_roll_lots"):
        a = lv("after_roll_lots"); v = after_re[0]["oi"]
        lines.append(f"After the index roll ({after_re[0]['date']} report): {v:,} lots still open vs {a['p10']:,.0f}–{a['p90']:,.0f} (median {a['p50']:,.0f}) for past {MONS[m - 1].title()} contracts.")
    if after_ox and lv("after_opt_lots") and ox < T0:
        a = lv("after_opt_lots"); v = after_ox[0]["oi"]
        lines.append(f"After option expiry ({ox.isoformat()}): {v:,} lots vs a past median of {a['p50']:,.0f}.")
    if lv("at_T0_lots"):
        a = lv("at_T0_lots")
        lines.append(f"Typical open interest left at {'first notice' if NOTICE[sym] else 'expiry'} for this month: {a['p50']:,.0f} lots (10th–90th pct {a['p10']:,.0f}–{a['p90']:,.0f}).")
    if sym in STOP and k <= 5:
        n_, txt_ = STOP[sym]
        lines.append(f"In {n_}-lot stopping blocks the {lots_left:,} lots open now are {lots_left / n_:,.0f} blocks ({txt_}).")
    rec = [(c, v.get(str(k))) for c, v in B.get("recent", {}).items() if v.get(str(k)) is not None]
    if rec:
        lines.append("Last contracts at the same stage: " + ", ".join(f"{c[0]}{c[-2:]} {v:.0f}%" for c, v in rec[-5:]) + ".")
    if in_roll:
        lines.append(f"Index-roll window {w0.strftime('%d %b')}–{w1.strftime('%d %b')}: {rolled:,} lots of open interest left the contract in the reports covering it" + ("" if pd.Timestamp(rows[-1]['date']).date() > w1 else " so far") + ".")
    if sp is not None:
        fmt = (lambda v: f"{v:+,.0f} $/t") if sym == "CC" else (lambda v: f"{v:+.2f}¢")
        lines.append(f"Spread to {nxt[:3].title()} {nxt[3:]}: {fmt(sp)} ({'front over next: inverted' if sp > 0 else 'front under next: carry'})" + (f", {fmt(sp - spr10)} since 10 days before {'notice' if NOTICE[sym] else 'expiry'}" if spr10 is not None and k < 10 else "") + ".")
    # price of the next contract through the roll (k20 -> k5), from the desk's daily contract closes
    price_line, cls = None, None
    try:
        import io, requests, math
        mm = {c: i + 1 for i, c in enumerate("FGHJKMNQUVXZ")}
        code_n = f"{sym}{CODE[MONS.index(nxt[:3])]}20{nxt[3:]}"
        cp = pd.read_csv(io.StringIO(requests.get(f"https://raw.githubusercontent.com/BMR-Com/Brazil--trade/main/data/contracts/{sym}.csv", timeout=60).text), parse_dates=["date"])
        cn = cp[cp.contract == code_n].set_index("date").close.sort_index()
        d20 = pd.Timestamp(shift(T0, -20)); d5 = pd.Timestamp(shift(T0, -5))
        a = cn[cn.index <= d20]; b = cn[cn.index <= min(d5, cn.index.max())]
        if len(a) and len(b) and b.index[-1] > a.index[-1]:
            mv = math.log(b.iloc[-1] / a.iloc[-1])
            n_ = len(cn[(cn.index > a.index[-1]) & (cn.index <= b.index[-1])])
            iv = None
            dj = ROOT / "data" / "web" / f"{sym}_desk.json"
            if dj.exists():
                iv = json.loads(dj.read_text()).get("atm")
            z = mv / (iv / 100 * math.sqrt(max(n_, 1) / 252)) if iv else None
            cls = "quiet" if abs(mv) < 0.04 else ("big up" if z is not None and z > 2 else "big down" if z is not None and z < -2 else ("up" if mv > 0 else "down"))
            done = b.index[-1] >= d5
            price_line = (f"{nxt[:3].title()} {nxt[3:]} futures {mv * 100:+.1f}% from 20 to {'5' if done else str(bdays_between(b.index[-1].date(), T0))} business days before {'first notice' if NOTICE[sym] else 'expiry'}"
                          + (f" ({z:+.1f} standard deviations of implied vol)" if z is not None else "") + f": {cls} roll" + ("" if done else " so far") + ".")
            PL = B.get("price_leans", {})
            lean = PL.get(cls.replace("big ", ""))
            if lean:
                price_line += f" History: {lean}."
            ml = PL.get("month", {}).get(mk)
            if ml:
                price_line += f" Season: {ml}."
    except Exception as e:
        print(sym, "price line failed:", e)
    if price_line:
        lines.append(price_line)
    if state == "heavy" and heavy_lots and not heavy_pct:
        lines.append(f"The share of open interest that has left is normal, but the absolute size is not: {lots_left:,} lots is above the 90th percentile of past {MONS[m - 1].title()} contracts at this stage, because the contract started the roll unusually big. More lots have to be rolled, closed or delivered than usual. "
                     "History: big remaining size predicts a bigger delivery; on its own it has not predicted the spread. Squeezes came when size stayed big after the index roll and deliverable stock was short or costly to take (cotton July 2011 held into notice; July 2012 ran from +2.7 to +13.6¢ over the next contract during and just after the index roll and option expiry, then collapsed to flat by notice; July 2022 the same).")
        idea = {"lean": "watch", "text": f"Watch the reports after the index roll: if {MONS[m - 1].title()} still holds far more lots than usual and the spread to {nxt[:3].title()} firms, a pre-notice squeeze (and its collapse into notice) is possible; check deliverable stock. No position until then."}
    elif state == "heavy":
        lines.append("More open interest than usual is still in the front month this close to notice: a larger delivery is likely. History: when this much lingers, the front has more often weakened against the next month into notice than squeezed (longs end up rolling or selling). Squeezes do happen when deliverable stock is short or costly to take: cotton July 2011 held into notice; July 2012 and July 2022 ran up after the index roll and peaked 1–4 days before notice, then collapsed.")
        idea = {"lean": "bear spread", "text": f"Lean to sell {MONS[m - 1].title()}/buy {nxt[:3].title()} into notice unless deliverable stocks are tight; size small and exit by first notice."}
    elif state == "light":
        lines.append("Open interest has left the front faster than usual: deliveries are likely small and shorts have little to deliver against; the front spread has more often held or firmed.")
        idea = {"lean": "bull spread", "text": f"Mild lean to buy {MONS[m - 1].title()}/sell {nxt[:3].title()} into notice; low conviction."}
    else:
        lines.append("The roll is running at a normal pace for this contract month: no delivery or spread signal from open interest.")
        idea = {"lean": "none", "text": "No spread idea from the roll."}
    return {"sym": sym, "name": NAME[sym], "contract": con, "label": f"{MONS[m - 1].title()} {str(y)[2:]}", "next": nxt, "T0": T0.isoformat(),
            "T0_kind": "first notice" if NOTICE[sym] else "expiry", "k": k, "K0": K0, "oi": lots_left, "rem": cur["rem"], "band": {"lo": lo, "mid": mid, "hi": hi},
            "pct": None if pr is None else round(pr), "lots_band": {"lo": llo, "mid": lmid, "hi": lhi}, "lots_pct": None if lots_pr is None else round(lots_pr), "opt_expiry": opt_exp(sym, y, m).isoformat(), "state": state, "base": base, "base_src": base_src, "roll_window": [w0.isoformat(), w1.isoformat()],
            "rolled_in_window": rolled, "spread": sp, "spread_k10": spr10, "share": cur["share"], "path": rows, "band_path": band,
            "roll_price_class": cls, "read": " ".join(lines), "idea": idea, "lot": LOTSIZE[sym], "asof": cur["date"]}


def main():
    B = json.loads(BANDS.read_text()) if BANDS.exists() else {"markets": {}}
    out = {"generated": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"), "markets": {},
           "note": "Remaining front-month open interest vs the same point of past rolls (2005-2026); open interest on ICE reports is the previous business day's."}
    for sym in ("CT", "KC", "SB", "CC"):
        if sym not in B["markets"]:
            continue
        try:
            r = track(sym, {**B["markets"][sym], "price_leans": B.get("price_leans", {}).get(sym, {})})
        except Exception as e:
            print(sym, "roll tracker failed:", e); r = None
        if r and r["k"] <= B["markets"][sym]["K0"] + 5:
            out["markets"][sym] = r
            print(sym, r["label"], "k", r["k"], "rem", r["rem"], "pct", r["pct"], r["state"], "|", r["idea"]["text"])
        else:
            print(sym, "no contract in its roll window")
    OUT.write_text(json.dumps(out, ensure_ascii=False, default=lambda o: None))


if __name__ == "__main__":
    main()
