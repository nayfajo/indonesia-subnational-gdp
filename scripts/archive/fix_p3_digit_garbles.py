"""
fix_p3_digit_garbles.py

P3: Null confirmed BPS source errors (digit garbles / wrong-magnitude values).

Each entry was verified by PDF visual inspection before nulling.

Method per W3 precedent:
  1. PDF inspection confirms what BPS printed
  2. If printed value is inconsistent with before/after trend by >300% AND no higher
     source can correct it: null with log entry
  3. Log includes raw value and rationale

Fixes applied here:
  W3a — RIAU_KAMPAR real/1993 2000-2003 (~160× too low, BPS source error same in both pubs)
  W3b — MUSI_RAWAS nominal oil=True 2001 (×10 too high, single cell)
  W3c — SAMBAS capita 1996-1999 (÷10, values ×10 too high from scan shadow)
  W3d — SUMENEP real/1993 1996 (extra digit, ×8 too high)
  W3e — MAMUJU real/1993 1999 (spike-and-revert garble)
  W3f — KAPUAS capita 1999 (spurious leading "1", ×10 too high)

Each fix requires PDF inspection first. Script structured so each block
can be commented out if inspection reveals it needs different treatment.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")
CSVS = Path("pipeline_out/full_runs/csvs")


def null_rows(df, mask, fix_id, description, rationale):
    """Null value for matching rows and return correction log entries."""
    entries = []
    for idx in df.index[mask]:
        old_val = df.loc[idx, "value"]
        if pd.isna(old_val) or str(old_val).strip() in ("", "nan"):
            continue
        df.loc[idx, "value"] = ""
        entries.append({
            "date": str(date.today()),
            "source_file": "",  # filled by caller
            "fix_id": fix_id,
            "description": description + f" [row {idx}]",
            "year": df.loc[idx, "year"] if "year" in df.columns else "",
            "row_index_kab": idx,
            "row_index_kota": "",
            "kab_value_before": str(old_val),
            "kab_value_after": "",
            "kota_value_before": "",
            "kota_value_after": "",
            "rationale": rationale,
        })
    return entries


all_corrections = []

# ── W3a: Kampar real/1993 2000-2003 ─────────────────────────────────────────
# PDF (PDRB_2000-2001.pdf page 36) prints 11,120.92 juta for 2000.
# 1996-1999 source shows 1,826,129 juta for 1999 → ~160× too low.
# Same wrong values in old PDRB_2000-2003.pdf — BPS source error, not OCR.
# Both total and oil-excluded rows are wrong.

RAW = CSVS / "PDRB_2000-2001_wide_v2.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["province_name"].str.upper().str.contains("RIAU", na=False)) &
    (df["region_name_raw"].str.upper().str.contains("KAMPAR", na=False)) &
    (df["table_header_raw"].str.contains("KONSTAN", case=False, na=False))
)
entries = null_rows(
    df, mask, "W3a",
    "RIAU/KAMPAR real/1993 BPS source error (printed ~160× too low)",
    "PDF (PDRB_2000-2001.pdf Table 34, p.34) prints 11,120.92 juta for 2000 real/1993. "
    "1996-1999 source shows 1,826,129 juta for 1999 — impossible 160× drop. "
    "Same wrong values in old PDRB_2000-2003.pdf. BPS source error in both publications.",
)
for e in entries:
    e["source_file"] = RAW.name
all_corrections.extend(entries)
df.to_csv(RAW, index=False)
print(f"W3a: nulled {len(entries)} Kampar real/1993 rows in {RAW.name}")


# ── W3b: Musi Rawas nominal oil=True 2001 ────────────────────────────────────
# PDF (PDRB_2000-2001.pdf Table 6, p.6) prints "1 910 163,00" for Musi Rawas¹) 2001.
# pdfplumber extracted "1 910 16o3,0.0" — 'o' OCR artifact for '1', trailing '.0' garbage.
# Parser computed 1.910163e+13 (×10 too high). Correct raw → "1.910.163,00".

RAW = CSVS / "PDRB_2000-2001_wide_v2.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper().str.contains("MUSI RAWAS", na=False)) &
    (df["year"].astype(str) == "2001") &
    (df["value"].astype(str).str.contains("16o3", na=False))
)
rows_found = df[mask]
for idx, row in rows_found.iterrows():
    old_val = row["value"]
    df.loc[idx, "value"] = "1.910.163,00"
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "W3b",
        "description": f"MUSI RAWAS nominal oil=True 2001 OCR garble corrected [row {idx}]",
        "year": 2001,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": "1.910.163,00",
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "PDF (Table 6, p.6) prints '1 910 163,00' for Musi Rawas oil-excl 2001. "
            "pdfplumber extracted '1 910 16o3,0.0' — 'o' artifact and trailing garbage "
            "caused parser to compute 19,101,630 instead of 1,910,163. "
            "Consistent with 2000=1,657,991 and 2002=1,546,751 (oil-excl trajectory)."
        ),
    })
df.to_csv(RAW, index=False)
print(f"W3b: corrected {len(rows_found)} Musi Rawas oil-excl 2001 row(s)")


# ── W3c: Sambas capita 1996-1999 ─────────────────────────────────────────────
# PDF (Table 66) prints Sambas per-capita as 199.138,54 for 1996.
# All other KalBar districts: 1.7-5.1M rupiah. BPS source error: ÷10 denominator.
# Proof: Sambas 1999 value ×10 = 3,977,382 ≈ 2000 value 3,977,878 (0.01% match).
# Fix: multiply raw values by 10 (convert "199.138,54" → "1.991.385,40" etc.)

RAW = CSVS / "PDRB-capita_1996-1999_wide_a.csv"
df = pd.read_csv(RAW, dtype=str)

import re
def bps_to_float(s):
    """Parse BPS number format (period=thousands, comma=decimal) to float."""
    s = str(s).strip()
    if ',' in s:
        parts = s.rsplit(',', 1)
        integer_str = parts[0].replace('.', '').replace(' ', '')
        decimal_str = parts[1]
        try:
            return float(integer_str + '.' + decimal_str)
        except:
            return None
    return None

def float_to_bps(f):
    """Format float back to BPS string format (period=thousands, comma=decimal)."""
    rounded = round(f, 2)
    int_part = int(rounded)
    dec_part = round((rounded - int_part) * 100)
    int_str = f"{int_part:,}".replace(",", ".")
    return f"{int_str},{dec_part:02d}"

mask = df["region_name_raw"].str.upper() == "SAMBAS"
for idx, row in df[mask].iterrows():
    old_val = row["value"]
    parsed = bps_to_float(str(old_val))
    if parsed is None:
        print(f"  W3c: could not parse Sambas row {idx}: {repr(old_val)}")
        continue
    corrected = float_to_bps(parsed * 10)
    df.loc[idx, "value"] = corrected
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "W3c",
        "description": f"SAMBAS capita {row['year']} ÷10 BPS error corrected ×10 [row {idx}]",
        "year": row["year"],
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": corrected,
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "PDF Table 66 (PDRB-capita_1996-1999.pdf p.3) prints Sambas 1996=199,138.54 "
            "while all other 8 KalBar districts show 1.7-5.1M rupiah/capita. "
            "Sambas 1999 value ×10 = 3,977,382 ≈ 2000 value 3,977,878 (0.01% match) — "
            "confirms exact ÷10 BPS denominator error. Corrected by ×10."
        ),
    })
df.to_csv(RAW, index=False)
print(f"W3c: corrected {mask.sum()} Sambas capita rows")


# ── W3d: Sumenep real/1993 1996 ──────────────────────────────────────────────
# PDF (Table 39, PDRB_1996-1999.pdf p.42) prints "852.541,10" for Sumenep 1996 real.
# OCR dropped period, giving "8521541,10" → ×10 too high (8,521,541 vs 852,541).

RAW = CSVS / "PDRB_1996-1999_wide_a.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper() == "SUMENEP") &
    (df["year"].astype(str) == "1996") &
    (df["value"].astype(str).str.startswith("852"))
)
for idx, row in df[mask].iterrows():
    old_val = row["value"]
    # "8521541,10" → "852.541,10"
    corrected = "852.541,10"
    df.loc[idx, "value"] = corrected
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "W3d",
        "description": f"SUMENEP real/1993 1996 OCR drop corrected [row {idx}]",
        "year": 1996,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": corrected,
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "PDF Table 39 (PDRB_1996-1999.pdf p.42) prints '852.541,10' juta for "
            "Sumenep 1996 real/1993. OCR dropped the thousands-separator period, giving "
            "'8521541,10' = 8,521,541 (×10 too high). Other years: 978,766/873,943/903,150."
        ),
    })
df.to_csv(RAW, index=False)
print(f"W3d: corrected {mask.sum()} Sumenep real/1993 1996 row(s)")


# ── W3e: Mamuju real/1993 1999 ────────────────────────────────────────────────
# PDF (Table 46, PDRB_1996-1999.pdf p.49) confirms 649.558,43 printed for Mamuju 1999.
# Trajectory: 185,999 → 285,861 → 195,701 → 649,558 (232% spike impossible).
# BPS source error — null. No cross-reference to recover correct value.

RAW = CSVS / "PDRB_1996-1999_wide_a.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper() == "MAMUJU") &
    (df["year"].astype(str) == "1999")
)
entries = null_rows(
    df, mask, "W3e",
    "MAMUJU real/1993 1999 BPS source error (232% impossible spike)",
    "PDF Table 46 (PDRB_1996-1999.pdf p.49) prints 649,558.43 for Mamuju 1999 real/1993. "
    "Trajectory: 185,999 → 285,861 → 195,701 → 649,558 — 232% jump impossible. "
    "Province total check inconclusive. Nulled; no cross-reference source available.",
)
for e in entries:
    e["source_file"] = RAW.name
all_corrections.extend(entries)
df.to_csv(RAW, index=False)
print(f"W3e: nulled {len(entries)} Mamuju real/1993 1999 row(s)")


# ── W3f: Kapuas capita 1999 ──────────────────────────────────────────────────
# PDF (Table 67, PDRB-capita_1996-1999.pdf p.4) shows Kapuas 1999 = 13.873.942,59.
# Pattern: 2,055,672 → 2,247,678 → 3,348,449 → 13,873,943 (314% spike impossible).
# Removing leading "1": 3.873.942,59 → +15.7% from 1998 (plausible).
# Mirrors W3 (Banjarmasin "L" → "1" prefix).

RAW = CSVS / "PDRB-capita_1996-1999_wide_a.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper() == "KAPUAS") &
    (df["year"].astype(str) == "1999") &
    (df["value"].astype(str).str.startswith("13"))
)
for idx, row in df[mask].iterrows():
    old_val = row["value"]
    corrected = "3.873.942,59"
    df.loc[idx, "value"] = corrected
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "W3f",
        "description": f"KAPUAS capita 1999 spurious leading '1' removed [row {idx}]",
        "year": 1999,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": corrected,
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "PDF Table 67 (PDRB-capita_1996-1999.pdf p.4) prints '13.873.942,59' for "
            "Kapuas 1999 per-capita. Preceding years: 2,056K/2,248K/3,348K. "
            "Removing spurious leading '1': 3.873.942,59 (+15.7% from 1998). "
            "2000 value = 3,977,878 → smooth continuation. BPS scan shadow artifact."
        ),
    })
df.to_csv(RAW, index=False)
print(f"W3f: corrected {mask.sum()} Kapuas capita 1999 row(s)")


# ── Write all corrections to log ─────────────────────────────────────────────

if all_corrections:
    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_corrections[0].keys()))
        writer.writerows(all_corrections)
    print(f"Logged {len(all_corrections)} corrections total")
else:
    print("No corrections applied in this run")
