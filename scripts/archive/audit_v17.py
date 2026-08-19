import pandas as pd
import numpy as np
from pathlib import Path

STAND_DIR = Path("pipeline_out/standardized")

all_data = []
for fp in sorted(STAND_DIR.glob("*.csv")):
    df = pd.read_csv(fp)
    df["source_file"] = fp.name
    all_data.append(df)

df = pd.concat(all_data, ignore_index=True)
data = df[df["is_data_row"] == True].copy()
data["value_standardized"] = pd.to_numeric(data["value_standardized"], errors="coerce")

is_capita = data["source_file"].str.contains("capita")
is_total  = ~is_capita

print("=== BUG A -- TOO_LARGE_CAPITA (>2B rupiah/capita) ===")
bug_a = data[is_capita & (data["value_standardized"] > 2e9)]
print(f"  {len(bug_a)} rows  (expect 0)")
if len(bug_a):
    print(bug_a[["source_file","province_name_raw","year","value_standardized","unit"]].to_string())

print("\n=== BUG B -- NEGATIVE values ===")
bug_b = data[data["value_standardized"] < 0]
print(f"  {len(bug_b)} rows  (expect 0)")
if len(bug_b):
    print(bug_b[["source_file","region_name_raw","year","value_standardized"]].to_string())

print("\n=== BUG C -- TOO_SMALL_CAPITA (<1M rupiah/capita) ===")
bug_c = data[is_capita & data["value_standardized"].notna() & (data["value_standardized"] < 1e6)]
print(f"  {len(bug_c)} rows  (expect 0)")
if len(bug_c):
    print(bug_c[["source_file","region_name_raw","year","value_standardized","unit"]].head(20).to_string())

print("\n=== BUG D -- TOO_SMALL_TOTAL (<1B rupiah total) ===")
bug_d = data[is_total & data["value_standardized"].notna() & (data["value_standardized"] < 1e9)]
print(f"  {len(bug_d)} rows  (expect: phantom block only ~769)")
if len(bug_d):
    print(bug_d.groupby("source_file").size().to_string())

print("\n=== BUG D check -- unit_from_english triggered ===")
if "unit_from_english" in df.columns:
    fallback_used = data[
        data["unit_from_english"].notna() &
        (data["unit_from_english"] != data["unit"])
    ]
    print(f"  Rows where English unit differs from final unit: {len(fallback_used)}")
    if len(fallback_used):
        print(fallback_used.groupby(["source_file","unit","unit_from_english"]).size().to_string())
else:
    print("  unit_from_english column not found")
