import pandas as pd
from pathlib import Path
import numpy as np

all_data = []
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    df = pd.read_csv(fp)
    df["_file"] = fp.name
    all_data.append(df)
df = pd.concat(all_data, ignore_index=True)

# --- 1. Sulawesi Utara check ---
sulut = df[df["province_name_raw"].str.upper().str.strip().isin(
    {"SULAWESI UTARA", "NORTH SULAWESI"}
) if df["province_name_raw"].notna().any() else df["province_name_raw"].isna()]
sulut = df[df["province_name_raw"].str.upper().str.strip().str.contains("SULAWESI UTARA", na=False)]
print(f"=== Sulawesi Utara rows: {len(sulut)}")
if len(sulut):
    print(sulut[["_file","year","unit","unit_multiplier","unit_from_english","value","value_standardized"]].head(10).to_string())
    print(f"\n  Units seen: {sulut['unit'].value_counts().to_dict()}")
    print(f"  unit_from_english seen: {sulut['unit_from_english'].value_counts().to_dict()}")

# --- 2. x) normalization ---
print("\n=== name_flag check post-normalization ===")
flags = df["name_flag"].dropna().value_counts()
print(flags.to_string())

# Confirm no x) remains
x_rows = df[df["name_flag"].astype(str).str.strip() == "x)"]
print(f"\nx) rows remaining: {len(x_rows)}")

# Check is_pre_split_aggregate and oil_excluded for former x) rows
# (They should now be classified as pre-split, not oil-excluded)
# We can check via province=Kalimantan Barat, file=2011-2013
kalbar_2013 = df[
    df["_file"].str.contains("2011-2013") &
    df["province_name_raw"].str.upper().str.strip().str.contains("KALIMANTAN BARAT", na=False)
]
print(f"\n=== Kalimantan Barat in 2011-2013 (should show Mempawah as pre-split): {len(kalbar_2013)}")
if len(kalbar_2013):
    mempawah = kalbar_2013[kalbar_2013["region_name_raw"].str.contains("Mempawah", case=False, na=False)]
    print(mempawah[["_file","region_name_raw","year","name_flag","oil_excluded","is_pre_split_aggregate","value_standardized"]].to_string())

# --- 3. Rounding check ---
print("\n=== Rounding check (should be no >2dp values) ===")
data = df[df["is_data_row"] == True].copy()
data["vs"] = pd.to_numeric(data["value_standardized"], errors="coerce")
# Check for floating-point dust
def has_extra_decimals(v):
    if pd.isna(v):
        return False
    s = f"{v:.10f}".rstrip("0")
    dot_pos = s.find(".")
    if dot_pos == -1:
        return False
    return len(s) - dot_pos - 1 > 2

extra_dp = data["vs"].apply(has_extra_decimals)
print(f"  Rows with >2dp floating-point dust: {extra_dp.sum()} (expect 0)")

# Sample any that slipped through
if extra_dp.any():
    print(data[extra_dp][["_file","region_name_raw","year","vs"]].head(5).to_string())
