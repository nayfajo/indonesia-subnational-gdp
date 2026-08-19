import pandas as pd
from pathlib import Path

all_data = []
for fp in sorted(Path("pipeline_out/standardized").glob("*.csv")):
    df = pd.read_csv(fp)
    df["_file"] = fp.name
    all_data.append(df)
df = pd.concat(all_data, ignore_index=True)

flag_col = df["name_flag"].astype(str).str.strip()
flags = df[
    df["name_flag"].notna() &
    flag_col.ne("") &
    flag_col.ne("nan") &
    flag_col.ne("#)")
].copy()

print("Non-#) name_flag values by file:")
print(flags.groupby(["_file", "name_flag"]).size().to_string())

print("\nAll distinct non-#) flag values seen:")
print(sorted(flags["name_flag"].astype(str).str.strip().unique()))

print("\nFiles with non-#) flags — sample page numbers for PDF spot-check:")
for f, grp in flags.groupby("_file"):
    pages = sorted(grp["page_number"].dropna().astype(int).unique())[:5]
    flag_vals = sorted(grp["name_flag"].astype(str).str.strip().unique())
    print(f"  {f}: flags={flag_vals}  pages={pages}")
