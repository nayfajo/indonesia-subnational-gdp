"""
recover_w2c_sumbar.py

Recover the 30 nulled SumBar per-capita 2000-2001 values (W2c) from BPS online data.

Source: BPS Query Builder — Seri 2000 PDRB Per Kapita HB (Juta Rupiah), 2000-2008.
        "Query Builder Result - Sabtu, 08 Agustus 2026 pukul 14.06.10 PDT.csv"

Unit: raw CSV stores values in RUPIAH (table_header says "(RUPIAH)").
      BPS online is in Juta Rupiah → multiply by 1,000,000 to convert.

District matching: by regency_code (unambiguous; two "Solok" entries:
  code 03 = Kab. Solok, code 72 = Kota Solok).

Skipped: name_flag='#)' rows (pre-split aggregate, not district data).

Fix_id: W2c_recover
"""

from pathlib import Path
import pandas as pd
import csv
from datetime import date

RAW = Path("pipeline_out/full_runs/csvs/PDRB-capita_2000-2001_wide_v2.csv")
LOG = Path("pipeline_out/full_runs/corrections_log.csv")
ONLINE = Path("Query Builder Result - Sabtu, 08 Agustus 2026 pukul 14.06.10 PDT.csv")


def juta_to_bps_string(juta):
    """Convert juta rupiah (float) to BPS string format in rupiah."""
    rupiah = round(float(juta) * 1_000_000, 2)
    int_part = int(rupiah)
    dec_part = round((rupiah - int_part) * 100)
    int_str = f"{int_part:,}".replace(",", ".")
    return f"{int_str},{dec_part:02d}"


# regency_code → (online_district_name, bps_name_hint)
# Maps short regency code (from CSV, no leading zeros) to online index
REGENCY_ONLINE_MAP = {
    "01": "Kab. Kepulauan Mentawai",
    "02": "Kab. Pesisir Selatan",
    "03": "Kab. Solok",
    "04": "Kab. Sijunjung",
    "05": "Kab. Tanah Datar",
    "06": "Kab. Padang Pariaman",
    "07": "Kab. Agam",
    "08": "Kab. Lima Puluh Kota",
    "09": "Kab. Pasaman",
    "71": "Kota Padang",
    "72": "Kota Solok",
    "73": "Kota Sawahlunto",
    "74": "Kota Padang Panjang",
    "75": "Kota Bukittinggi",
    "76": "Kota Payakumbuh",
}

# Load BPS online data (Seri 2000 HB, juta rupiah)
online_raw = pd.read_csv(ONLINE, skiprows=2, header=0)
online_raw = online_raw.rename(columns={"Unnamed: 0": "district_online"})
online_raw = online_raw.dropna(subset=["district_online"])
online_raw = online_raw[~online_raw["district_online"].str.contains("Provinsi", na=False)]

# Build lookup: district_online → {year → juta_value}
online_lookup = {}
for _, row in online_raw.iterrows():
    name = str(row["district_online"]).strip()
    online_lookup[name] = {"2000": row["2000"], "2001": row["2001"]}

# Load raw CSV
df = pd.read_csv(RAW, dtype=str)

corrections = []
recovered = 0
skipped = 0

for idx, row in df.iterrows():
    # Only SumBar, years 2000-2001
    if not str(row.get("province_name", "")).upper().find("SUMATERA BARAT") >= 0:
        continue
    yr = str(row.get("year", "")).strip()
    if yr not in ("2000", "2001"):
        continue
    # Skip pre-split aggregates
    if str(row.get("name_flag", "")).strip() == "#)":
        skipped += 1
        continue
    # Skip if not nulled
    val = str(row.get("value", "")).strip()
    if val not in ("", "nan"):
        skipped += 1
        continue

    # Identify district via regency_code
    code = str(row.get("regency_code", "")).strip()
    online_name = REGENCY_ONLINE_MAP.get(code)
    if online_name is None:
        print(f"  WARNING: no online mapping for regency_code={code!r} ({row['region_name_raw']})")
        skipped += 1
        continue

    juta_val = online_lookup.get(online_name, {}).get(yr)
    if juta_val is None or str(juta_val).strip() in ("", "nan", "-"):
        print(f"  WARNING: no online value for {online_name} {yr}")
        skipped += 1
        continue

    bps_str = juta_to_bps_string(juta_val)
    df.loc[idx, "value"] = bps_str
    recovered += 1

    corrections.append({
        "date": str(date.today()),
        "source_file": RAW.name,
        "fix_id": "W2c_recover",
        "description": (
            f"{row['region_name_raw']} per-capita {yr} recovered from BPS online "
            f"({online_name}, Seri 2000 HB) [row {idx}]"
        ),
        "year": yr,
        "row_index_kab": idx,
        "row_index_kota": "",
        "kab_value_before": "",
        "kab_value_after": bps_str,
        "kota_value_before": "",
        "kota_value_after": "",
        "rationale": (
            f"BPS Query Builder (Seri 2000 HB per-capita, juta rupiah): "
            f"{online_name} {yr} = {juta_val} juta = {bps_str} rupiah. "
            "Original value was nulled (W2c: BPS pub used ~62K denominator for all SumBar districts). "
            "Recovery source: BPS online nominal per-capita is equivalent regardless of series."
        ),
    })

df.to_csv(RAW, index=False)
print(f"Recovered {recovered} values, skipped {skipped}")

if corrections:
    with open(LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(corrections[0].keys()))
        writer.writerows(corrections)
    print(f"Logged {len(corrections)} W2c_recover entries")
