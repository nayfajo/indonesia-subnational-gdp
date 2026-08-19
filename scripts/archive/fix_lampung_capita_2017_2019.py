"""
fix_lampung_capita_2017_2019.py

In PDRB-capita_2017-2019_wide_v2.csv, Kota Bandar Lampung (code 71) and Kota Metro
(code 72) have implausible per-capita values for 2017-2021:
  Bandar Lampung: 328,350 / 355,198 / 382,028 / 362,458 / 375,837 ribu
  Metro:            5,396 /   5,700 /   6,002 /   5,422 /   5,550 ribu

These are confirmed directly from the PDF (Table 144, page 154). The parser
correctly extracted what is printed. This is a BPS data error — the per-capita
denominators for these two cities are wrong in BPS's calculation system for this
publication. Evidence:
  - Province total (37,328 ribu 2017) is calculated from aggregate data and looks
    correct — consistent with all other kabupaten values (14,666–54,804 range).
  - Bandar Lampung 2016 = 44,800 ribu and 2020 = 50,750 ribu (from other pubs).
    Correct 2017 should be ~47,000 ribu, not 328,350.
  - Metro 2016 = ~31,000 ribu and 2020 = ~37,400 ribu. Correct 2017 ~32,000,
    not 5,396.

Fix: null all 5 years (2017-2021) for both districts. Years 2020-2021 are already
overridden in build_panel by higher-priority publications (2020-2022 and 2021-2023).
Years 2017-2019 will become NaN in the capita panel (3-year gap, documented).

Also null the real (Harga Konstan) rows for the same districts/years if present,
as the same BPS calculation error likely affects both tables.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB-capita_2017-2019_wide_v2.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

TARGET_CODES = {71, 72}   # Bandar Lampung, Metro
TARGET_YEARS = {2017, 2018, 2019, 2020, 2021}


def main():
    df = pd.read_csv(RAW_CSV)

    mask = (
        (df["province_name"].str.upper() == "LAMPUNG")
        & df["regency_code"].isin(TARGET_CODES)
        & df["year"].isin(TARGET_YEARS)
    )
    affected = df[mask].copy()
    print(f"Rows to null: {mask.sum()}")
    print(affected[["region_name_raw", "regency_code", "year", "value", "table_header_raw"]].to_string())

    corrections = []
    for idx, row in affected.iterrows():
        corrections.append({
            "date": str(date.today()),
            "source_file": "PDRB-capita_2017-2019_wide_v2.csv",
            "fix_id": "W2",
            "description": "Null BPS per-capita error: Bandar Lampung & Metro 2017-2021",
            "year": int(row["year"]),
            "row_index_kab": idx,
            "row_index_kota": "",
            "kab_value_before": row["value"],
            "kab_value_after": "NaN",
            "kota_value_before": "",
            "kota_value_after": "",
            "rationale": (
                f"BPS publication error in PDRB-capita_2017-2021 (Table 144). "
                f"{row['region_name_raw']} per-capita = {row['value']} ribu is implausible. "
                f"Province total (37,328 ribu 2017) is internally consistent; only Bandar Lampung "
                f"(~7x too high) and Metro (~6x too low) are wrong. "
                f"PDF-confirmed: values are printed as-is, not a parser artifact. "
                f"Nulled; 2020+ years also overridden by higher-priority publications."
            ),
        })
        df.loc[idx, "value"] = float("nan")

    df.to_csv(RAW_CSV, index=False)
    print(f"\nSaved: {RAW_CSV}")

    with open(LOG_CSV, "a", newline="") as f:
        fieldnames = list(corrections[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(corrections)
    print(f"Logged {len(corrections)} corrections to {LOG_CSV}")


if __name__ == "__main__":
    main()
