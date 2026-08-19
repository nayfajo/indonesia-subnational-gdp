# scripts/build_district_reference.py
"""
Builds crosswalks/district_reference.csv — the stable ID spine of the panel.

One row per 2000-vintage district. Columns:
  district_id       : string key  e.g. ACEH_BANDA_ACEH
  district_num      : sequential integer for regression use
  province_canonical: from province_crosswalk
  district_name_2000: 2000-vintage district name (parent for split units)
  bps_code          : BPS Kode Wilayah (4-digit PPKK) — manually enriched
  admin_type        : kabupaten / kota — manually enriched for Kab/Kota pairs
  multi_province_flag: True if this district appears under >1 province in
                       the standardized files (needs manual review)
  notes             : any flags worth knowing

Does NOT modify any standardized files. Review output before running
harmonize_regions.py.

WARNING — MANUAL ENRICHMENT GUARD
----------------------------------
crosswalks/district_reference.csv has been manually enriched (2026-08-13):
  - bps_code   : all 423 rows filled via a one-off enrichment script
                 (fill_bps_codes.py, no longer retained) that looked codes
                 up against crosswalks/bps_code_reference.csv;
                 18 rows assigned by hand (pre-split parents, renames,
                 province migrations); 1 row (RIAU_KEPULAUAN_RIAU) has a
                 4-step code chain documented in notes.
  - admin_type : filled for the ~52 Kab/Kota name-collision rows.
  - notes      : provenance notes for all manual assignments.

Re-running this script will OVERWRITE those enrichments with a fresh
skeleton (bps_code = "TBD" everywhere). Do NOT re-run unless you intend
to redo the enrichment from scratch. If you must regenerate the skeleton
(e.g. after adding new source PDFs), preserve the enriched columns first:

    python3 -c "
    import pandas as pd
    ref = pd.read_csv('crosswalks/district_reference.csv')
    ref[['district_id','bps_code','admin_type','notes']].to_csv(
        'crosswalks/district_reference_bps_backup.csv', index=False)
    print('Backup written.')
    "

Then after re-running, re-join on district_id to restore enriched columns.
"""

from pathlib import Path
import pandas as pd
import re
import sys

STANDARDIZED_DIR = Path("standardized")
CROSSWALK_DIR    = Path("crosswalks")
OUT_FILE         = CROSSWALK_DIR / "district_reference.csv"

# ── Manual enrichment guard ───────────────────────────────────────────────────
if OUT_FILE.exists():
    _existing = pd.read_csv(OUT_FILE, dtype=str)
    _enriched = (_existing.get('bps_code', pd.Series(dtype=str))
                           .fillna('TBD')
                           .ne('TBD')
                           .any())
    if _enriched:
        print("=" * 70)
        print("ABORT: district_reference.csv has been manually enriched.")
        print("Re-running will overwrite bps_code, admin_type, and notes.")
        print("Read the WARNING in this script's docstring before proceeding.")
        print("To bypass: delete or rename the existing file first.")
        print("=" * 70)
        sys.exit(1)


def make_district_id(province, district):
    """PROVINCE_DISTRICT_NAME — uppercase, spaces to underscores, strip noise."""
    def clean(s):
        s = str(s).upper().strip()
        s = re.sub(r'[^\w\s]', '', s)   # remove punctuation
        s = re.sub(r'\s+', '_', s)       # spaces to underscores
        return s
    return f"{clean(province)}_{clean(district)}"


def main():
    print("=" * 70)
    print("BUILDING DISTRICT REFERENCE TABLE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Load crosswalks
    # ------------------------------------------------------------------
    prov_xwalk = pd.read_csv(CROSSWALK_DIR / "province_crosswalk.csv")
    prov_map = dict(zip(
        prov_xwalk["province_name_clean"],
        prov_xwalk["province_canonical"]
    ))

    split_conc = pd.read_csv(CROSSWALK_DIR / "split_concordance.csv")

    # Any child that already appears in the 2000-2003 publication files was
    # trackable as a separate unit from 2000 onward (e.g. Kota Cimahi appeared
    # before its formal autonomy in 2001). Treat these as own 2000-vintage units.
    early_files = sorted(STANDARDIZED_DIR.glob("*2000*2003*.csv")) + \
                  sorted(STANDARDIZED_DIR.glob("*1996*1999*.csv"))
    early_bases = set()
    for fp in early_files:
        df = pd.read_csv(fp, usecols=["region_name_base", "is_data_row"])
        early_bases.update(
            df[df["is_data_row"] == True]["region_name_base"].dropna().unique()
        )

    present_in_early = split_conc["child_base"].isin(early_bases)
    excluded = split_conc[present_in_early]["child_base"].tolist()
    if excluded:
        print(f"\nChildren already in 2000-2003 data — kept as own units ({len(excluded)}):")
        for c in excluded:
            print(f"  {c}")

    # child_base → parent_base_2000 (only for children NOT already in early data)
    child_to_parent = dict(zip(
        split_conc.loc[~present_in_early, "child_base"],
        split_conc.loc[~present_in_early, "parent_base_2000"]
    ))

    # ------------------------------------------------------------------
    # Load all data rows from standardized files
    # ------------------------------------------------------------------
    rows = []
    for fp in sorted(STANDARDIZED_DIR.glob("*.csv")):
        df = pd.read_csv(fp, usecols=[
            "region_name_base", "province_name_clean", "is_data_row"
        ])
        rows.append(df[df["is_data_row"] == True])

    panel = pd.concat(rows, ignore_index=True)

    # Apply province crosswalk
    panel["province_canonical"] = panel["province_name_clean"].map(prov_map)
    unmapped = panel[panel["province_canonical"].isna()]["province_name_clean"].unique()
    if len(unmapped):
        print(f"WARNING: {len(unmapped)} province_name_clean values not in crosswalk:")
        for u in unmapped:
            print(f"  {u}")

    # ------------------------------------------------------------------
    # Resolve each region_name_base to its 2000-vintage identity
    # ------------------------------------------------------------------
    panel["district_name_2000"] = panel["region_name_base"].map(
        lambda x: child_to_parent.get(x, x)
    )

    # ------------------------------------------------------------------
    # Collapse to unique (district_name_2000, province_canonical) pairs
    # ------------------------------------------------------------------
    unique_pairs = (
        panel[["district_name_2000", "province_canonical"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["province_canonical", "district_name_2000"])
    )

    # Flag districts appearing under more than one province
    province_counts = (
        unique_pairs.groupby("district_name_2000")["province_canonical"]
        .nunique()
        .reset_index()
        .rename(columns={"province_canonical": "n_provinces"})
    )
    multi_prov = set(
        province_counts[province_counts["n_provinces"] > 1]["district_name_2000"]
    )

    print(f"\nDistricts appearing under >1 province: {len(multi_prov)}")
    if multi_prov:
        for d in sorted(multi_prov):
            provs = unique_pairs[unique_pairs["district_name_2000"] == d][
                "province_canonical"
            ].tolist()
            print(f"  {d}: {provs}")

    # For multi-province districts, keep the most frequent province assignment
    prov_freq = (
        panel[["district_name_2000", "province_canonical"]]
        .dropna()
        .groupby(["district_name_2000", "province_canonical"])
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
        .drop_duplicates(subset=["district_name_2000"])
        [["district_name_2000", "province_canonical"]]
    )

    # ------------------------------------------------------------------
    # Build reference table
    # ------------------------------------------------------------------
    ref = prov_freq.sort_values(
        ["province_canonical", "district_name_2000"]
    ).reset_index(drop=True)

    ref["district_num"] = ref.index + 1

    ref["district_id"] = ref.apply(
        lambda r: make_district_id(r["province_canonical"], r["district_name_2000"]),
        axis=1
    )

    # Resolve name-variant collisions: same cleaned ID, different raw names
    # (e.g. PARE-PARE vs PAREPARE). Keep the most frequent variant per ID.
    id_counts = (
        panel[["district_name_2000", "province_canonical"]]
        .dropna()
        .groupby(["district_name_2000", "province_canonical"])
        .size()
        .reset_index(name="n")
    )
    id_counts["district_id"] = id_counts.apply(
        lambda r: make_district_id(r["province_canonical"], r["district_name_2000"]),
        axis=1
    )
    # For each district_id, keep the district_name_2000 with most observations
    best_name = (
        id_counts.sort_values("n", ascending=False)
        .drop_duplicates(subset=["district_id"])
        [["district_id", "district_name_2000"]]
        .rename(columns={"district_name_2000": "district_name_canonical"})
    )
    ref = ref.merge(best_name, on="district_id", how="left")

    # Flag where canonical name differs from resolved name (name variant collapsed)
    name_variant_collapsed = ref["district_name_canonical"] != ref["district_name_2000"]

    # Use canonical name going forward, drop duplicates that arose from variants
    ref["district_name_2000"] = ref["district_name_canonical"]
    ref = ref.drop(columns=["district_name_canonical"])
    ref = ref.drop_duplicates(subset=["district_id"]).reset_index(drop=True)
    ref["district_num"] = ref.index + 1

    ref["bps_code"] = "TBD"

    ref["multi_province_flag"] = ref["district_name_2000"].isin(multi_prov)

    ref["notes"] = ""
    ref.loc[ref["multi_province_flag"], "notes"] = (
        "appears under >1 province — province assigned by frequency; review needed"
    )
    collapsed = name_variant_collapsed.reindex(ref.index, fill_value=False)
    ref.loc[collapsed, "notes"] = ref.loc[collapsed, "notes"].apply(
        lambda x: (x + "; " if x else "") + "name variant collapsed — add to name_corrections.csv"
    )

    # Reorder columns
    ref = ref[[
        "district_id",
        "district_num",
        "province_canonical",
        "district_name_2000",
        "bps_code",
        "multi_province_flag",
        "notes",
    ]]

    # ------------------------------------------------------------------
    # Sanity checks
    # ------------------------------------------------------------------
    assert ref["district_id"].nunique() == len(ref), \
        "district_id is not unique — check for province+name collisions"
    assert ref["district_num"].nunique() == len(ref), \
        "district_num is not unique"

    # Verify five SCM units are present
    scm_names = ["BANDA ACEH", "CIMAHI", "AMBON", "PALU", "BONE"]
    print("\n=== Five SCM units in reference table ===")
    for name in scm_names:
        row = ref[ref["district_name_2000"] == name]
        if len(row):
            r = row.iloc[0]
            print(f"  {r['district_id']}  |  num={r['district_num']}  |  province={r['province_canonical']}")
        else:
            print(f"  {name}: NOT FOUND")

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    ref.to_csv(OUT_FILE, index=False)

    print(f"\nSaved: {OUT_FILE}")
    print(f"Total districts: {len(ref)}")
    print(f"Provinces:        {ref['province_canonical'].nunique()}")
    print(f"Multi-province flags: {ref['multi_province_flag'].sum()}")


if __name__ == "__main__":
    main()
