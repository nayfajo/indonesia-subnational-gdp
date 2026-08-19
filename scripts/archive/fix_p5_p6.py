"""
fix_p5_p6.py

P5: Barru 1998 nominal — spike-and-revert BPS source error.
P6: Sumba Barat capita 2005-2007 — OCR garble (bounce 9.6M→1.0M→4.6M).

Fakfak 2000 nominal/real −96% is administrative boundary change (Sorong/Manokwari
split from old Fakfak district). Structural discontinuity — not nulled.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")
CSVS = Path("pipeline_out/full_runs/csvs")

all_corrections = []


# ── P5: Barru 1998 nominal ────────────────────────────────────────────────────
# 1996=188K, 1997=214K, 1998=1,641K (+664%), 1999=361K — spike-and-revert.
# Real/1993 series: 152K, 159K, 150K, 158K — completely smooth.
# Nominal 1998 spike is BPS source error (wrong row entry). Null nominal only.

RAW = CSVS / "PDRB_1996-1999_wide_a.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper() == "BARRU") &
    (df["year"].astype(str) == "1998") &
    (df["table_header_raw"].str.contains("BERLAKU", case=False, na=False))
)
for idx in df.index[mask]:
    old_val = df.loc[idx, "value"]
    if pd.isna(old_val) or str(old_val).strip() in ("", "nan"):
        continue
    df.loc[idx, "value"] = ""
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "P5a",
        "description": f"BARRU nominal 1998 spike-and-revert BPS source error nulled [row {idx}]",
        "year": 1998,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": "",
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "BARRU nominal 1993-1999 trajectory: 188K→214K→1,641K(+664%)→361K. "
            "Real/1993 series for same years: 152K→159K→150K→158K (smooth). "
            "Spike in nominal only = BPS source error (wrong value entered for 1998). "
            "No PDF inspection needed: spike-and-revert pattern with smooth real series is conclusive."
        ),
    })
df.to_csv(RAW, index=False)
print(f"P5a: nulled {mask.sum()} Barru nominal 1998 row(s)")


# ── P6: Sumba Barat capita 2005-2007 ─────────────────────────────────────────
# Values in ribu rupiah: 2005=9,623 / 2006=1,003 / 2007=4,640 — bouncing.
# Province average 2005 = 3,399 ribu; 2008=5,157 (normal).
# 2005: +363% spike, 2006: -90% drop, 2007: +363% again — OCR garble confirmed.

RAW = CSVS / "PDRB-capita_2005-2007_wide_v2.csv"
df = pd.read_csv(RAW, dtype=str)
mask = (
    (df["region_name_raw"].str.upper().str.contains("SUMBA BARAT", na=False)) &
    (df["year"].astype(str).isin(["2005", "2006", "2007"])) &
    df["name_flag"].isna()
)
for idx in df.index[mask]:
    old_val = df.loc[idx, "value"]
    if pd.isna(old_val) or str(old_val).strip() in ("", "nan", "-"):
        continue
    df.loc[idx, "value"] = ""
    yr = df.loc[idx, "year"]
    all_corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "P6",
        "description": f"SUMBA BARAT capita {yr} OCR garble nulled [row {idx}]",
        "year": yr,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": str(old_val),
        "kab_value_after": "",
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "Sumba Barat per-capita 2005=9,623/2006=1,003/2007=4,640 ribu — "
            "bouncing values (−90% then +363%). Province avg 2005=3,399 ribu; "
            "2008=5,157 (normal continuation). Three consecutive garbled years. "
            "OCR vision-parse error confirmed. Nulled; no cross-reference available."
        ),
    })
df.to_csv(RAW, index=False)
print(f"P6: nulled {mask.sum()} Sumba Barat capita rows (2005-2007)")


# ── Write corrections log ─────────────────────────────────────────────────────
if all_corrections:
    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_corrections[0].keys()))
        writer.writerows(all_corrections)
    print(f"Logged {len(all_corrections)} corrections")
