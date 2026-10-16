#!/usr/bin/env python3
"""
build_desk.py — daily options "vol desk" for ICE softs (CT, KC, SB).

Reads the ICE settlement archive (data/csv/<T>_MASTER.csv) plus public BMR-Com price data and writes
data/web/<T>_desk.json for the Vol Desk tab: implied vol level, term structure and smile, skew,
put/call positioning, open-interest walls, gamma by strike, expected moves, and a written read.
"""
import io, json, math, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "csv"
OUT = ROOT / "data" / "web"
RAW = "https://raw.githubusercontent.com/BMR-Com"
LOCAL = os.getenv("DESK_LOCAL")
WINDOW_DAYS = 9          # latest report plus the prior week (calendar days), so week-on-week comparisons have a base           # optional folder with local clones
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
LABEL = {"CT": "Cotton No.2", "KC": "Coffee C", "SB": "Sugar No.11"}
UNIT = {"CT": "¢/lb", "KC": "¢/lb", "SB": "¢/lb"}
MULT = {"CT": 50000, "KC": 37500, "SB": 112000}     # lbs per contract
# main option months per market (serials map to these futures)
MAIN = {"CT": ("MAR", "MAY", "JUL", "DEC"), "KC": ("MAR", "MAY", "JUL", "SEP", "DEC"), "SB": ("MAR", "MAY", "JUL", "OCT")}


def remote(path, local_rel):
    if LOCAL and (Path(LOCAL) / local_rel).exists():
        return (Path(LOCAL) / local_rel).read_bytes()
    import requests
    r = requests.get(f"{RAW}/{path}", timeout=180); r.raise_for_status(); return r.content


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def b76_gamma(F, K, T, s):
    """Black-76 gamma per 1¢ move in the futures (per contract unit)."""
    if T <= 0 or s <= 0 or F <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * s * s * T) / (s * math.sqrt(T))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (F * s * math.sqrt(T))


def ordn(x):
    n = int(round(x)); return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def exp_label(e):
    return e[:1] + e[1:3].lower() + " " + e[3:]


# ─────────────────────────── per-expiry measures ───────────────────────────
def smile(g):
    """OTM smile for one expiry on one day: calls at/above F, puts below F."""
    F = float(g.futures_price.iloc[0])
    c = g[(g.call_put == "C") & (g.strike >= F)]; p = g[(g.call_put == "P") & (g.strike < F)]
    s = pd.concat([p, c]).dropna(subset=["implied_vol_pct"])
    s = s[(s.implied_vol_pct > 2) & (s.implied_vol_pct < 150)].sort_values("strike")
    return F, s


def atm_iv(g):
    F, s = smile(g)
    if len(s) < 2:
        return None
    return float(np.interp(F, s.strike, s.implied_vol_pct))


def delta_iv(g, side, target=0.25):
    x = g[(g.call_put == side)].dropna(subset=["delta", "implied_vol_pct"]).copy()
    x["ad"] = x.delta.abs()
    x = x[(x.ad > 0.03) & (x.ad < 0.97) & (x.implied_vol_pct > 2)].sort_values("ad")
    if len(x) < 2 or not (x.ad.min() <= target <= x.ad.max()):
        return None
    return float(np.interp(target, x.ad, x.implied_vol_pct))


def max_pain(g):
    ks = sorted(g.strike.unique())
    c = g[g.call_put == "C"].groupby("strike").open_interest.sum(); p = g[g.call_put == "P"].groupby("strike").open_interest.sum()
    best, bk = None, None
    for K in ks:
        pay = sum(max(0, K - k) * oi for k, oi in c.items()) + sum(max(0, k - K) * oi for k, oi in p.items())
        if best is None or pay < best:
            best, bk = pay, K
    return bk


def main_expiries(day, T):
    """Main (non-serial) option months, nearest first, with at least 7 days to expiry."""
    ex = day.groupby("expiry").agg(dte=("dte", "first"), oi=("open_interest", "sum")).reset_index()
    ex = ex[(ex.expiry.str[:3].isin(MAIN[T])) & (ex.dte >= 7)].sort_values("dte")
    return list(ex.expiry)


# ─────────────────────────── history helpers ───────────────────────────
def yahoo(T):
    """Front-month futures from the COT site's contract-labelled price file; returns are taken within one contract only."""
    try:
        raw = remote("cftc-cot-full/main/data/prices/front_contract.csv", "cftc-cot-full/data/prices/front_contract.csv")
        p = pd.read_csv(io.BytesIO(raw), parse_dates=["date"])
        p = p[p.ticker == T].set_index("date").sort_index()[["contract", "close", "high", "low"]].dropna()
        same = p.contract.eq(p.contract.shift(1))
        p["lr"] = np.where(same, np.log(p.close / p.close.shift(1)), np.nan)
        return p
    except Exception as ex:
        print("price history unavailable:", ex); return None


def bloomberg_iv_ct():
    """Front-month cotton implied vol history (Bloomberg HIST_CALL_IMP_VOL), 2000 onward — Mar/May/Jul/Dec only."""
    try:
        raw = remote("cotton-price/main/data/cotton_raw.csv", "bmr-com/cotton-price/data/cotton_raw.csv")
        d = pd.read_csv(io.BytesIO(raw), low_memory=False, na_values=["#N/A N/A"])
        d["Dates"] = pd.to_datetime(d.Dates, format="mixed"); d = d.set_index("Dates").sort_index()
        def front(m):
            return "MAR" if m in (11, 12, 1) else "MAY" if m in (2, 3) else "JUL" if m in (4, 5) else "DEC"
        iv = pd.Series([d.at[i, f"CT{front(i.month)}1 Comdty HIST_CALL_IMP_VOL"] for i in d.index], index=d.index, dtype=float)
        return iv[(iv > 3) & (iv < 120)].dropna()
    except Exception as ex:
        print("Bloomberg IV history unavailable:", ex); return None


# ─────────────────────────── build ───────────────────────────
def build(T, px, ivhist):
    f = CSV / f"{T}_MASTER.csv"
    if not f.exists():
        return None
    m = pd.read_csv(f)
    m["date"] = pd.to_datetime(m.date)
    fu = pd.read_csv(CSV / f"{T}_FUTURES.csv", parse_dates=["date"]) if (CSV / f"{T}_FUTURES.csv").exists() else None
    m = m[m.strike.notna()]
    # drop incomplete reports (e.g. the short "traded strikes only" DMR): far fewer rows / OI than the days around them
    daily = m.groupby("date").agg(rows=("strike", "size"), oi=("open_interest", "sum")).sort_index()
    ref = daily.rolling(5, min_periods=1).median().shift(1)
    ok = daily[(daily.rows >= 0.6 * ref.rows.fillna(daily.rows)) & (daily.oi >= 0.6 * ref.oi.fillna(daily.oi))].index
    skipped = [d.strftime("%Y-%m-%d") for d in daily.index if d not in ok]
    m = m[m.date.isin(ok)]
    # use only the most recent week of reports (older archive stretches are not comparable)
    if len(m):
        m = m[m.date >= m.date.max() - pd.Timedelta(days=WINDOW_DAYS)]
    dates = sorted(m.date.unique())
    if len(dates) < 2:
        return None

    # history (one row per complete report day): front main month measures + market-wide positioning
    hist = []
    for dt in dates:
        day = m[m.date == dt]
        ex = main_expiries(day, T)
        if not ex:
            continue
        fe = ex[0]; g = day[day.expiry == fe]
        F = float(g.futures_price.iloc[0]); a = atm_iv(g)
        c25, p25 = delta_iv(g, "C"), delta_iv(g, "P")
        cOI, pOI = day[day.call_put == "C"].open_interest.sum(), day[day.call_put == "P"].open_interest.sum()
        cV, pV = day[day.call_put == "C"].volume.sum(), day[day.call_put == "P"].volume.sum()
        hist.append({"date": dt, "front": fe, "F": F, "atm": a, "c25": c25, "p25": p25,
                     "rr25": (c25 - p25) if c25 is not None and p25 is not None else None,
                     "bf25": ((c25 + p25) / 2 - a) if None not in (c25, p25, a) else None,
                     "cOI": int(cOI), "pOI": int(pOI), "cVol": int(cV), "pVol": int(pV),
                     "cOIchg": int(day[day.call_put == "C"].oi_change.sum()), "pOIchg": int(day[day.call_put == "P"].oi_change.sum())})
    H = pd.DataFrame(hist).set_index("date")
    if H.empty:
        return None
    H["pc_oi"] = H.pOI / H.cOI.replace(0, np.nan)
    last = H.index[-1]
    day = m[m.date == last]
    ex = main_expiries(day, T)
    fe = ex[0]; se = ex[1] if len(ex) > 1 else None
    g = day[day.expiry == fe]; F = float(g.futures_price.iloc[0]); dte = int(g.dte.iloc[0])

    def back(n_cal):
        """Report day closest to n calendar days before the latest (within the archive)."""
        tgt = last - pd.Timedelta(days=n_cal)
        cand = [d for d in H.index if d <= tgt]
        return cand[-1] if cand and (tgt - cand[-1]).days <= 4 else None
    d1 = H.index[-2] if len(H) > 1 else None
    w1 = back(7)

    # realized vol & price moves from the futures (Yahoo front month)
    rv20 = rv60 = r5 = r1 = None; ret_series = None
    if px is not None and len(px) > 70:
        p = px[px.index <= last]
        lr = p.lr.dropna()                                # within-contract returns (roll days excluded)
        rv20 = float(lr.tail(20).std() * math.sqrt(252) * 100); rv60 = float(lr.tail(60).std() * math.sqrt(252) * 100)
        r5 = float(lr.tail(5).sum()); r1 = float(lr.tail(1).sum())
        rvs = lr.rolling(20).std() * math.sqrt(252) * 100
        ret_series = rvs

    a = H.atm.iloc[-1]
    # implied-vol percentile: cotton uses the Bloomberg history (2000+) joined to the ICE archive
    pct1y = pct5y = None; ivlong = None
    if ivhist is not None and a is not None:
        s = pd.concat([ivhist[ivhist.index < H.index[0]], H.atm.dropna()])
        s1 = s[s.index > last - pd.Timedelta(days=365)]; s5 = s[s.index > last - pd.Timedelta(days=5 * 365)]
        pct1y = float((s1 < a).mean() * 100) if len(s1) > 100 else None
        pct5y = float((s5 < a).mean() * 100) if len(s5) > 200 else None
        wk = s.resample("W-FRI").last().dropna()
        wk = wk[wk.index > last - pd.Timedelta(days=5 * 365)]
        ivlong = []
        prev_d = None
        for d, v in wk.items():
            if prev_d is not None and (d - prev_d).days > 21:
                ivlong.append([(prev_d + pd.Timedelta(days=7)).strftime("%Y-%m-%d"), None])   # break the line over data gaps
            ivlong.append([d.strftime("%Y-%m-%d"), round(float(v), 2)]); prev_d = d
    elif a is not None:
        pct1y = None          # no long implied-vol history for this market
    pct_lbl = "of the past year" if ivhist is not None else "no long history"

    # term structure & smiles (today and ~1 week ago)
    def term(dt):
        dd = m[m.date == dt]; out = []
        for e in sorted(dd.expiry.unique(), key=lambda e: int(dd[dd.expiry == e].dte.iloc[0])):
            gg = dd[dd.expiry == e]
            if int(gg.dte.iloc[0]) < 7:
                continue
            v = atm_iv(gg)
            if v is not None:
                out.append({"exp": e, "label": exp_label(e), "dte": int(gg.dte.iloc[0]), "atm": round(v, 2), "F": float(gg.futures_price.iloc[0])})
        return out
    def smile_pts(dt, e):
        gg = m[(m.date == dt) & (m.expiry == e)]
        if gg.empty:
            return []
        F_, s = smile(gg)
        s = s[(s.strike > F_ * 0.75) & (s.strike < F_ * 1.3)]
        return [[float(k), round(float(v), 2)] for k, v in zip(s.strike, s.implied_vol_pct)]

    # strike map for the two main expiries
    def strike_map(e):
        gg = day[day.expiry == e]
        if gg.empty:
            return None
        Fe = float(gg.futures_price.iloc[0]); Te = max(int(gg.dte.iloc[0]), 1) / 365
        rows = []
        for K, kk in gg.groupby("strike"):
            c = kk[kk.call_put == "C"]; p = kk[kk.call_put == "P"]
            cOI = int(c.open_interest.sum()); pOI = int(p.open_interest.sum())
            iv = kk.implied_vol_pct.dropna().mean()
            gam = b76_gamma(Fe, float(K), Te, (iv or 25) / 100)
            rows.append({"K": float(K), "cOI": cOI, "pOI": pOI, "cChg": int(c.oi_change.sum()), "pChg": int(p.oi_change.sum()),
                         "cVol": int(c.volume.sum()), "pVol": int(p.volume.sum()),
                         # futures-equivalent lots that change per 1¢ move: gamma × open interest (calls and puts, gross)
                         "cGam": round(gam * cOI, 1), "pGam": round(gam * pOI, 1)})
        R = pd.DataFrame(rows).sort_values("K")
        R = R[(R.K > Fe * 0.7) & (R.K < Fe * 1.35)]
        above = R[R.K >= Fe]; below = R[R.K <= Fe]
        cw = float(above.loc[above.cOI.idxmax(), "K"]) if len(above) and above.cOI.max() > 0 else None
        pw = float(below.loc[below.pOI.idxmax(), "K"]) if len(below) and below.pOI.max() > 0 else None
        gk = float(R.loc[(R.cGam + R.pGam).idxmax(), "K"]) if len(R) else None
        return {"exp": e, "label": exp_label(e), "F": Fe, "dte": int(gg.dte.iloc[0]), "call_wall": cw, "put_wall": pw,
                "max_pain": max_pain(gg), "gamma_peak": gk, "rows": R.to_dict("records"),
                "cOI": int(gg[gg.call_put == "C"].open_interest.sum()), "pOI": int(gg[gg.call_put == "P"].open_interest.sum())}
    maps = [x for x in (strike_map(fe), strike_map(se) if se else None) if x]

    # ── per-expiry weekly table: futures, spreads, vol, skew, option flow, walls ──
    def fut_at(dt, con):
        if fu is None or dt is None:
            return None
        x = fu[(fu.date == dt) & (fu.contract == con)]
        return x.iloc[0] if len(x) else None
    def contract_rv(con):
        if fu is None:
            return None, 0
        x = fu[(fu.contract == con) & (fu.date <= last) & (fu.date >= last - pd.Timedelta(days=45))].sort_values("date")
        x = x[x.settle > 0]
        gap = x.date.diff().dt.days
        lr = np.log(x.settle / x.settle.shift(1))[(gap <= 4)]
        lr = lr.tail(20)
        return (float(lr.std() * math.sqrt(252) * 100), len(lr)) if len(lr) >= 5 else (None, len(lr))
    exp_rows = []
    wk_day = m[m.date == w1] if w1 is not None else None
    wk_window = m[(m.date > w1) & (m.date <= last)] if w1 is not None else m[m.date == last]
    uf_order = sorted({(int(day[day.expiry == e].dte.iloc[0]), day[day.expiry == e].underlying_fut.iloc[0]) for e in ex})
    ufs = [u for _, u in uf_order]
    for e in ex[:4]:
        g0 = day[day.expiry == e]; uf = g0.underlying_fut.iloc[0]
        tot_oi = int(g0.open_interest.sum())
        if tot_oi < 1000:
            continue
        r = {"exp": e, "label": exp_label(e), "fut": uf, "dte": int(g0.dte.iloc[0])}
        fn, fw = fut_at(last, uf), fut_at(w1, uf)
        r["F"] = float(fn.settle) if fn is not None else float(g0.futures_price.iloc[0])
        r["dF"] = float(fn.settle - fw.settle) if fn is not None and fw is not None else None
        r["dFpct"] = r["dF"] / float(fw.settle) if r["dF"] is not None and fw.settle else None
        r["futOI"] = int(fn.open_interest) if fn is not None else None
        r["dFutOI"] = int(fn.open_interest - fw.open_interest) if fn is not None and fw is not None else None
        nxt = ufs[ufs.index(uf) + 1] if uf in ufs and ufs.index(uf) + 1 < len(ufs) else None
        if nxt:
            a1, b1, a0, b0 = fut_at(last, uf), fut_at(last, nxt), fut_at(w1, uf), fut_at(w1, nxt)
            if a1 is not None and b1 is not None:
                r["spread_vs"] = exp_label(nxt); r["spread"] = float(a1.settle - b1.settle)
                r["dSpread"] = float((a1.settle - b1.settle) - (a0.settle - b0.settle)) if a0 is not None and b0 is not None else None
        a_now = atm_iv(g0); gw = wk_day[wk_day.expiry == e] if wk_day is not None else None
        a_wk = atm_iv(gw) if gw is not None and len(gw) else None
        c25, p25 = delta_iv(g0, "C"), delta_iv(g0, "P")
        rr_now = c25 - p25 if c25 is not None and p25 is not None else None
        rr_wk = None
        if gw is not None and len(gw):
            c0, p0 = delta_iv(gw, "C"), delta_iv(gw, "P"); rr_wk = c0 - p0 if c0 is not None and p0 is not None else None
        r.update({"atm": a_now, "dIV": (a_now - a_wk) if a_now is not None and a_wk is not None else None,
                  "rr25": rr_now, "dRR": (rr_now - rr_wk) if rr_now is not None and rr_wk is not None else None})
        rv, nrv = contract_rv(uf)
        if rv is None or nrv < 15:          # too few daily settlements in the recent window: use the front contract's 20-day realized vol
            rv = rv20; r["rv_src"] = "front 20d"
        r["rv"] = rv; r["rv_n"] = nrv
        r["vrp"] = (a_now - rv) if a_now is not None and rv is not None else None
        cO, pO = int(g0[g0.call_put == "C"].open_interest.sum()), int(g0[g0.call_put == "P"].open_interest.sum())
        cO0 = int(gw[gw.call_put == "C"].open_interest.sum()) if gw is not None and len(gw) else None
        pO0 = int(gw[gw.call_put == "P"].open_interest.sum()) if gw is not None and len(gw) else None
        ww = wk_window[wk_window.expiry == e]
        r.update({"cOI": cO, "pOI": pO, "dcOI": (cO - cO0) if cO0 is not None else None, "dpOI": (pO - pO0) if pO0 is not None else None,
                  "cVolWk": int(ww[ww.call_put == "C"].volume.sum()), "pVolWk": int(ww[ww.call_put == "P"].volume.sum())})
        sm_ = strike_map(e)
        if sm_:
            r.update({"call_wall": sm_["call_wall"], "put_wall": sm_["put_wall"], "gamma_peak": sm_["gamma_peak"], "max_pain": sm_["max_pain"]})
        if a_now is not None:
            r["em_exp"] = r["F"] * a_now / 100 * math.sqrt(max(r["dte"], 1) / 365)
        # futures positioning read
        if r.get("dF") is not None and r.get("dFutOI") is not None:
            up, oiu = r["dF"] > 0, r["dFutOI"] > 0
            r["fut_read"] = ("new buying" if up and oiu else "short covering" if up else "new selling" if oiu else "long liquidation")
        # option flow read for the week
        sc, why = 0, []
        dc, dp = r.get("dcOI"), r.get("dpOI")
        if dc is not None and dp is not None:
            if dc > 0 and dc > max(dp, 0) * 1.2:
                sc += 1; why.append(f"call OI +{dc:,}")
            if dp > 0 and dp > max(dc, 0) * 1.2:
                sc -= 1; why.append(f"put OI +{dp:,}")
            if dp < 0 and (r.get("dFpct") or 0) > 0.005:
                sc += 0.5; why.append("puts closed into the rally")
            if dc < 0 and (r.get("dFpct") or 0) < -0.005:
                sc -= 0.5; why.append("calls closed into the decline")
        if r.get("dRR") is not None:
            if r["dRR"] > 0.7:
                sc += 1; why.append(f"skew to calls {r['dRR']:+.1f}")
            elif r["dRR"] < -0.7:
                sc -= 1; why.append(f"skew to puts {r['dRR']:+.1f}")
        if r.get("dFpct") is not None and r.get("dIV") is not None:
            if r["dFpct"] > 0.005 and r["dIV"] < -0.5:
                sc += 0.5; why.append("rally with vol offered")
            elif r["dFpct"] < -0.005 and r["dIV"] < -0.5:
                sc -= 0.5; why.append("sell-off with vol offered")
        r["flow"] = "bullish" if sc >= 1 else "bearish" if sc <= -1 else "mixed"
        r["flow_why"] = ", ".join(why) if why else "no clear build on either side"
        exp_rows.append(r)

    # expected moves (1 standard deviation)
    em = None
    if a is not None:
        em = {"day": F * a / 100 * math.sqrt(1 / 252), "week": F * a / 100 * math.sqrt(5 / 252), "expiry": F * a / 100 * math.sqrt(dte / 365), "dte": dte}

    # changes
    def chg(col, ref):
        if ref is None or pd.isna(H.at[ref, col]) or pd.isna(H[col].iloc[-1]):
            return None
        return float(H[col].iloc[-1] - H.at[ref, col])
    cur = H.iloc[-1]
    dIV1, dIV5 = chg("atm", d1), chg("atm", w1)
    dRR5 = chg("rr25", w1)
    cOI5 = chg("cOI", w1); pOI5 = chg("pOI", w1)
    pc_avg = float(H.pc_oi.mean())
    vol5 = H[H.index > last - pd.Timedelta(days=7)]
    pcv5 = float(vol5.pVol.sum() / vol5.cVol.sum()) if vol5.cVol.sum() > 0 else None
    pcv_all = float(H.pVol.sum() / H.cVol.sum()) if H.cVol.sum() > 0 else None
    vrp = (a - rv20) if a is not None and rv20 is not None else None

    # ── read: factors (rules informed by cotton's own vol/price behaviour) ──
    F_ = []
    def add(name, tilt, text):
        F_.append({"factor": name, "tilt": tilt, "text": text})
    if r5 is not None and dIV5 is not None:
        if r5 > 0.015 and dIV5 < -0.5:
            add("Price & vol", "bullish", f"Futures {r5:+.1%} over the week while implied vol fell {dIV5:+.1f} pts — an orderly rally with no rush for upside calls; moves like this have tended to keep going in the near term.")
        elif r5 > 0.015 and dIV5 > 1:
            add("Price & vol", "bearish", f"Futures {r5:+.1%} with implied vol up {dIV5:+.1f} pts — buyers chasing upside calls. In {LABEL[T].split()[0].lower()} vol normally rises in rallies, but sharp vol-bid rallies have tended to fade.")
        elif r5 < -0.015 and dIV5 < -0.5:
            add("Price & vol", "bearish", f"Futures {r5:+.1%} with implied vol down {dIV5:+.1f} pts — an orderly sell-off with no demand for protection; sell-offs like this have tended to continue.")
        elif r5 < -0.015 and dIV5 > 1:
            add("Price & vol", "neutral", f"Futures {r5:+.1%} with implied vol up {dIV5:+.1f} pts — hedgers paying up for puts; this mix has been a less reliable guide to direction.")
        else:
            add("Price & vol", "neutral", f"Futures {r5:+.1%} over the week, implied vol {dIV5:+.1f} pts — no clear signal from the price/vol mix.")
    if pct1y is not None:
        if pct1y >= 80:
            add("Vol level", "bearish", f"Implied vol {a:.1f}% is in the {ordn(pct1y)} percentile {pct_lbl} — expect bigger swings; high-vol spells have more often resolved lower.")
        elif pct1y <= 20:
            add("Vol level", "neutral", f"Implied vol {a:.1f}% is in the {ordn(pct1y)} percentile {pct_lbl} — options are cheap for protection or upside exposure; quiet spells rarely last.")
        else:
            add("Vol level", "neutral", f"Implied vol {a:.1f}% sits at the {ordn(pct1y)} percentile {pct_lbl}.")
    if vrp is not None:
        add("Vol vs realized", "neutral", f"Implied {a:.1f}% vs 20-day realized {rv20:.1f}% (premium {vrp:+.1f} pts) — "
            + ("options are rich; realized vol has usually come in well under implied from here, which favours selling premium or using spreads." if vrp >= 5 else
               "options are cheap relative to how the market is actually moving — owning options is relatively attractive." if vrp <= -2 else "options fairly priced vs realized movement."))
    if cur.rr25 is not None and not pd.isna(cur.rr25):
        rr = float(cur.rr25)
        if dRR5 is not None and dRR5 > 2:
            add("Skew", "bearish", f"25-delta risk reversal {rr:+.1f} vol, up {dRR5:+.1f} on the week — upside calls bid sharply; sudden call-skew spikes have often marked short-term exhaustion.")
        elif rr > 1:
            add("Skew", "bullish", f"25-delta risk reversal {rr:+.1f} vol — calls priced over puts; a persistent call skew has leaned bullish over the following weeks.")
        elif rr < -1:
            add("Skew", "bearish", f"25-delta risk reversal {rr:+.1f} vol — puts priced over calls; the market is paying for downside protection.")
        else:
            add("Skew", "neutral", f"25-delta risk reversal {rr:+.1f} vol — skew roughly balanced.")
    if not pd.isna(cur.pc_oi):
        z = (cur.pc_oi - pc_avg)
        tilt = "bearish" if cur.pc_oi > pc_avg * 1.08 else "bullish" if cur.pc_oi < pc_avg * 0.92 else "neutral"
        add("Put/call positioning", tilt, f"Put/call open interest {cur.pc_oi:.2f} vs {pc_avg:.2f} average over the week"
            + (f"; put/call volume over the past week {pcv5:.2f}" if pcv5 else "") + " — "
            + ("put-heavy positioning; in this market heavy put demand has more often been right than contrarian (short history)." if tilt == "bearish" else
               "call-heavy positioning (short history)." if tilt == "bullish" else "positioning near its recent norm."))
    if cOI5 is not None and pOI5 is not None and r5 is not None:
        if r5 < -0.01 and pOI5 > abs(cOI5) and pOI5 > 0:
            add("OI flow", "bearish", f"Put open interest +{pOI5:,.0f} lots vs calls {cOI5:+,.0f} on a falling market — fresh hedges or bearish bets being added.")
        elif r5 > 0.01 and cOI5 > abs(pOI5) and cOI5 > 0:
            add("OI flow", "bullish", f"Call open interest +{cOI5:,.0f} lots vs puts {pOI5:+,.0f} on a rising market — new upside positions being added.")
        elif r5 > 0.01 and cOI5 < 0:
            add("OI flow", "neutral", f"Calls {cOI5:+,.0f} lots on a rally — upside positions being taken off rather than added.")
        else:
            add("OI flow", "neutral", f"Week's open-interest change: calls {cOI5:+,.0f}, puts {pOI5:+,.0f} lots.")
    score = sum(1 if f["tilt"] == "bullish" else -1 if f["tilt"] == "bearish" else 0 for f in F_)
    label = "bullish" if score >= 2 else "leaning bullish" if score == 1 else "bearish" if score <= -2 else "leaning bearish" if score == -1 else "neutral"
    rich = vrp is not None and vrp >= 5; cheap = (vrp is not None and vrp <= -2) or (pct1y is not None and pct1y <= 20)
    if "bull" in label:
        idea = "call spreads or selling puts below the put wall" if rich else "outright calls or call spreads"
    elif "bear" in label:
        idea = "put spreads or selling calls above the call wall" if rich else "outright puts or put spreads"
    else:
        idea = "selling a range around the walls with defined risk (iron condor / strangle with wings)" if rich else "owning a straddle or strangle ahead of the next catalyst" if cheap else "staying light until flow or skew gives a direction"

    mp = maps[0] if maps else {}
    T_ = []
    T_.append({"h": "Vol snapshot", "t": (
        f"{exp_label(fe)} options (futures {F:.2f}, {dte} days to expiry): ATM implied vol **{a:.1f}%** "
        + (f"({dIV1:+.1f} pts on the day, {dIV5:+.1f} on the week)" if dIV1 is not None and dIV5 is not None else "")
        + (f", {ordn(pct1y)} percentile {pct_lbl}" if pct1y is not None else "")
        + (f"; 20-day realized {rv20:.1f}%" if rv20 is not None else "") + ". "
        + (f"Expected 1-sd move: ±{em['week']:.2f}¢ this week, ±{em['expiry']:.2f}¢ to expiry ({F - em['expiry']:.2f}–{F + em['expiry']:.2f})." if em else ""))})
    if mp:
        T_.append({"h": "Positioning map", "t": (
            f"{mp['label']}: largest call open interest above the market at **{mp['call_wall']}**, largest put open interest below at **{mp['put_wall']}**; "
            f"max pain {mp['max_pain']}; gamma is most concentrated at {mp['gamma_peak']}. "
            + (f"With {mp['dte']} days left, expect pinning pressure toward {mp['max_pain']}–{mp['gamma_peak']} into expiry. " if mp["dte"] <= 15 else "")
            + f"Calls {mp['cOI']:,} vs puts {mp['pOI']:,} lots open.")})
    flow = (f"Latest session: calls {int(cur.cVol):,} / puts {int(cur.pVol):,} lots traded; open interest calls {int(cur.cOIchg):+,}, puts {int(cur.pOIchg):+,}. ")
    if cOI5 is not None:
        flow += f"Over the week: calls {cOI5:+,.0f}, puts {pOI5:+,.0f} lots of open interest."
    T_.append({"h": "Flow", "t": flow})
    if exp_rows:
        lines = []
        for r in exp_rows:
            t = f"**{r['label']}** (futures {r['fut'][:3].title()} {r['F']:.2f}"
            if r.get("dF") is not None:
                t += f", {r['dF']:+.2f} on the week"
            if r.get("dFutOI") is not None:
                t += f"; futures OI {r['dFutOI']:+,} — {r.get('fut_read', '')}"
            t += ")"
            if r.get("spread") is not None:
                t += f"; spread to {r['spread_vs']} {r['spread']:+.2f}" + (f" ({r['dSpread']:+.2f} w/w" + (f", {'nearby firming' if r['dSpread'] > 0 else 'nearby weakening'}" if abs(r["dSpread"]) >= 0.1 else "") + ")" if r.get("dSpread") is not None else "")
            if r.get("atm") is not None:
                t += f"; ATM vol {r['atm']:.1f}%" + (f" ({r['dIV']:+.1f})" if r.get("dIV") is not None else "")
            if r.get("rr25") is not None:
                t += f", 25Δ RR {r['rr25']:+.1f}" + (f" ({r['dRR']:+.1f})" if r.get("dRR") is not None else "")
            if r.get("rv") is not None:
                t += f", realized {r['rv']:.1f}% (implied {'over' if r['vrp'] > 0 else 'under'} by {abs(r['vrp']):.1f})"
            t += (f"; options: calls {r['dcOI']:+,} / puts {r['dpOI']:+,} OI" if r.get("dcOI") is not None else "")
            t += f" — **{r['flow']} flow** ({r['flow_why']})"
            if r.get("call_wall") is not None:
                t += f"; call wall {r['call_wall']}, put wall {r['put_wall']}, max gamma {r['gamma_peak']}, max pain {r['max_pain']}."
            lines.append(t)
        T_.insert(1, {"h": "By expiry — past week", "t": "<br>".join(lines)})
    T_.append({"h": "Read", "t": f"**Options read: {label}.** " + " ".join(f["text"] for f in F_ if f["tilt"] != "neutral")})
    T_.append({"h": "Trade idea (not advice)", "t": f"With vol {'rich' if rich else 'cheap' if cheap else 'fairly priced'} and a {label} lean: {idea}."})

    hist_out = {"dates": [d.strftime("%Y-%m-%d") for d in H.index], "F": [round(x, 2) for x in H.F],
                "atm": [None if pd.isna(x) else round(x, 2) for x in H.atm], "rr25": [None if pd.isna(x) else round(x, 2) for x in H.rr25],
                "bf25": [None if pd.isna(x) else round(x, 2) for x in H.bf25], "pc_oi": [None if pd.isna(x) else round(x, 3) for x in H.pc_oi],
                "cOI": list(H.cOI), "pOI": list(H.pOI), "cVol": list(H.cVol), "pVol": list(H.pVol), "front": list(H.front)}
    if ret_series is not None:
        rv = ret_series[ret_series.index >= H.index[0] - pd.Timedelta(days=10)].dropna()
        hist_out["rv20"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in rv.items()]
        pp = px[(px.index >= H.index[0] - pd.Timedelta(days=10)) & (px.index <= last)]
        hist_out["px"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in pp.close.items()]
    return {"ticker": T, "label": LABEL[T], "unit": UNIT[T], "date": last.strftime("%Y-%m-%d"), "skipped": skipped,
            "front": fe, "front_label": exp_label(fe), "F": F, "dte": dte, "atm": a, "dIV1": dIV1, "dIV5": dIV5,
            "rr25": None if pd.isna(cur.rr25) else float(cur.rr25), "bf25": None if pd.isna(cur.bf25) else float(cur.bf25), "dRR5": dRR5,
            "pct1y": pct1y, "pct5y": pct5y, "pct_lbl": pct_lbl, "rv20": rv20, "rv60": rv60, "vrp": vrp, "r1": r1, "r5": r5,
            "pc_oi": None if pd.isna(cur.pc_oi) else float(cur.pc_oi), "pc_oi_avg": pc_avg, "pc_vol5": pcv5, "pc_vol_all": pcv_all,
            "cOI": int(cur.cOI), "pOI": int(cur.pOI), "cOI5": cOI5, "pOI5": pOI5, "em": em,
            "factors": F_, "score": score, "lean": label, "vol_view": "rich" if rich else "cheap" if cheap else "fair", "idea": idea, "brief": T_,
            "term": term(last), "term_wk": term(w1) if w1 is not None else [],
            "smile": {"front": smile_pts(last, fe), "front_wk": smile_pts(w1, fe) if w1 is not None else [],
                      "second": smile_pts(last, se) if se else [], "second_label": exp_label(se) if se else None},
            "maps": maps, "expiries": exp_rows, "hist": hist_out, "ivlong": ivlong, "ivlong_source": "Bloomberg front-month implied vol + ICE settlements" if ivlong else None,
            "wk_ref": w1.strftime("%Y-%m-%d") if w1 is not None else None}


def clean(o):
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    return o


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ivct = bloomberg_iv_ct()
    idx = {}
    for T in ("CT", "KC", "SB"):
        try:
            b = build(T, yahoo(T), ivct if T == "CT" else None)
        except Exception as ex:
            import traceback; traceback.print_exc(); b = None
        if b:
            (OUT / f"{T}_desk.json").write_text(json.dumps(clean(b), separators=(",", ":"), allow_nan=False))
            idx[T] = {"date": b["date"], "lean": b["lean"], "vol_view": b["vol_view"]}
            print(f"\n== {T} {b['date']} {b['front_label']} ATM {b['atm']:.1f}  lean={b['lean']} vol={b['vol_view']}  skipped={b['skipped']}")
            for x in b["brief"]:
                print(f"[{x['h']}] {x['t']}")
    (OUT / "index.json").write_text(json.dumps({"generated": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"), "markets": idx}))


if __name__ == "__main__":
    main()
