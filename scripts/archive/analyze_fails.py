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

print(f"Total oil-flagged rows (excl #)): {len(oil_rows)}")

results = []
for idx, row in oil_rows.iterrows():
    gidx = row["_global_idx"]
    above = df[(df["_global_idx"] == gidx - 1) & (df["_file"] == row["_file"])]
    if above.empty:
        results.append({"idx": gidx, "flag": row["name_flag"], "reason": "NO_ROW_ABOVE",
                        "val_smaller": False, "flag_x": row["name_flag"] == "x)"})
        continue
    above = above.iloc[0]
    same_region = (str(row["region_name_raw"]).strip().upper() ==
                   str(above["region_name_raw"]).strip().upper())
    same_year = str(row["year"]) == str(above["year"])
    above_unflagged = pd.isna(above["name_flag"]) or str(above["name_flag"]).strip() in ("", "nan")
    vs_row   = pd.to_numeric(row["value_standardized"],   errors="coerce")
    vs_above = pd.to_numeric(above["value_standardized"], errors="coerce")
    val_smaller = bool(pd.notna(vs_row) and pd.notna(vs_above) and vs_row < vs_above)

    ok = same_region and same_year and above_unflagged
    if not ok:
        reason_parts = []
        if not same_region:
            reason_parts.append(f"OCR_NAME_MISMATCH")
        if not same_year:
            reason_parts.append("YEAR_MISMATCH")
        if not above_unflagged:
            reason_parts.append("ABOVE_ALSO_FLAGGED")
        results.append({
            "idx": gidx,
            "flag": row["name_flag"],
            "reason": "|".join(reason_parts),
            "val_smaller": val_smaller,
            "flag_x": row["name_flag"] == "x)",
            "above_region": str(above["region_name_raw"])
        })

fails_df = pd.DataFrame(results)
print(f"\nTotal FAILS: {len(fails_df)}")

ocr_only   = fails_df["reason"] == "OCR_NAME_MISMATCH"
consec     = fails_df["reason"].str.contains("ABOVE_ALSO_FLAGGED")
yr_miss    = fails_df["reason"].str.contains("YEAR_MISMATCH")
x_rows     = fails_df["flag_x"]

print(f"\nBreakdown:")
print(f"  OCR name mismatch only:          {ocr_only.sum()}")
print(f"    of which val_smaller=True:     {(ocr_only & fails_df['val_smaller']).sum()}")
print(f"    of which val_smaller=False:    {(ocr_only & ~fails_df['val_smaller']).sum()}")
print(f"  Consecutive flagged rows:        {consec.sum()}")
print(f"    of which val_smaller=False:    {(consec & ~fails_df['val_smaller']).sum()}")
print(f"  Year mismatch:                   {yr_miss.sum()}")
print(f"  x) rows in fails:                {x_rows.sum()}")

# Show the consecutive-flagged rows with val_smaller=False — most suspicious
suspect = fails_df[consec & ~fails_df["val_smaller"]]
print(f"\nMost suspicious (consecutive + NOT val_smaller): {len(suspect)}")
if len(suspect):
    print(suspect[["idx","flag","reason","above_region"]].head(20).to_string())

# Show flag breakdown overall
print("\nAll distinct non-#) flag values with counts:")
print(oil_rows["name_flag"].value_counts().to_string())
