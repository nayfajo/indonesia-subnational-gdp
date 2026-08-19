"""
fix_p7_kota_bogor.py

P7: Fill nulled Kota Bogor nominal 2002-2004 from PDF visual read,
    and correct garbled 2005-2006 values in the same raw CSV.

Source: PDRB_2002-2004.pdf, Jawa Barat nominal table (Jutaan Rupiah),
        row 71. Bogor (Kota Bogor). Values read directly from PDF by user.

This file uses Western number format (comma=thousands, period=decimal)
unlike other PDRB CSVs which use BPS format (period=thousands, comma=decimal).

2005-2006 are also corrected even though the panel already uses the 2005-2007
publication for those years (higher source_priority). Correcting keeps the
raw CSV internally consistent.

Kab. Bogor (code 1) values are already correct and untouched.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW = Path("pipeline_out/full_runs/csvs/PDRB_2002-2004_wide_v2.csv")
LOG = Path("pipeline_out/full_runs/corrections_log.csv")

# PDF-verified values for Kota Bogor nominal (Jutaan Rupiah), code 71
PDF_VALUES = {
    "2002": "3,459,398.26",
    "2003": "3,915,569.13",
    "2004": "4,515,746.82",
    "2005": "5,391,918.89",   # garbled in CSV as 47,596,588.89
    "2006": "6,357,742.09",   # garbled in CSV as 65,077,543.54
}

df = pd.read_csv(RAW, dtype=str)

mask = (
    (df["regency_code"].astype(str).str.strip() == "71.0") &
    (df["region_name_raw"].str.upper() == "BOGOR") &
    (df["table_header_raw"].str.contains("BERLAKU", case=False, na=False)) &
    (df["year"].astype(str).isin(PDF_VALUES.keys()))
)

corrections = []
for idx in df.index[mask]:
    yr = str(df.loc[idx, "year"]).strip()
    old_val = str(df.loc[idx, "value"]).strip()
    new_val = PDF_VALUES[yr]

    if old_val in ("", "nan", "NaN"):
        fix_id = "P7_recover"
        desc = f"Kota Bogor nominal {yr} null filled from PDF visual read [row {idx}]"
    else:
        fix_id = "P7_garble"
        desc = f"Kota Bogor nominal {yr} garbled value corrected from PDF [row {idx}]"

    df.loc[idx, "value"] = new_val
    corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": fix_id,
        "description": desc,
        "year": yr,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": old_val,
        "kab_value_after": new_val,
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            f"Kota Bogor nominal {yr}: PDF PDRB_2002-2004.pdf row 71.Bogor = {new_val} juta rupiah. "
            "2002-2004 were null (OCR failed to parse row). "
            "2005-2006 were garbled (47M/65M juta > Kab.Bogor — physically impossible). "
            "Values read directly from PDF by researcher. "
            "Panel uses 2005-2007 publication for 2005-2006 (higher priority), so only 2002-2004 affect panel output."
        ),
    })

df.to_csv(RAW, index=False)
print(f"Fixed {len(corrections)} Kota Bogor rows")
for c in corrections:
    print(f"  {c['fix_id']} {c['year']}: {c['kab_value_before']!r} → {c['kab_value_after']!r}")

if corrections:
    with open(LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(corrections[0].keys()))
        writer.writerows(corrections)
    print(f"Logged {len(corrections)} corrections")
