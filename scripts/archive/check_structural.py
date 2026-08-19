import pandas as pd
from pathlib import Path
import numpy as np

all_data = []
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    df = pd.read_csv(fp)
    df["_file"] = fp.name
    df["_orig_idx"] = range(len(df))
    all_data.append(df)
df = pd.concat(all_data, ignore_index=True)
df["_global_idx"] = range(len(df))

flag_col = df["name_flag"].astype(str).str.strip()
oil_rows = df[
    df["name_flag"].notna() &
    flag_col.ne("") &
    flag_col.ne("nan") &
    flag_col.ne("#)")
].copy()

print(f"Total oil-flagged rows to check: {len(oil_rows)}")

results = []
for idx, row in oil_rows.iterrows():
    gidx = row["_global_idx"]
    # Check the row immediately above in the same file
    above = df[(df["_global_idx"] == gidx - 1) & (df["_file"] == row["_file"])]
    if above.empty:
        results.append({"idx": gidx, "file": row["_file"], "flag": row["name_flag"],
                        "region": row["region_name_raw"], "year": row["year"],
                        "check": "NO_ROW_ABOVE"})
        continue

    above = above.iloc[0]
    same_region = (str(row["region_name_raw"]).strip().upper() ==
                   str(above["region_name_raw"]).strip().upper())
    same_year   = row["year"] == above["year"]
    above_unflagged = pd.isna(above["name_flag"]) or str(above["name_flag"]).strip() in ("", "nan")

    vs_row   = pd.to_numeric(row["value_standardized"],   errors="coerce")
    vs_above = pd.to_numeric(above["value_standardized"], errors="coerce")
    val_smaller = (pd.notna(vs_row) and pd.notna(vs_above) and vs_row < vs_above)

    ok = same_region and same_year and above_unflagged
    status = "OK" if ok else "FAIL"
    if status == "FAIL" or row["name_flag"] == "x)":
        results.append({
            "idx": gidx, "file": row["_file"], "flag": row["name_flag"],
            "region": row["region_name_raw"], "year": row["year"],
            "same_region": same_region, "same_year": same_year,
            "above_unflagged": above_unflagged, "val_smaller": val_smaller,
            "above_region": above["region_name_raw"], "check": status
        })

if not results:
    print("ALL oil-flagged rows pass structural test (immediate paired sub-row below same district)")
else:
    fail_df = pd.DataFrame(results)
    fails = fail_df[fail_df["check"] == "FAIL"]
    xrows = fail_df[fail_df["flag"] == "x)"]
    print(f"\nFAILS: {len(fails)}")
    if len(fails):
        print(fails.to_string())
    print(f"\nx) rows detail:")
    print(xrows[["file","flag","region","year","same_region","same_year","above_unflagged","val_smaller","above_region"]].to_string())
