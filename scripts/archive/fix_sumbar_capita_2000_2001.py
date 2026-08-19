"""
fix_sumbar_capita_2000_2001.py

PDRB-capita_2000-2001_wide_v2.csv uses a single wrong population denominator
(~61-62K) for ALL 15 Sumatera Barat districts in years 2000 and 2001.

Evidence: total PDRB / per-capita = 61-62K implied population for EVERY district,
regardless of actual population (range: 42K Padang Panjang to 743K Padang).
This is a BPS publication error — the same denominator was used for all districts.

Affected panel districts for years 2000-2001:
  9 districts with actual pop >> 62K: per-capita 4-10× too high
  6 districts with actual pop ≤ 62K:  per-capita ~10-30% wrong in opposite direction
  → ALL 15 affected; nulled pending BPS online recovery (fix_id W2c_recover).

Years 2002-2003 in this file are also wrong but overridden in build_panel
by higher-priority PDRB-capita_2002-2004 publication — no panel impact.

fix_id: W2c
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB-capita_2000-2001_wide_v2.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

PROVINCE = "SUMATERA BARAT"
TARGET_YEARS = {2000, 2001}

# Rows that are province totals, not district data
SKIP_NAME_FRAGMENTS = {"jml", "total"}


def is_summary_row(name):
    if pd.isna(name):
        return False
    return any(frag in str(name).lower() for frag in SKIP_NAME_FRAGMENTS)


def main():
    df = pd.read_csv(RAW_CSV, dtype=str)
    corrections = []
    nulled = 0

    for idx, row in df.iterrows():
        if str(row.get("province_name", "")).strip().upper() != PROVINCE:
            continue
        try:
            year = int(float(str(row["year"])))
        except (ValueError, TypeError):
            continue
        if year not in TARGET_YEARS:
            continue
        if is_summary_row(row.get("region_name_raw")):
            continue
        old_val = row["value"]
        if pd.isna(old_val) or str(old_val).strip() in ("", "nan"):
            continue  # already null / #) placeholder

        df.loc[idx, "value"] = ""  # null
        nulled += 1
        corrections.append({
            "date": str(date.today()),
            "source_file": RAW_CSV.name,
            "fix_id": "W2c",
            "description": f"SumBar per-capita wrong population denominator: {row['region_name_raw']} {year}",
            "year": year,
            "row_index_kab": idx,
            "row_index_kota": "",
            "kab_value_before": str(old_val),
            "kab_value_after": "",
            "kota_value_before": "",
            "kota_value_after": "",
            "rationale": (
                "PDRB-capita_2000-2001 (Sumatera Barat) uses a single wrong population "
                "denominator (~62K) for ALL 15 districts in 2000-2001. Implied population "
                "= total PDRB / per-capita = 61-62K uniformly across all districts. "
                "Actual populations range from 42K (Padang Panjang) to 743K (Padang). "
                "All values nulled pending BPS Sumbar online recovery (fix W2c_recover)."
            ),
        })

    df.to_csv(RAW_CSV, index=False)
    print(f"Nulled {nulled} rows in {RAW_CSV.name}")

    if corrections:
        with open(LOG_CSV, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(corrections[0].keys()))
            writer.writerows(corrections)
        print(f"Logged {len(corrections)} corrections (fix_id=W2c)")


if __name__ == "__main__":
    main()
