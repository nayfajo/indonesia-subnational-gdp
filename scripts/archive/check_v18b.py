import pandas as pd
from pathlib import Path
import re

# --- 1. Check for floating-point dust in actual CSV text ---
print("=== Floating-point dust in CSV text ===")
dust_total = 0
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    text = fp.read_text()
    # Find value_standardized column values that have >2 decimal places in text
    # Look for any number like 123456789.123456 (more than 2dp)
    dust = re.findall(r'\b\d+\.\d{3,}\b', text)
    if dust:
        print(f"  {fp.name}: {len(dust)} cells with >2dp values, e.g. {dust[:3]}")
        dust_total += len(dust)

if dust_total == 0:
    print("  NONE — rounding eliminated all floating-point dust in CSV output ✓")

# --- 2. Sulawesi Utara in 2011-2013 specifically ---
print("\n=== Sulawesi Utara in PDRB_2011-2013 (checking unit fix) ===")
df = pd.read_csv("pipeline_out/standardized/PDRB_2011-2013_wide_v2.csv")
sulut = df[df["province_name_raw"].str.upper().str.strip().str.contains("SULAWESI UTARA", na=False)]
print(f"Total Sulawesi Utara rows: {len(sulut)}")
print(f"Units: {sulut['unit'].value_counts().to_dict()}")
print(f"unit_from_english: {sulut['unit_from_english'].value_counts().to_dict()}")
data_sulut = sulut[sulut["is_data_row"] == True].copy()
data_sulut["vs"] = pd.to_numeric(data_sulut["value_standardized"], errors="coerce")
print(f"\nData rows: {len(data_sulut)}, value_standardized range:")
print(f"  min={data_sulut['vs'].min():.0f}, max={data_sulut['vs'].max():.0f}")
print(f"  Suspicious small (<1B) total PDRB: {(data_sulut['vs'] < 1e9).sum()}")
bad = data_sulut[data_sulut["vs"] < 1e9]
if len(bad):
    print(bad[["province_name_raw","region_name_raw","year","unit","unit_from_english","value","value_standardized"]].head(10).to_string())

# --- 3. Check PDRB-capita_2011-2013 for same ---
print("\n=== Sulawesi Utara in PDRB-capita_2011-2013 ===")
df2 = pd.read_csv("pipeline_out/standardized/PDRB-capita_2011-2013_wide_v2.csv")
sulut2 = df2[df2["province_name_raw"].str.upper().str.strip().str.contains("SULAWESI UTARA", na=False)]
print(f"Total Sulawesi Utara rows: {len(sulut2)}")
print(f"Units: {sulut2['unit'].value_counts().to_dict()}")
print(f"unit_from_english: {sulut2['unit_from_english'].value_counts().to_dict()}")

# --- 4. Confirm all name_flags are 1) or #) ---
print("\n=== name_flag values across all files ===")
all_dfs = []
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    d = pd.read_csv(fp, usecols=["name_flag"])
    all_dfs.append(d)
flags_df = pd.concat(all_dfs)
print(flags_df["name_flag"].value_counts(dropna=False).head(10).to_string())
unexpected = flags_df["name_flag"].dropna()
unexpected = unexpected[~unexpected.isin(["1)", "#)"])]
print(f"\nUnexpected flag values (not 1) or #)): {len(unexpected)}")
if len(unexpected):
    print(unexpected.value_counts().to_string())
