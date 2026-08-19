"""
revert_b2_and_null_kota_bogor.py

The B2 swap (fix_bogor_nominal_swap.py) was incorrect. Investigation of
PDRB_2002-2004.pdf page 12 shows that the parser correctly extracted Kab. Bogor
(code 01) values: 24,002,022.55 | 26,990,272.23 | 30,684,780.53 million for
2002-2004. These match kab_value_before in corrections_log.csv exactly.

The B2 swap moved these correct values to Kota Bogor and put Kota Bogor's
garbled parser artifacts (33.5T, 32.7T, 34.6T) onto Kab. Bogor.

Root cause: Kota Bogor's row in the PDF is a scanner artifact — pdfplumber
renders it character-by-character rather than as coherent words. The parser
assembled a garbage value from this garbled region.

Fix: revert Kab. Bogor to the original correct PDF values, and null Kota Bogor
nominal 2002-2004 (values cannot be reliably extracted from this scan).
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB_2002-2004_wide_v2.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

# Original values from corrections_log.csv (kab_value_before = correct PDF value)
ORIGINAL_KAB = {
    2002: ("24,002,022.55", 1097),
    2003: ("26,990,272.23", 1319),
    2004: ("30,684,780.53", 1541),
}
KOTA_INDICES = {2002: 1124, 2003: 1346, 2004: 1568}


def main():
    df = pd.read_csv(RAW_CSV)
    corrections = []

    for yr, (correct_val, kab_idx) in ORIGINAL_KAB.items():
        kota_idx = KOTA_INDICES[yr]

        kab_current = df.loc[kab_idx, "value"]
        kota_current = df.loc[kota_idx, "value"]

        # Revert Kab. Bogor to correct PDF value
        df.loc[kab_idx, "value"] = correct_val

        # Null Kota Bogor (garbled extraction, not recoverable from this scan)
        df.loc[kota_idx, "value"] = float("nan")

        print(
            f"  year={yr}: Kab {kab_current} → {correct_val} (reverted to PDF) | "
            f"Kota {kota_current} → NaN (nulled)"
        )

        corrections.append({
            "date": str(date.today()),
            "source_file": "PDRB_2002-2004_wide_v2.csv",
            "fix_id": "B2-revert",
            "description": "Revert B2 swap; null Kota Bogor nominal (unrecoverable scan artifact)",
            "year": yr,
            "row_index_kab": kab_idx,
            "row_index_kota": kota_idx,
            "kab_value_before": kab_current,
            "kab_value_after": correct_val,
            "kota_value_before": kota_current,
            "kota_value_after": "NaN",
            "rationale": (
                f"B2 swap was based on wrong diagnosis. PDF page 12 line shows Kab. Bogor "
                f"(code 01) = {correct_val} million — exactly matching the pre-swap kab value. "
                f"Kota Bogor row is scanner-garbled (character-by-character pdfplumber output); "
                f"assembled parser value is not the real figure. Kab restored from corrections_log "
                f"kab_value_before. Kota nulled — correct value not recoverable from this scan."
            ),
        })

    df.to_csv(RAW_CSV, index=False)
    print(f"\nSaved: {RAW_CSV}")

    with open(LOG_CSV, "a", newline="") as f:
        fieldnames = list(corrections[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(corrections)
    print(f"Logged {len(corrections)} corrections to {LOG_CSV}")


if __name__ == "__main__":
    main()
