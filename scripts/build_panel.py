# scripts/build_panel.py
"""
Panel assembly stage — v2.

Reads all 20 harmonized CSVs (10 total + 10 capita) and assembles two district-year panels:
  outputs/panel_pdrb_total_2000bounds.csv     — 2000-vintage, SCM-ready (children aggregated to parents)
  outputs/panel_pdrb_total_native.csv   — full granular (all districts, native boundaries)
  outputs/panel_pdrb_capita_2000bounds.csv    — 2000-vintage capita (children dropped, cannot sum)
  outputs/panel_pdrb_capita_native.csv  — full granular capita

Key decisions:
  - D2: two output variants per series (see above)
  - D3: provisional rows KEPT; flagged as is_provisional=True in output
  - S1: child rows summed onto parent's direct row within each source_file (min_count=1);
        standalone child_aggregate emitted only when parent absent from that file
  - S2: NaN value_standardized rows dropped before panel assembly
  - Overlapping publication years: later publication wins (higher source_priority)
  - ambiguous_kab_kota rows: excluded from panel; written to pipeline_out/audits/panel_ambiguous.csv
  - Panel key: (district_id, year, table_type, base_year, oil_excluded)
  - value_standardized is in base rupiah (total) or base rupiah per person (capita)
"""

from pathlib import Path
import pandas as pd

HARMONIZED_DIR = Path("pipeline_out/harmonized")
CROSSWALK_DIR  = Path("crosswalks")
OUTPUT_DIR     = Path("outputs")
AUDIT_DIR      = Path("pipeline_out/audits")
SIDECAR_PATH   = Path("corrections/corrections_applied.csv")

SOURCE_PRIORITY = {
    "PDRB_1998-2001_jabar_banten.csv": 0,  # supplementary gap-filler; lowest priority
    "PDRB_1996-1999.csv":            1,
    "PDRB_2000-2001.csv":           2,
    "PDRB_2002-2004.csv":           3,
    "PDRB_2005-2007.csv":           4,
    "PDRB_2008-2010.csv":           5,
    "PDRB_2011-2013.csv":           6,
    "PDRB_2014-2016.csv":           7,
    "PDRB_2017-2019.csv":           8,
    "PDRB_2020-2022.csv":           9,
    "PDRB_2021-2023.csv":          10,
    "PDRB-capita_1996-1999.csv":     1,
    "PDRB-capita_2000-2001.csv":    2,
    "PDRB-capita_2002-2004.csv":    3,
    "PDRB-capita_2005-2007.csv":    4,
    "PDRB-capita_2008-2010.csv":    5,
    "PDRB-capita_2011-2013.csv":    6,
    "PDRB-capita_2014-2016.csv":    7,
    "PDRB-capita_2017-2019.csv":    8,
    "PDRB-capita_2020-2022.csv":    9,
    "PDRB-capita_2021-2023.csv":   10,
}

TOTAL_FILES = [
    "PDRB_1998-2001_jabar_banten.csv",  # supplementary: Jawa Barat + Banten BERLAKU gap-filler
    "PDRB_1996-1999.csv",
    "PDRB_2000-2001.csv",
    "PDRB_2002-2004.csv",
    "PDRB_2005-2007.csv",
    "PDRB_2008-2010.csv",
    "PDRB_2011-2013.csv",
    "PDRB_2014-2016.csv",
    "PDRB_2017-2019.csv",
    "PDRB_2020-2022.csv",
    "PDRB_2021-2023.csv",
]

CAPITA_FILES = [
    "PDRB-capita_1996-1999.csv",
    "PDRB-capita_2000-2001.csv",
    "PDRB-capita_2002-2004.csv",
    "PDRB-capita_2005-2007.csv",
    "PDRB-capita_2008-2010.csv",
    "PDRB-capita_2011-2013.csv",
    "PDRB-capita_2014-2016.csv",
    "PDRB-capita_2017-2019.csv",
    "PDRB-capita_2020-2022.csv",
    "PDRB-capita_2021-2023.csv",
]

PANEL_KEY = ["district_id", "year", "table_type", "base_year", "oil_excluded"]

PANEL_COLS_V2 = [
    "district_id",
    "district_num",
    "bps_code",
    "province_canonical",
    "district_name_2000",
    "year",
    "is_provisional",
    "table_type",
    "base_year",
    "oil_excluded",
    "value_standardized",
    "is_child_aggregate",
    "unit",
    "unit_multiplier",
    "source_file",
    "source_priority",
    "is_pre_split_aggregate",
    "match_status",
]

PANEL_COLS_FULL = [
    "district_id",
    "district_num",
    "bps_code",
    "province_canonical",
    "district_name_2000",
    "region_name_corrected",
    "admin_type",
    "year",
    "is_provisional",
    "table_type",
    "base_year",
    "oil_excluded",
    "value_standardized",
    "is_post2000_child",
    "parent_district_id",
    "unit",
    "unit_multiplier",
    "source_file",
    "source_priority",
    "is_pre_split_aggregate",
    "match_status",
    "correction_id",
]

AGG_MERGE_KEY = ["source_file", "district_id", "year", "table_type", "base_year", "oil_excluded"]
CHILD_SUM_KEY = ["source_file", "parent_district_id", "year", "table_type", "base_year", "oil_excluded"]


def load_series(file_list):
    """Load and concatenate harmonized files; add source_priority; filter to data rows."""
    frames = []
    for fname in file_list:
        fp = HARMONIZED_DIR / fname
        df = pd.read_csv(fp, low_memory=False)
        df = df[df["is_data_row"].astype(str) == "True"].copy()
        # D3: flag provisional but keep all rows
        df["is_provisional"] = df["year_flag"].notna() & (df["year_flag"].astype(str) != "")
        df["source_file"]     = fname
        df["source_priority"] = SOURCE_PRIORITY[fname]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def dedup_by_priority(df, key):
    """Keep highest source_priority for each panel key."""
    df["source_priority"] = df["source_priority"].astype(int)
    return (
        df.sort_values("source_priority", ascending=False)
        .drop_duplicates(subset=key, keep="first")
        .reset_index(drop=True)
    )


def attach_ref_metadata(df, ref_map):
    """Join district_num, bps_code, province_canonical, district_name_2000 from reference."""
    df["district_num"]       = df["district_id"].map(lambda x: ref_map.get(x, {}).get("district_num"))
    df["bps_code"]           = df["district_id"].map(lambda x: ref_map.get(x, {}).get("bps_code"))
    df["province_canonical"] = df["district_id"].map(
        lambda x: ref_map.get(x, {}).get("province_canonical") or x
    )
    df["district_name_2000"] = df["district_id"].map(lambda x: ref_map.get(x, {}).get("district_name_2000"))
    # For rows where district_id already had province_canonical from harmonize, preserve it
    if "province_canonical_x" in df.columns:
        df["province_canonical"] = df["province_canonical_x"]
    return df


def build_panel_v2(data, series_label, aggregate_children, ref_map):
    """
    Build 2000-vintage panel (SCM-ready).

    aggregate_children=True for PDRB total: child sums are added onto parent direct rows.
    aggregate_children=False for capita: children dropped (cannot sum per-capita).
    """
    print(f"\n{'='*70}")
    print(f"Building {series_label} — 2000-vintage panel")
    print(f"  Total data rows loaded  : {len(data):>7,}")

    # S2: drop NaN values before assembly
    data = data.dropna(subset=["value_standardized"]).copy()
    print(f"  After NaN value drop    : {len(data):>7,}")

    # Partition
    ambiguous = data[data["ambiguous_kab_kota"].astype(str) == "True"].copy()
    children  = data[
        (data["is_post2000_child"].astype(str) == "True") &
        data["parent_district_id"].notna()
    ].copy()
    direct = data[
        (data["ambiguous_kab_kota"].astype(str) != "True") &
        (data["is_post2000_child"].astype(str) != "True") &
        data["district_id"].notna()
    ].copy()

    print(f"  Direct (matched)        : {len(direct):>7,}")
    print(f"  Children                : {len(children):>7,}")
    print(f"  Ambiguous KAB/KOTA      : {len(ambiguous):>7,}")
    n_other = len(data) - len(direct) - len(children) - len(ambiguous)
    if n_other:
        print(f"  Other (no district_id)  : {n_other:>7,}")

    direct["is_child_aggregate"] = False

    if aggregate_children and len(children) > 0:
        # S1/S2: sum children by parent within each source_file (min_count=1 → NaN if all children NaN)
        child_sums = (
            children
            .groupby(CHILD_SUM_KEY, dropna=False)["value_standardized"]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={
                "parent_district_id": "district_id",
                "value_standardized": "child_value_sum",
            })
        )

        # Merge child sums onto parent direct rows where parent exists in same file
        merged = direct.merge(child_sums, on=AGG_MERGE_KEY, how="left")
        has_child = merged["child_value_sum"].notna()
        merged.loc[has_child, "value_standardized"] = (
            merged.loc[has_child, "value_standardized"].fillna(0) +
            merged.loc[has_child, "child_value_sum"]
        )
        merged.drop(columns=["child_value_sum"], inplace=True)

        # Standalone child aggregates: parent absent from this file
        direct_in_file = set(zip(direct["source_file"], direct["district_id"]))
        orphan_mask = child_sums.apply(
            lambda r: (r["source_file"], r["district_id"]) not in direct_in_file, axis=1
        )
        orphan = child_sums[orphan_mask].copy()
        orphan["value_standardized"]  = orphan["child_value_sum"]
        orphan["is_child_aggregate"]  = True
        orphan["is_pre_split_aggregate"] = False
        orphan["match_status"]        = "child_aggregate"
        orphan["source_priority"]     = orphan["source_file"].map(SOURCE_PRIORITY)
        orphan["is_provisional"]      = False
        orphan.drop(columns=["child_value_sum"], inplace=True)

        combined = pd.concat([merged, orphan], ignore_index=True)
        print(f"  Child aggregates added  : {orphan_mask.sum():>7,}  "
              f"(from {len(children):,} child rows, {(~orphan_mask).sum():,} merged onto parents)")
    else:
        if not aggregate_children and len(children) > 0:
            print(f"  Children dropped (per-capita cannot be summed)")
        combined = direct.copy()

    print(f"  Rows before dedup       : {len(combined):>7,}")

    combined = dedup_by_priority(combined, PANEL_KEY)
    print(f"  Rows after dedup        : {len(combined):>7,}")

    combined = attach_ref_metadata(combined, ref_map)

    n_no_ref = combined["district_num"].isna().sum()
    if n_no_ref:
        missing = combined[combined["district_num"].isna()]["district_id"].unique()
        print(f"  WARNING: {n_no_ref} rows missing from district_reference: {missing[:10]}")

    print(f"  Unique districts        : {combined['district_id'].nunique():>7,}")
    print(f"  Year range              : {int(combined['year'].min())}–{int(combined['year'].max())}")
    print(f"  Series (table+base_yr)  : "
          f"{combined.groupby(['table_type','base_year'], dropna=False).ngroups}")

    out_cols = [c for c in PANEL_COLS_V2 if c in combined.columns]
    panel = (
        combined[out_cols]
        .sort_values(["district_id", "year", "table_type", "base_year", "oil_excluded"])
        .reset_index(drop=True)
    )
    return panel, ambiguous


def build_panel_full(data, series_label, ref_map, corr_df=None):
    """
    Build full granular panel — all districts at native boundaries, no child aggregation.
    Children are kept with district_id=null, identified by (province_canonical, region_name_corrected).
    corr_df: corrections_applied DataFrame (source_file, region_name, year, fix_id) or None.
    """
    print(f"\n{'='*70}")
    print(f"Building {series_label} — full granular panel")
    print(f"  Total data rows loaded  : {len(data):>7,}")

    # S2: drop NaN values
    data = data.dropna(subset=["value_standardized"]).copy()
    print(f"  After NaN value drop    : {len(data):>7,}")

    # Exclude ambiguous
    ambiguous = data[data["ambiguous_kab_kota"].astype(str) == "True"].copy()
    data = data[data["ambiguous_kab_kota"].astype(str) != "True"].copy()

    # Dedup direct rows by panel key (source_priority wins)
    direct = data[data["is_post2000_child"].astype(str) != "True"].copy()
    children = data[data["is_post2000_child"].astype(str) == "True"].copy()

    direct = dedup_by_priority(direct, PANEL_KEY)

    # For children: panel key uses province+name+admin_type instead of district_id
    child_full_key = ["province_canonical", "region_name_corrected", "admin_type",
                      "year", "table_type", "base_year", "oil_excluded"]
    children = dedup_by_priority(children, child_full_key)

    combined = pd.concat([direct, children], ignore_index=True)
    print(f"  Rows after dedup        : {len(combined):>7,}")

    combined = attach_ref_metadata(combined, ref_map)

    # P8 / S-6(b): join correction_id from the corrections_applied sidecar on row identity.
    # The sidecar now carries the raw_text_hash of every CSV row each fix actually touched,
    # so the join is on (source_file, raw_text_hash) only. This is immune to name/format drift
    # and eliminates the name-based over-tagging (Kab/Kota Bogor, cross-table siblings, oil pairs).
    #
    # Design note: a single panel row can, in principle, derive from several raw_text_hashes
    # (the child-summation step in build_panel_v2 collapses many child rows onto one parent).
    # In this full granular panel no summation occurs, so each surviving row maps to exactly one
    # raw_text_hash — but we still model the hash as a *set* per row so a fix on any contributing
    # hash is credited, never silently dropped.
    if corr_df is not None and not corr_df.empty and "raw_text_hash" in combined.columns:
        combined["year"] = combined["year"].astype(str)

        sidecar = corr_df.copy()
        # De-duplicate sidecar entries: a fix may log the same (source_file, raw_text_hash)
        # more than once (duplicate source CSV rows sharing a hash; or a null-target fix whose
        # skipped-mode match sweeps sibling NaN rows). Row identity is (source_file, hash, fix_id);
        # collapsing to distinct triples keeps the verification-gate counts exact.
        hashed = (
            sidecar[sidecar["raw_text_hash"].astype(str) != ""]
            .drop_duplicates(["source_file", "raw_text_hash", "fix_id"])
        )
        # Map (source_file, raw_text_hash) -> ";"-joined sorted fix_ids
        hash_lu = (
            hashed.groupby(["source_file", "raw_text_hash"])["fix_id"]
            .apply(lambda xs: ";".join(sorted(set(xs.astype(str)))))
            .to_dict()
        )

        def _corr_for_row(row):
            hset = row["raw_text_hash_set"]
            fixes = set()
            for h in hset:
                key = (row["source_file"], h)
                if key in hash_lu:
                    fixes.update(hash_lu[key].split(";"))
            return ";".join(sorted(fixes)) if fixes else pd.NA

        # Each row's hash set (singleton here; a set to stay robust to future aggregation)
        combined["raw_text_hash_set"] = combined["raw_text_hash"].map(
            lambda h: {h} if pd.notna(h) and str(h) != "" else set()
        )
        combined["correction_id"] = combined.apply(_corr_for_row, axis=1)
        combined.drop(columns=["raw_text_hash_set"], inplace=True)

        n_corrected = combined["correction_id"].notna().sum()
        print(f"  Correction_id joined    : {n_corrected:>7,} rows flagged (hash join)")

        # Verification gate: for each fix_id, the number of panel rows tagged must equal the
        # number of that fix's sidecar hashes that survived into this panel. Proves no over-tag.
        panel_hashes = set(zip(combined["source_file"], combined["raw_text_hash"].astype(str)))
        # Count sidecar hashes per fix_id that are present in this panel's surviving rows
        surviving = hashed[
            hashed.apply(lambda r: (r["source_file"], str(r["raw_text_hash"])) in panel_hashes, axis=1)
        ]
        surviving_per_fix = surviving.groupby("fix_id").size().to_dict()

        # Count panel rows tagged per fix_id (a row may carry multiple fix_ids)
        tagged_per_fix = {}
        for ids in combined["correction_id"].dropna():
            for fid in str(ids).split(";"):
                tagged_per_fix[fid] = tagged_per_fix.get(fid, 0) + 1

        mismatches = []
        for fid in set(surviving_per_fix) | set(tagged_per_fix):
            s = surviving_per_fix.get(fid, 0)
            t = tagged_per_fix.get(fid, 0)
            if s != t:
                mismatches.append((fid, s, t))
        assert not mismatches, (
            f"correction_id over/under-tagging in {series_label}: "
            f"(fix_id, surviving_sidecar_hashes, tagged_panel_rows) = {sorted(mismatches)}"
        )

        # Completeness check: fix_ids whose source_file feeds this panel but which tag nothing.
        # A fix legitimately tags nothing only if every row it touched was dropped before output:
        #   null_fix_ids   — fixes whose edited rows are all nulled → dropped by the S2 NaN filter
        #   excluded_always — P7_garble: rows survive standardize but lose dedup to the
        #                      higher-priority 2005-2007 publication
        # (Derived post-hash-join per Fable Section 3, not ported forward from the name-join list.)
        null_fix_ids    = {"W3a", "W3e", "P5a", "P6", "W2", "FAKFAK_err"}
        excluded_always = {"P7_garble"}
        panel_source_files = set(combined["source_file"].dropna().unique())
        scoped_sidecar = sidecar[sidecar["source_file"].isin(panel_source_files)]
        scoped_fix_ids = set(scoped_sidecar["fix_id"].astype(str).unique())
        tagged_fix_ids = set(tagged_per_fix)
        missing = scoped_fix_ids - tagged_fix_ids - null_fix_ids - excluded_always
        if missing:
            print(f"  WARNING: fix_ids scoped to this panel but tagging nothing: {sorted(missing)}")
    else:
        combined["correction_id"] = pd.NA

    print(f"  Unique named districts  : {combined['region_name_corrected'].nunique():>7,}")
    print(f"  Year range              : {int(combined['year'].min())}–{int(combined['year'].max())}")

    out_cols = [c for c in PANEL_COLS_FULL if c in combined.columns]
    panel = (
        combined[out_cols]
        .sort_values(["province_canonical", "region_name_corrected", "year",
                      "table_type", "base_year", "oil_excluded"])
        .reset_index(drop=True)
    )
    return panel


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("PANEL ASSEMBLY v2")
    print("=" * 70)

    dist_ref = pd.read_csv(CROSSWALK_DIR / "district_reference.csv", dtype={"bps_code": str})
    ref_map = {
        row["district_id"]: {
            "district_num":       int(row["district_num"]),
            "bps_code":           row["bps_code"] if pd.notna(row["bps_code"]) else None,
            "province_canonical": row["province_canonical"],
            "district_name_2000": row["district_name_2000"],
        }
        for _, row in dist_ref.iterrows()
    }
    print(f"\nDistrict reference: {len(ref_map)} entries")

    corr_df = None
    if SIDECAR_PATH.exists():
        corr_df = pd.read_csv(SIDECAR_PATH, dtype=str, keep_default_na=False)
        print(f"Corrections sidecar: {len(corr_df)} row(s) → correction_id join enabled")
    else:
        print(f"Corrections sidecar not found — correction_id will be null")

    # ----------------------------------------------------------------
    # PDRB total
    # ----------------------------------------------------------------
    total_data = load_series(TOTAL_FILES)

    total_v2, total_ambig = build_panel_v2(
        total_data.copy(), "PDRB total", aggregate_children=True, ref_map=ref_map
    )
    total_v2.to_csv(OUTPUT_DIR / "panel_pdrb_total_2000bounds.csv", index=False)
    print(f"  Written: outputs/panel_pdrb_total_2000bounds.csv  ({len(total_v2):,} rows)")

    total_full = build_panel_full(total_data.copy(), "PDRB total", ref_map=ref_map, corr_df=corr_df)
    total_full.to_csv(OUTPUT_DIR / "panel_pdrb_total_native.csv", index=False)
    print(f"  Written: outputs/panel_pdrb_total_native.csv  ({len(total_full):,} rows)")

    # ----------------------------------------------------------------
    # PDRB per capita
    # ----------------------------------------------------------------
    capita_data = load_series(CAPITA_FILES)

    capita_v2, capita_ambig = build_panel_v2(
        capita_data.copy(), "PDRB per capita", aggregate_children=False, ref_map=ref_map
    )
    capita_v2.to_csv(OUTPUT_DIR / "panel_pdrb_capita_2000bounds.csv", index=False)
    print(f"  Written: outputs/panel_pdrb_capita_2000bounds.csv  ({len(capita_v2):,} rows)")

    capita_full = build_panel_full(capita_data.copy(), "PDRB per capita", ref_map=ref_map, corr_df=corr_df)
    capita_full.to_csv(OUTPUT_DIR / "panel_pdrb_capita_native.csv", index=False)
    print(f"  Written: outputs/panel_pdrb_capita_native.csv  ({len(capita_full):,} rows)")

    # ----------------------------------------------------------------
    # Ambiguous KAB/KOTA audit
    # ----------------------------------------------------------------
    ambig_cols = [
        "source_file", "province_canonical", "region_name_corrected",
        "admin_type", "year", "table_type", "base_year", "oil_excluded",
        "value_standardized", "match_status",
    ]
    all_ambig = pd.concat([total_ambig, capita_ambig], ignore_index=True)
    ambig_out = [c for c in ambig_cols if c in all_ambig.columns]
    if len(all_ambig):
        all_ambig[ambig_out].to_csv(AUDIT_DIR / "panel_ambiguous.csv", index=False)
        print(f"\nAmbiguous KAB/KOTA rows (excluded): "
              f"{len(all_ambig):,} → pipeline_out/audits/panel_ambiguous.csv")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PANEL ASSEMBLY COMPLETE")
    print("=" * 70)
    print(f"\nPDRB total v2    : {len(total_v2):>6,} rows  "
          f"({total_v2['district_id'].nunique()} districts × "
          f"{total_v2['year'].nunique()} years × series)")
    print(f"PDRB total full  : {len(total_full):>6,} rows  "
          f"({total_full['region_name_corrected'].nunique()} districts)")
    print(f"PDRB capita v2   : {len(capita_v2):>6,} rows  "
          f"({capita_v2['district_id'].nunique()} districts × "
          f"{capita_v2['year'].nunique()} years × series)")
    print(f"PDRB capita full : {len(capita_full):>6,} rows  "
          f"({capita_full['region_name_corrected'].nunique()} districts)")

    print("\nPDRB total v2 — rows by series:")
    print(total_v2.groupby(["table_type", "base_year", "oil_excluded"],
                            dropna=False).size().to_string())
    print("\nPDRB capita v2 — rows by series:")
    print(capita_v2.groupby(["table_type", "base_year", "oil_excluded"],
                              dropna=False).size().to_string())


if __name__ == "__main__":
    main()
