"""
Rebuild district_reference.csv to fix silent KAB/KOTA collapses.

For each (province, base_name) pair that has both kabupaten and kota rows in the
post-2008 standardized files, the single collapsed reference row is split into two:
  - one with admin_type=kabupaten, district_id suffix _KAB
  - one with admin_type=kota,      district_id suffix _KOTA

An admin_type column is added to the reference. For unambiguous names it is left null.

Outputs:
  crosswalks/district_reference.csv   (updated in place)
  audits/kab_kota_ambiguous_pairs.csv (the 26 pairs for manual review)
"""

import glob
import pandas as pd

STD_DIR = "standardized/"
REF_PATH = "crosswalks/district_reference.csv"
AUDIT_PATH = "audits/kab_kota_ambiguous_pairs.csv"


def find_kab_kota_pairs(std_dir):
    frames = []
    for f in sorted(glob.glob(std_dir + "*.csv")):
        df = pd.read_csv(f, low_memory=False)
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)

    post2008 = all_df[(all_df["is_data_row"] == True) & (all_df["admin_type"].notna())].copy()

    combos = (
        post2008
        .groupby(["province_name_clean", "region_name_base", "admin_type"])
        .size()
        .reset_index(name="row_count")
    )

    pivot = combos.pivot_table(
        index=["province_name_clean", "region_name_base"],
        columns="admin_type",
        values="row_count",
        fill_value=0,
    ).reset_index()

    pairs = pivot[(pivot.get("kabupaten", 0) > 0) & (pivot.get("kota", 0) > 0)].copy()
    pairs = pairs[["province_name_clean", "region_name_base"]].rename(
        columns={"province_name_clean": "province_canonical"}
    )
    return pairs.reset_index(drop=True)


def rebuild(ref_path, pairs):
    ref = pd.read_csv(ref_path)

    pair_set = set(zip(pairs["province_canonical"], pairs["region_name_base"]))

    is_ambiguous = ref.apply(
        lambda r: (r["province_canonical"], r["district_name_2000"]) in pair_set, axis=1
    )

    clean_rows = ref[~is_ambiguous].copy()
    clean_rows["admin_type"] = None

    split_rows = []
    for _, orig in ref[is_ambiguous].iterrows():
        for atype, suffix in [("kabupaten", "_KAB"), ("kota", "_KOTA")]:
            row = orig.copy()
            row["district_id"] = orig["district_id"] + suffix
            row["admin_type"] = atype
            split_rows.append(row)

    split_df = pd.DataFrame(split_rows)

    rebuilt = pd.concat([clean_rows, split_df], ignore_index=True)
    rebuilt = rebuilt.sort_values(["province_canonical", "district_name_2000", "admin_type"]).reset_index(drop=True)
    rebuilt["district_num"] = range(1, len(rebuilt) + 1)

    col_order = [
        "district_id", "district_num", "province_canonical", "district_name_2000",
        "admin_type", "bps_code", "multi_province_flag", "notes",
    ]
    rebuilt = rebuilt[col_order]
    return rebuilt


def main():
    print("Finding KAB/KOTA pairs from post-2008 standardized files...")
    pairs = find_kab_kota_pairs(STD_DIR)
    print(f"  {len(pairs)} ambiguous pairs found")

    print("Rebuilding district_reference.csv...")
    rebuilt = rebuild(REF_PATH, pairs)

    orig = pd.read_csv(REF_PATH)
    print(f"  Original rows: {len(orig)}")
    print(f"  Rebuilt rows:  {len(rebuilt)}  (+{len(rebuilt) - len(orig)} from splits)")

    rebuilt.to_csv(REF_PATH, index=False)
    print(f"  Written: {REF_PATH}")

    pairs.to_csv(AUDIT_PATH, index=False)
    print(f"  Written: {AUDIT_PATH}")

    print("\nAmbiguous pairs (pre-2008 rows with these base names need manual review):")
    print(pairs.to_string(index=False))


if __name__ == "__main__":
    main()
