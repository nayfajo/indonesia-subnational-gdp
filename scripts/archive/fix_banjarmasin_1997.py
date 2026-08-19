"""
fix_banjarmasin_1997.py

In PDRB_1996-1999_wide_a.csv, Banjarmasin 1997 real/1993-base value is "L421.607,59".
The "L" is an OCR misread of "1" caused by a shadow/scan artifact on page 45 (all
characters are doubled; the parser collapsed duplicates but lost the leading "1").

Correct value from PDF: "1.421.607,59" juta = 1,421,607.59 juta = 1.422 trillion rupiah.
Without fix: 421,607.59 juta = 0.422 trillion (3.37x too low), causing a false -68%/+195%
swing in the real series around the 1997 Asian financial crisis.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB_1996-1999_wide_a.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

TARGET = {
    "region_name_raw": "Banjarmasin",
    "year": 1997,
    "bad_value": "L421.607,59",
    "good_value": "1.421.607,59",
}


def main():
    df = pd.read_csv(RAW_CSV)

    mask = (
        (df["region_name_raw"] == TARGET["region_name_raw"])
        & (df["year"] == TARGET["year"])
        & (df["value"] == TARGET["bad_value"])
    )
    assert mask.sum() == 1, f"Expected 1 row, found {mask.sum()}"

    idx = df.index[mask][0]
    df.loc[idx, "value"] = TARGET["good_value"]
    df.to_csv(RAW_CSV, index=False)
    print(f"Fixed row {idx}: '{TARGET['bad_value']}' → '{TARGET['good_value']}'")

    log_exists = LOG_CSV.exists()
    correction = {
        "date": str(date.today()),
        "source_file": "PDRB_1996-1999_wide_a.csv",
        "fix_id": "W3",
        "description": "Banjarmasin 1997 real leading-digit OCR fix",
        "year": 1997,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": TARGET["bad_value"],
        "kab_value_after": TARGET["good_value"],
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            "Page 45 of PDRB_1996-1999.pdf has doubled characters throughout "
            "(scan shadow artifact). The leading '1' in '1.421.607,59' was misread "
            "as 'L' in the shadow layer; pdfplumber collapsed duplicates keeping 'L' "
            "and dropped the clean-layer '1'. Without fix: 0.422T (−68% from 1996). "
            "With fix: 1.422T (stable trajectory consistent with 1996=1.331T and "
            "1998=1.244T after Asian crisis)."
        ),
    }
    with open(LOG_CSV, "a", newline="") as f:
        fieldnames = list(correction.keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not log_exists:
            writer.writeheader()
        writer.writerow(correction)
    print(f"Logged to {LOG_CSV}")


if __name__ == "__main__":
    main()
