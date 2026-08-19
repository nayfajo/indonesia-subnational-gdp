import pandas as pd
from pathlib import Path

all_data = []
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    df = pd.read_csv(fp)
    df["_file"] = fp.name
    all_data.append(df)
df = pd.concat(all_data, ignore_index=True)

eng_rupiah = df[df["unit_from_english"] == "rupiah"].copy()
eng_rupiah["value_standardized"] = pd.to_numeric(eng_rupiah["value_standardized"], errors="coerce")

print(f"Total rows where unit_from_english='rupiah': {len(eng_rupiah)}")
print("\nBreakdown by file and Indonesian unit:")
print(eng_rupiah.groupby(["_file", "unit"]).size().to_string())

# Rows where Indonesian unit is NOT rupiah — English extraction was weaker
not_rupiah_ind = eng_rupiah[eng_rupiah["unit"].fillna("") != "rupiah"]
print(f"\nRows where unit_from_english='rupiah' but Indonesian unit is something else: {len(not_rupiah_ind)}")
if len(not_rupiah_ind):
    print(not_rupiah_ind.groupby(["_file","unit"]).size().to_string())
    print("\nDistinct English headers causing this:")
    print(not_rupiah_ind[["_file","table_header_english","unit","unit_from_english"]].drop_duplicates("table_header_english").to_string())

# Rows where BOTH are rupiah but value looks too large (fallback gave wrong answer)
both_rupiah = eng_rupiah[eng_rupiah["unit"].fillna("") == "rupiah"]
print(f"\nRows where both Indonesian and English say rupiah: {len(both_rupiah)}")
large = both_rupiah[both_rupiah["value_standardized"] > 1e9]
print(f"  Of those, value_standardized > 1B (suspicious for bare rupiah): {len(large)}")
if len(large):
    print(large.groupby("_file").size().to_string())
    print(large[["_file","province_name_raw","region_name_raw","year","value","value_standardized","table_header_raw","table_header_english"]].head(10).to_string())
