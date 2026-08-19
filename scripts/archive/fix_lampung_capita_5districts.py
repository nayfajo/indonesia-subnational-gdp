"""
fix_lampung_capita_5districts.py

The BPS per-capita publication PDRB-capita_2017-2019 (Table 144) has wrong values
for 5 Lampung districts in 2017-2019. The other 10 districts match the BPS online
database exactly, confirming these 5 are BPS publication errors (wrong population
denominators used in the per-capita calculation).

Source for correct values: BPS Lampung online database (lampung.bps.go.id)
  — PDRB Per Kapita Atas Dasar Harga Berlaku, Ribu Rupiah, 2017-2019

Districts affected (PDF wrong → BPS online correct):
  Kab. Mesuji (11):            54,804/58,667/62,056 → 45,089/48,659/51,934
  Kab. Tulang Bawang Barat (12): 49,746/53,497/57,104 → 36,611/39,287/41,860
  Kab. Pesisir Barat (13):     14,666/15,790/17,144 → 25,881/27,854/30,246
  Kota Bandar Lampung (71):    328,350/355,198/382,028 → 49,298/52,824/56,218
  Kota Metro (72):             5,396/5,700/6,002 → 33,635/35,671/37,683

Kota Bandar Lampung and Kota Metro were already nulled by fix W2; this script
restores them with correct values.

Years 2020-2021 in this publication are also wrong for these districts but are
overridden by the higher-priority 2020-2022 publication in build_panel.
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW_CSV = Path("pipeline_out/full_runs/csvs/PDRB-capita_2017-2019_wide_v2.csv")
LOG_CSV = Path("pipeline_out/full_runs/corrections_log.csv")

CORRECT = {
    # (region_name_raw, year): correct_value_string (Indonesian format)
    ("Kab. Mesuji",            2017): "45.089",
    ("Kab. Mesuji",            2018): "48.659",
    ("Kab. Mesuji",            2019): "51.934",
    ("Kab. Tulang Bawang Barat", 2017): "36.611",
    ("Kab. Tulang Bawang Barat", 2018): "39.287",
    ("Kab. Tulang Bawang Barat", 2019): "41.860",
    ("Kab. Pesisir Barat",     2017): "25.881",
    ("Kab. Pesisir Barat",     2018): "27.854",
    ("Kab. Pesisir Barat",     2019): "30.246",
    ("Kota Bandar Lampung",    2017): "49.298",
    ("Kota Bandar Lampung",    2018): "52.824",
    ("Kota Bandar Lampung",    2019): "56.218",
    ("Kota Metro",             2017): "33.635",
    ("Kota Metro",             2018): "35.671",
    ("Kota Metro",             2019): "37.683",
}


def main():
    df = pd.read_csv(RAW_CSV)
    corrections = []

    for (name, year), correct_val in CORRECT.items():
        mask = (
            (df["province_name"] == "LAMPUNG")
            & (df["region_name_raw"] == name)
            & (df["year"] == year)
        )
        assert mask.sum() == 1, f"Expected 1 row for {name} {year}, got {mask.sum()}"
        idx = df.index[mask][0]
        old_val = df.loc[idx, "value"]
        df.loc[idx, "value"] = correct_val

        print(f"  {name} {year}: {repr(str(old_val))} → {correct_val}")
        corrections.append({
            "date": str(date.today()),
            "source_file": "PDRB-capita_2017-2019_wide_v2.csv",
            "fix_id": "W2b",
            "description": f"Lampung per-capita BPS publication error: {name} {year}",
            "year": year,
            "row_index_kab": idx,
            "row_index_kota": "",
            "kab_value_before": str(old_val),
            "kab_value_after": correct_val,
            "kota_value_before": "",
            "kota_value_after": "",
            "rationale": (
                "BPS per-capita 2017-2019 publication printed wrong per-capita for 5 "
                "Lampung districts. Other 10 districts match BPS online exactly, "
                "confirming these 5 have wrong population denominators in BPS's "
                "calculation system for this print run. Correct values from: "
                "lampung.bps.go.id — PDRB Per Kapita HB (Ribu Rp), 2017-2019."
            ),
        })

    df.to_csv(RAW_CSV, index=False)
    print(f"\nSaved: {RAW_CSV}")

    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(corrections[0].keys()))
        writer.writerows(corrections)
    print(f"Logged {len(corrections)} corrections")


if __name__ == "__main__":
    main()
