#!/usr/bin/env python3
"""
ICE Options Analytics CSV Archiver (Single File Per Commodity)
================================================================
Processes ICE Daily Market Report (DMR) PDFs and appends to ONE master CSV per commodity.

Supports: CT (Cotton No.2), KC (Coffee C), SB (Sugar No.11)

Usage:
    # Process new PDFs and append to master CSV
    python options_csv_archiver_single.py --options-pdf CT_2026_04_15.pdf --futures-pdf CT_2026_04_15-2.pdf --master-csv ./CT_MASTER.csv

    # Or batch process directory
    python options_csv_archiver_single.py --pdf-dir ./pdfs --output-dir ./csv_archive --ticker CT

    # View stats
    python options_csv_archiver_single.py --stats --master-csv ./CT_MASTER.csv

Output:
    - ONE file per commodity: {TICKER}_MASTER.csv
    - Schema identical to multi-file version but deduplicated by date
"""

import os
import os
import re
import sys
import json
import math
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import csv

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("Warning: pdfplumber not installed. Install with: pip install pdfplumber")

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

COMMODITIES = {
    'CT': {
        'label': 'Cotton No.2', 'ticker': 'CT', 'unit': '¢/lb',
        'option_prefix': 'CT', 'futures_prefix': 'CT',
        'strike_step': 1, 'contract_size': 50000,
        'ltd': {
            'MAY26':'2026-04-10','JUL26':'2026-06-12','SEP26':'2026-08-21','OCT26':'2026-09-11',
            'NOV26':'2026-10-16','DEC26':'2026-11-13','JAN27':'2026-12-18','MAR27':'2027-02-05',
            'MAY27':'2027-04-16','JUL27':'2027-06-11','SEP27':'2027-08-20','OCT27':'2027-09-10',
            'NOV27':'2027-10-15','DEC27':'2027-11-12','JAN28':'2027-12-17','MAR28':'2028-02-11',
            'MAY28':'2028-04-13','JUL28':'2028-06-09','SEP28':'2028-08-18','OCT28':'2028-09-15',
            'NOV28':'2028-10-20','DEC28':'2028-11-10','JAN29':'2028-12-15','MAR29':'2029-02-09'
        },
        'exp_order': ['MAY26','JUL26','SEP26','OCT26','NOV26','DEC26','JAN27','MAR27','MAY27','JUL27','SEP27','OCT27','NOV27','DEC27','JAN28','MAR28','MAY28','JUL28','SEP28','OCT28','NOV28','DEC28','JAN29','MAR29']
    },
    'KC': {
        'label': 'Coffee C', 'ticker': 'KC', 'unit': '¢/lb',
        'option_prefix': 'KC', 'futures_prefix': 'KC',
        'strike_step': 2.5, 'contract_size': 37500,
        'ltd': {
            'MAY26':'2026-04-10','JUN26':'2026-05-08','JUL26':'2026-06-12','AUG26':'2026-07-10',
            'SEP26':'2026-08-14','DEC26':'2026-11-12','MAR27':'2027-02-10','MAY27':'2027-04-09',
            'JUL27':'2027-06-11','SEP27':'2027-08-13','DEC27':'2027-11-12','MAR28':'2028-02-11'
        },
        'exp_order': ['MAY26','JUN26','JUL26','AUG26','SEP26','DEC26','MAR27','MAY27','JUL27','SEP27','DEC27','MAR28']
    },
    'SB': {
        'label': 'Sugar No.11', 'ticker': 'SB', 'unit': '¢/lb',
        'option_prefix': 'SB', 'futures_prefix': 'SB',
        'strike_step': 0.25, 'contract_size': 112000,
        'ltd': {
            'MAY26':'2026-04-15','JUN26':'2026-05-15','JUL26':'2026-06-15','AUG26':'2026-07-15',
            'OCT26':'2026-09-15','JAN27':'2026-12-15','MAR27':'2027-02-16','MAY27':'2027-04-15',
            'JUL27':'2027-06-15','OCT27':'2027-09-15','JAN28':'2027-12-15','MAR28':'2028-02-15',
            'MAY28':'2028-04-17','JUL28':'2028-06-15','OCT28':'2028-09-15','JAN29':'2028-12-15',
            'MAR29':'2029-02-15'
        },
        'exp_order': ['MAY26','JUN26','JUL26','AUG26','OCT26','JAN27','MAR27','MAY27','JUL27','OCT27','JAN28','MAR28','MAY28','JUL28','OCT28','JAN29','MAR29']
    }
}

RISK_FREE_RATE = 0.045
CSV_COLUMNS = [
    'date', 'commodity', 'expiry', 'strike', 'call_put', 'settle_price',
    'volume', 'open_interest', 'oi_change', 'delta', 'implied_vol_pct',
    'black76_price', 'futures_price', 'underlying_fut', 'dte', 'time_to_expiry_yrs'
]

# ═══════════════════════════════════════════════════════════════════════════════
# PDF EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pdf_text(pdf_path: str) -> str:
    text = ""
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    pt = page.extract_text()
                    if pt: text += pt + "\n"
            if text.strip(): return text
        except Exception as e:
            logger.error(f"pdfplumber failed: {e}")
    if HAS_PYPDF2:
        try:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    pt = page.extract_text()
                    if pt: text += pt + "\n"
            if text.strip(): return text
        except Exception as e:
            logger.error(f"PyPDF2 failed: {e}")
    logger.error(f"Could not extract text from {pdf_path}")
    return ""

# ═══════════════════════════════════════════════════════════════════════════════
# PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def parse_date_from_text(text: str) -> Optional[str]:
    months = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    m = re.search(r'(\d{1,2})[-\/]([A-Za-z]+)[-\/](\d{4})', text)
    if m:
        mon = months.get(m.group(2)[:3])
        if mon: return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', text)
    if m:
        mon = months.get(m.group(1)[:3])
        if mon: return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return None

def parse_date_from_filename(filename: str) -> Optional[str]:
    m = re.search(r'(\d{4})[_\-](\d{2})[_\-](\d{2})', filename)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def norm_exp(raw: str) -> Optional[str]:
    u = raw.upper().replace(' ', '').replace('-', '')
    for comm in COMMODITIES.values():
        if u in comm['exp_order']: return u
    m = re.match(r'([A-Z]{3})(\d{2})', u)
    return m.group(1) + m.group(2) if m else None

def parse_futures_pdf(text: str, ticker: str) -> Dict[str, float]:
    prices = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith(ticker): continue
        tokens = line.split()
        if len(tokens) < 3: continue
        if not re.match(r'^[A-Za-z]+-\d{2}$', tokens[1]): continue
        exp = norm_exp(tokens[1])
        if not exp: continue
        nums = []
        for t in tokens[2:]:
            try: nums.append(float(t.replace(',', '')))
            except: continue
        settle = None
        if len(nums) >= 7: settle = nums[4]
        elif len(nums) >= 1: settle = nums[0]
        if settle and math.isfinite(settle) and settle > 0:
            prices[exp] = settle
    return prices

def detect_commodity_from_filename(filename: str) -> Optional[str]:
    """Auto-detect commodity ticker from PDF filename."""
    basename = os.path.basename(filename).upper()
    for ticker in ['CT', 'KC', 'SB']:
        if basename.startswith(ticker + '_') or basename.startswith(ticker + '-'):
            return ticker
    return None

def parse_options_pdf(text: str, ticker: str) -> Dict[str, Any]:
    data = {'calls': {}, 'puts': {}}
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith(ticker): continue
        pattern = rf'^{ticker}\s+([\w]+-\d{{2}})\s+([\d.]+)\s+([CP])\s+([\d.]+)\s+(.*)'
        m = re.match(pattern, line)
        if not m: continue
        exp = norm_exp(m.group(1))
        strike = float(m.group(2))
        pc = m.group(3)
        delta = float(m.group(4))
        if not exp: continue
        nums = []
        for t in m.group(5).split():
            try: nums.append(float(t.replace(',', '')))
            except: continue
        price = vol = oi = oi_change = 0
        if len(nums) >= 13:
            price = nums[4]; vol = round(nums[6]); oi = round(nums[7]); oi_change = round(nums[8])
        elif len(nums) >= 9:
            price = nums[0]; vol = round(nums[2]); oi = round(nums[3]); oi_change = round(nums[4])
        if oi > 0 or price > 0.005:
            side = 'calls' if pc == 'C' else 'puts'
            if exp not in data[side]: data[side][exp] = {}
            data[side][exp][strike] = {'oi': oi, 'vol': vol, 'price': price, 'oiChange': oi_change, 'delta': delta}
    return data

# ═══════════════════════════════════════════════════════════════════════════════
# BLACK-76
# ═══════════════════════════════════════════════════════════════════════════════

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def black76_price(F: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0: return 0.0
    sq = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sq)
    d2 = d1 - sigma * sq
    disc = math.exp(-r * T)
    return disc * (F * normal_cdf(d1) - K * normal_cdf(d2)) if is_call else disc * (K * normal_cdf(-d2) - F * normal_cdf(-d1))

def calc_iv(F: float, K: float, T: float, r: float, mkt_price: float, is_call: bool) -> Optional[float]:
    if not F or not K or not T or not mkt_price or mkt_price < 0.005: return None
    lo, hi = 0.001, 5.0
    for _ in range(150):
        mid = (lo + hi) / 2.0
        price = black76_price(F, K, T, r, mid, is_call)
        if abs(price - mkt_price) < 0.00005: return mid
        if price < mkt_price: lo = mid
        else: hi = mid
    iv = (lo + hi) / 2.0
    return iv if 0.01 < iv < 4.0 else None

# ═══════════════════════════════════════════════════════════════════════════════
# FUTURES MAPPING & IV
# ═══════════════════════════════════════════════════════════════════════════════

def get_underlying_fut(opt_exp: str, ticker: str) -> str:
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    m = re.match(r'^([A-Z]{3})(\d{2})$', opt_exp)
    if not m: return opt_exp
    mon = months.get(m.group(1)); yr = int(m.group(2))
    if not mon: return opt_exp
    if ticker == 'CT':
        if mon == 1: return f'MAR{m.group(2)}'
        elif mon in [9, 11]: return f'DEC{m.group(2)}'
        return opt_exp
    elif ticker == 'KC':
        if mon in [1, 2]: return f'MAR{m.group(2)}'
        elif mon == 4: return f'MAY{m.group(2)}'
        elif mon == 6: return f'JUL{m.group(2)}'
        elif mon == 8: return f'SEP{m.group(2)}'
        elif mon in [10, 11]: return f'DEC{m.group(2)}'
        return opt_exp
    elif ticker == 'SB':
        if mon in [1, 2]: return f'MAR{m.group(2)}'
        elif mon == 4: return f'MAY{m.group(2)}'
        elif mon == 6: return f'JUL{m.group(2)}'
        elif mon in [8, 9]: return f'OCT{m.group(2)}'
        elif mon in [11, 12]: return f'MAR{str(yr+1).zfill(2)}'
        return opt_exp
    return opt_exp

def get_time_to_expiry(exp: str, report_date: str, commodity: str) -> float:
    ltd = COMMODITIES[commodity]['ltd'].get(exp)
    if not ltd: return 0.5
    days = max((datetime.strptime(ltd, '%Y-%m-%d') - datetime.strptime(report_date, '%Y-%m-%d')).days, 1)
    return days / 365.0

def get_fut_price(fut_prices: Dict[str, float], opt_exp: str, ticker: str) -> Optional[float]:
    return fut_prices.get(get_underlying_fut(opt_exp, ticker))

def avg_iv(exp: str, strike: float, options_data: Dict, fut_prices: Dict[str, float], report_date: str, ticker: str) -> Optional[float]:
    F = get_fut_price(fut_prices, exp, ticker)
    if not F: return None
    T = get_time_to_expiry(exp, report_date, ticker)
    if T <= 0: return None
    calls = options_data.get('calls', {}).get(exp, {})
    puts = options_data.get('puts', {}).get(exp, {})
    ivs = []
    c_rec = calls.get(strike)
    if c_rec and c_rec.get('price', 0) > 0.005:
        civ = calc_iv(F, strike, T, RISK_FREE_RATE, c_rec['price'], True)
        if civ: ivs.append(civ)
    p_rec = puts.get(strike)
    if p_rec and p_rec.get('price', 0) > 0.005:
        piv = calc_iv(F, strike, T, RISK_FREE_RATE, p_rec['price'], False)
        if piv: ivs.append(piv)
    return sum(ivs) / len(ivs) if ivs else None

# ═══════════════════════════════════════════════════════════════════════════════
# CORE: APPEND TO SINGLE CSV
# ═══════════════════════════════════════════════════════════════════════════════

def append_to_master_csv(options_data: Dict, fut_prices: Dict[str, float],
                         report_date: str, ticker: str, master_path: str) -> bool:
    """
    Append new day's data to single master CSV. 
    If date already exists, replace it (deduplication).
    """
    rows = []
    commodity = COMMODITIES[ticker]
    all_exps = set(options_data.get('calls', {}).keys()) | set(options_data.get('puts', {}).keys())

    for exp in sorted(all_exps, key=lambda e: commodity['exp_order'].index(e) if e in commodity['exp_order'] else 999):
        calls = options_data.get('calls', {}).get(exp, {})
        puts = options_data.get('puts', {}).get(exp, {})
        all_strikes = sorted(set(calls.keys()) | set(puts.keys()), reverse=True)
        F = get_fut_price(fut_prices, exp, ticker)
        T = get_time_to_expiry(exp, report_date, ticker)
        underlying = get_underlying_fut(exp, ticker)
        fut_price = fut_prices.get(underlying)
        ltd = commodity['ltd'].get(exp, '')
        dte = max((datetime.strptime(ltd, '%Y-%m-%d') - datetime.strptime(report_date, '%Y-%m-%d')).days, 0) if ltd else 0

        for strike in all_strikes:
            c_rec = calls.get(strike)
            if c_rec:
                iv = avg_iv(exp, strike, options_data, fut_prices, report_date, ticker)
                b76 = black76_price(F or 0, strike, T, RISK_FREE_RATE, iv or 0.2, True) if F else 0
                rows.append({
                    'date': report_date, 'commodity': ticker, 'expiry': exp, 'strike': strike,
                    'call_put': 'C', 'settle_price': round(c_rec.get('price', 0), 4),
                    'volume': c_rec.get('vol', 0), 'open_interest': c_rec.get('oi', 0),
                    'oi_change': c_rec.get('oiChange', 0), 'delta': round(c_rec.get('delta', 0), 4),
                    'implied_vol_pct': round(iv * 100, 2) if iv else None,
                    'black76_price': round(b76, 4) if b76 > 0 else None,
                    'futures_price': round(fut_price, 2) if fut_price else None,
                    'underlying_fut': underlying, 'dte': dte, 'time_to_expiry_yrs': round(T, 4)
                })
            p_rec = puts.get(strike)
            if p_rec:
                iv = avg_iv(exp, strike, options_data, fut_prices, report_date, ticker)
                b76 = black76_price(F or 0, strike, T, RISK_FREE_RATE, iv or 0.2, False) if F else 0
                rows.append({
                    'date': report_date, 'commodity': ticker, 'expiry': exp, 'strike': strike,
                    'call_put': 'P', 'settle_price': round(p_rec.get('price', 0), 4),
                    'volume': p_rec.get('vol', 0), 'open_interest': p_rec.get('oi', 0),
                    'oi_change': p_rec.get('oiChange', 0), 'delta': round(p_rec.get('delta', 0), 4),
                    'implied_vol_pct': round(iv * 100, 2) if iv else None,
                    'black76_price': round(b76, 4) if b76 > 0 else None,
                    'futures_price': round(fut_price, 2) if fut_price else None,
                    'underlying_fut': underlying, 'dte': dte, 'time_to_expiry_yrs': round(T, 4)
                })

    if not rows:
        logger.warning(f"No data to append for {report_date}")
        return False

    new_df = pd.DataFrame(rows)

    # Handle existing master CSV
    if os.path.exists(master_path):
        existing = pd.read_csv(master_path)
        # Remove existing rows for this date (deduplication)
        existing = existing[existing['date'] != report_date]
        # Append new data
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.sort_values(['date', 'expiry', 'strike', 'call_put'])
        combined.to_csv(master_path, index=False, float_format='%.4f')
        logger.info(f"Updated {master_path}: removed old {report_date}, appended {len(new_df)} new rows. Total: {len(combined)}")
    else:
        new_df.to_csv(master_path, index=False, float_format='%.4f')
        logger.info(f"Created {master_path} with {len(new_df)} rows")

    return True

# ═══════════════════════════════════════════════════════════════════════════════
# STATS & SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def show_stats(master_path: str):
    """Display summary statistics for a master CSV."""
    if not os.path.exists(master_path):
        print(f"File not found: {master_path}")
        return

    df = pd.read_csv(master_path)
    ticker = df['commodity'].iloc[0] if len(df) > 0 else 'Unknown'

    print(f"\n{'='*60}")
    print(f"  MASTER CSV STATS: {os.path.basename(master_path)}")
    print(f"{'='*60}")
    print(f"  Total rows:        {len(df):,}")
    print(f"  Date range:        {df['date'].min()} → {df['date'].max()}")
    print(f"  Unique dates:      {df['date'].nunique()}")
    print(f"  Expiries:          {', '.join(sorted(df['expiry'].unique()))}")
    print(f"  Strikes range:     {df['strike'].min():.2f} → {df['strike'].max():.2f}")
    print(f"  Total Call OI:     {df[df['call_put']=='C']['open_interest'].sum():,}")
    print(f"  Total Put OI:      {df[df['call_put']=='P']['open_interest'].sum():,}")
    print(f"  Latest avg IV:     {df[df['date']==df['date'].max()]['implied_vol_pct'].mean():.2f}%")
    print(f"  File size:         {os.path.getsize(master_path):,} bytes")
    print(f"{'='*60}\n")

    # Daily summary preview
    daily = df.groupby('date').agg({
        'open_interest': 'sum',
        'volume': 'sum',
        'implied_vol_pct': 'mean'
    }).reset_index()
    daily.columns = ['date', 'total_oi', 'total_volume', 'avg_iv']
    print("Last 5 days:")
    print(daily.tail().to_string(index=False))

# ═══════════════════════════════════════════════════════════════════════════════
# PROCESSING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def process_single_day(options_pdf: str, futures_pdf: str, master_path: str, ticker: Optional[str] = None) -> bool:
    # Auto-detect commodity if not specified
    if not ticker:
        ticker = detect_commodity_from_filename(options_pdf)
        if not ticker:
            logger.error(f"Cannot detect commodity from filename: {options_pdf}")
            return False
        logger.info(f"Auto-detected commodity: {ticker}")
    logger.info(f"Processing: {os.path.basename(options_pdf)} + {os.path.basename(futures_pdf)}")

    opt_text = extract_pdf_text(options_pdf)
    fut_text = extract_pdf_text(futures_pdf)

    if not opt_text:
        logger.error(f"No options text extracted")
        return False
    if not fut_text:
        logger.error(f"No futures text extracted")
        return False

    opt_date = parse_date_from_text(opt_text) or parse_date_from_filename(options_pdf)
    if not opt_date:
        logger.error("Could not determine date")
        return False

    options_data = parse_options_pdf(opt_text, COMMODITIES[ticker]['option_prefix'])
    fut_prices = parse_futures_pdf(fut_text, COMMODITIES[ticker]['futures_prefix'])

    if not options_data['calls'] and not options_data['puts']:
        logger.error("No options data parsed")
        return False

    return append_to_master_csv(options_data, fut_prices, opt_date, ticker, master_path)


def is_valid_pdf(filepath: str) -> bool:
    """Check if file is a valid PDF by reading header."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(5)
            return header == b'%PDF-'
    except Exception:
        return False

def process_directory(pdf_dir: str, output_dir: str, ticker: Optional[str] = None):
    pdf_dir = Path(pdf_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Handle empty string as None
    if ticker and str(ticker).strip():
        tickers_to_process = [str(ticker).strip().upper()]
    else:
        # Always process all 3 commodities
        tickers_to_process = ['CT', 'KC', 'SB']

    logger.info(f"Will process commodities: {tickers_to_process}")

    all_pdfs = [f for f in pdf_dir.glob("*.pdf") if not f.name.endswith('-2.pdf') and is_valid_pdf(str(f))]
    logger.info(f"Found {len(all_pdfs)} total options PDFs in {pdf_dir}")

    for current_ticker in tickers_to_process:
        master_path = str(output_dir / f"{current_ticker}_MASTER.csv")
        ticker_pdfs = [f for f in all_pdfs if detect_commodity_from_filename(str(f)) == current_ticker]

        logger.info(f"{current_ticker}: {len(ticker_pdfs)} PDFs found")

        if not ticker_pdfs:
            logger.warning(f"No PDFs found for {current_ticker} in {pdf_dir}")
            continue

        processed = failed = 0
        for opt_pdf in ticker_pdfs:
            date_part = opt_pdf.stem.replace(f"{current_ticker}_", "")
            fut_pdf = pdf_dir / f"{current_ticker}_{date_part}-2.pdf"
            if not fut_pdf.exists():
                logger.warning(f"No futures PDF for {opt_pdf.name}, skipping")
                continue
            try:
                if process_single_day(str(opt_pdf), str(fut_pdf), master_path, current_ticker):
                    processed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to process {opt_pdf.name}: {e}")
                failed += 1

        logger.info(f"Complete for {current_ticker}: {processed} days appended to {master_path}, {failed} failed")
        if os.path.exists(master_path):
            show_stats(master_path)

# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup_old_pdfs(pdf_dir: str, days: int = 7):
    """Remove PDF files older than specified days from directory."""
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.exists():
        logger.info(f"PDF directory {pdf_dir} does not exist, skipping cleanup")
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    removed = 0

    for pdf_file in pdf_dir.glob('*.pdf'):
        try:
            # Get file modification time
            mtime = datetime.fromtimestamp(pdf_file.stat().st_mtime)
            if mtime < cutoff:
                pdf_file.unlink()
                removed += 1
                logger.info(f"Removed old PDF: {pdf_file.name} (modified {mtime.strftime('%Y-%m-%d')})")
        except Exception as e:
            logger.error(f"Failed to remove {pdf_file}: {e}")

    if removed > 0:
        logger.info(f"PDF cleanup complete: removed {removed} files older than {days} days")
    else:
        logger.info(f"No PDFs older than {days} days found in {pdf_dir}")

    return removed

def main():
    parser = argparse.ArgumentParser(description='Archive ICE Options to single CSV per commodity')
    parser.add_argument('--options-pdf', help='Single options PDF')
    parser.add_argument('--futures-pdf', help='Single futures PDF')
    parser.add_argument('--pdf-dir', help='Directory with PDF pairs')
    parser.add_argument('--output-dir', help='Output directory')
    parser.add_argument('--master-csv', help='Path to master CSV file')
    parser.add_argument('--ticker', default='CT', choices=['CT','KC','SB'])
    parser.add_argument('--stats', action='store_true', help='Show stats for master CSV')
    parser.add_argument('--cleanup', action='store_true', help='Remove PDFs older than 7 days after processing')
    parser.add_argument('--cleanup-days', type=int, default=7, help='Days to keep PDFs before cleanup (default: 7)')

    args = parser.parse_args()

    if args.stats and args.master_csv:
        show_stats(args.master_csv)
        return

    # Determine master path
    if args.master_csv:
        master_path = args.master_csv
    elif args.output_dir:
        master_path = str(Path(args.output_dir) / f"{args.ticker}_MASTER.csv")
    else:
        parser.print_help()
        sys.exit(1)

    if args.pdf_dir:
        process_directory(args.pdf_dir, args.output_dir or './csv_archive', args.ticker)
        if args.cleanup:
            cleanup_old_pdfs(args.pdf_dir, args.cleanup_days)
    elif args.options_pdf and args.futures_pdf:
        if not args.ticker:
            args.ticker = detect_commodity_from_filename(args.options_pdf)
        if not args.ticker:
            logger.error("Cannot detect commodity. Use --ticker or ensure filename starts with CT_/KC_/SB_")
            sys.exit(1)
        if not args.master_csv:
            args.master_csv = f"./csv_archive/{args.ticker}_MASTER.csv"
        process_single_day(args.options_pdf, args.futures_pdf, args.master_csv, args.ticker)
        show_stats(args.master_csv)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
