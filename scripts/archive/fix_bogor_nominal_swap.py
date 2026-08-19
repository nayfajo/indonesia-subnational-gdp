"""
fix_bogor_nominal_swap.py — B2 fix

In PDRB_2002-2004_wide_v2.csv the nominal (Harga Berlaku) values for
Kab. Bogor (regency_code=1) and Kota Bogor (regency_code=71) are swapped.
The real (Harga Konstan) values are correct.

Evidence: Kota Bogor nominal 2002 = 33.5T vs real 2002 = 2.45T → 13.7x ratio
(impossible). After swap: Kab. nominal = 33.5T vs real = 21.4T → 1.57x (plausible).
The 2005-2007 publication confirms correct Kota Bogor nominal is ~6T scale, not ~33T.

Fix: swap `value` and `value_flag` between the code=1 and code=71 rows for:
  - province: Jawa Barat
  - table: nominal (Harga Berlaku)
  - years: 2002, 2003, 2004

Scope: 3 year × 2 rows = 6 rows affected. Years 2005-2006 in this file are
overridden by the 2005-2007 publication (higher source priority) and are left
as-is to avoid introducing wrong values that would then be masked anyway.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB_2002-2004_wide_v2.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

SWAP_YEARS = {2002, 2003, 2004}


def main():
    df = pd.read_csv(RAW_CSV)

    # Identify nominal Jawa Barat rows only
    nominal_mask = df["table_header_raw"].str.contains("Berlaku", na=False)
    jabar_mask   = df["province_name"].str.upper().str.contains("JAWA BARAT", na=False)
    bogor_mask   = df["region_name_raw"].str.strip().str.upper() == "BOGOR"
    year_mask    = df["year"].isin(SWAP_YEARS)

    kab_mask  = jabar_mask & bogor_mask & nominal_mask & year_mask & (df["regency_code"] == 1)
    kota_mask = jabar_mask & bogor_mask & nominal_mask & year_mask & (df["regency_code"] == 71)

    kab_idx  = df.index[kab_mask].tolist()
    kota_idx = df.index[kota_mask].tolist()

    assert len(kab_idx) == len(kota_idx) == len(SWAP_YEARS), (
        f"Expected {len(SWAP_YEARS)} rows each, got kab={len(kab_idx)}, kota={len(kota_idx)}"
    )

    # Sort both by year so the swap is year-aligned
    kab_by_year  = df.loc[kab_idx].sort_values("year")
    kota_by_year = df.loc[kota_idx].sort_values("year")

    corrections = []
    for (_, kab_row), (_, kota_row) in zip(
        kab_by_year.iterrows(), kota_by_year.iterrows()
    ):
        yr = int(kab_row["year"])
        assert yr == int(kota_row["year"]), f"Year mismatch: {yr} vs {kota_row['year']}"

        kab_val_before  = kab_row["value"]
        kota_val_before = kota_row["value"]

        # Swap values
        df.loc[kab_row.name,  "value"] = kota_val_before
        df.loc[kota_row.name, "value"] = kab_val_before

        # Swap value_flag if present
        if "value_flag" in df.columns:
            kab_flag  = kab_row["value_flag"]
            kota_flag = kota_row["value_flag"]
            df.loc[kab_row.name,  "value_flag"] = kota_flag
            df.loc[kota_row.name, "value_flag"] = kab_flag

        corrections.append({
            "date":        str(date.today()),
            "source_file": "PDRB_2002-2004_wide_v2.csv",
            "fix_id":      "B2",
            "description": "Bogor Kab/Kota nominal value swap",
            "year":        yr,
            "row_index_kab":        kab_row.name,
            "row_index_kota":       kota_row.name,
            "kab_value_before":     kab_val_before,
            "kab_value_after":      kota_val_before,
            "kota_value_before":    kota_val_before,
            "kota_value_after":     kab_val_before,
            "rationale": (
                "Kota Bogor nominal/real ratio was 13.7x (impossible). "
                "Real series (Harga Konstan) is unaffected. "
                "After swap: Kab ratio ~1.57x (plausible), Kota ratio lower. "
                "2005-2007 pub overrides years 2005+ so only 2002-2004 swapped."
            ),
        })
        print(f"  year={yr}: Kab value {kab_val_before} → {kota_val_before} | "
              f"Kota value {kota_val_before} → {kab_val_before}")

    df.to_csv(RAW_CSV, index=False)
    print(f"\nSaved corrected CSV: {RAW_CSV}")

    # Write corrections log
    log_exists = LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=corrections[0].keys())
        if not log_exists:
            writer.writeheader()
        writer.writerows(corrections)
    print(f"Corrections logged: {LOG_CSV}")


if __name__ == "__main__":
    main()
