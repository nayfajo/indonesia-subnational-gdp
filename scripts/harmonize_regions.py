# scripts/harmonize_regions.py
"""
Geographic harmonization stage.

Reads all standardized CSVs from pipeline_out/standardized/. For each data row, adds:
  province_canonical    - harmonized province name (from province_crosswalk.csv)
  region_name_corrected - region_name_base after applying name_corrections.csv
  is_post2000_child     - True if this is a post-2000 split child not in the
                          early-data carve-out (unit tracked as own BPS entry before
                          formal creation, e.g. Kota Cimahi)
  parent_district_id    - for post-2000 children: the 2000-vintage parent's district_id;
                          null if parent could not be resolved
  district_id           - stable 2000-vintage district identifier; null for post-2000
                          children, ambiguous KAB/KOTA rows, and unmatched rows
  district_num          - sequential integer (null for same cases as district_id)
  ambiguous_kab_kota    - True for rows where the base name matches a KAB/KOTA pair in
                          district_reference and admin_type could not resolve the ambiguity
  match_status          - diagnostic: matched / matched_with_admin_type /
                          matched_province_fallback / child / ambiguous_kab_kota /
                          no_province_or_name / unmatched

Early-data carve-out (D1):
  A concordance child is treated as its own 2000-vintage unit iff it appears as a
  standalone, non-#) data row in the 1996-1999 or 2000-2001 standardized files
  (is_data_row=True AND is_pre_split_aggregate=False AND oil_excluded=False).
  Oil-excluded sub-rows are excluded from the scan — they are always companion lines
  of a total row and never standalone district entries, so their absence of #) does
  not signal independence.

Child and parent resolution (Q1b):
  child_set is keyed (province, child_base, child_admin_type) so Kab. Serang
  (direct match) is not confused with Kota Serang (child of Kab. Serang).
  Parent resolution tries unambiguous_ref first, then kab_kota_ref with parent admin_type.

Non-data rows are passed through unchanged with new columns set to null/False.

Outputs (all under pipeline_out/):
  pipeline_out/harmonized/<filename>.csv             one per standardized file
  pipeline_out/audits/harmonize_unmatched.csv        unmatched data rows for manual review
  pipeline_out/audits/harmonize_summary.csv          per-file match statistics
  pipeline_out/audits/harmonize_presplit_mismatch.csv
      is_pre_split_aggregate rows whose match_status is not child/matched —
      each hit is an OCR garble or a missing concordance/reference entry
"""

from pathlib import Path
import pandas as pd

STANDARDIZED_DIR = Path("pipeline_out/standardized")
CROSSWALK_DIR    = Path("crosswalks")
HARMONIZED_DIR   = Path("pipeline_out/harmonized")
AUDIT_DIR        = Path("pipeline_out/audits")

NEW_COLS = [
    "province_canonical",
    "region_name_corrected",
    "is_post2000_child",
    "parent_district_id",
    "district_id",
    "district_num",
    "ambiguous_kab_kota",
    "match_status",
]

# =========================================================
# HELPERS
# =========================================================

def _extract_admin_type(name_raw):
    """Derive admin_type from a raw district name with Kabupaten/Kota prefix."""
    if pd.isna(name_raw):
        return None
    s = str(name_raw).strip().lower()
    if s.startswith("kota"):
        return "kota"
    if s.startswith("kabupaten"):
        return "kabupaten"
    return None


def apply_correction(name, corr_map):
    if pd.isna(name):
        return name
    s = str(name).strip()
    return corr_map.get(s, s)


def lookup_district(prov, name, admin_type,
                    child_set, unambiguous_ref, kab_kota_ref, kab_kota_pairs,
                    name_unambig, name_kab_kota):
    """
    Return a dict of harmonization values for one data row.

    child_set:       {(province, child_base, child_admin_type): {parent_base, parent_admin_type}}
                     child_admin_type is None for concordance entries without Kab./Kota prefix.
    unambiguous_ref: {(province, district_name_2000): {district_id, district_num}}
    kab_kota_ref:    {(province, district_name_2000, admin_type): {district_id, district_num}}
    kab_kota_pairs:  set of (province, district_name_2000) with KAB/KOTA ambiguity
    name_unambig:    {district_name_2000: [(province, info)]} — name-only fallback index
    name_kab_kota:   {district_name_2000: {province, ...}} — provinces where name is a KAB/KOTA pair
    """
    base = dict(
        is_post2000_child=False,
        parent_district_id=None,
        district_id=None,
        district_num=None,
        ambiguous_kab_kota=False,
        match_status="unmatched",
    )

    if pd.isna(prov) or pd.isna(name):
        base["match_status"] = "no_province_or_name"
        return base

    at_known = pd.notna(admin_type) and admin_type in ("kabupaten", "kota")

    # 1. Post-2000 child check (admin_type-aware; early-data carve-out already excluded)
    child_entry = None
    if at_known:
        child_entry = child_set.get((prov, name, admin_type))
    if child_entry is None:
        child_entry = child_set.get((prov, name, None))
    if child_entry is None and not at_known:
        # admin_type unknown (pre-2008): try both keys; accept only if unambiguous
        kab_entry = child_set.get((prov, name, "kabupaten"))
        kot_entry = child_set.get((prov, name, "kota"))
        if kab_entry and not kot_entry:
            child_entry = kab_entry
        elif kot_entry and not kab_entry:
            child_entry = kot_entry

    if child_entry is not None:
        parent_base = child_entry["parent_base"]
        parent_at   = child_entry["parent_admin_type"]
        parent_info = unambiguous_ref.get((prov, parent_base))
        if parent_info is None and parent_at:
            parent_info = kab_kota_ref.get((prov, parent_base, parent_at))
        base["is_post2000_child"]  = True
        base["parent_district_id"] = parent_info["district_id"] if parent_info else None
        base["match_status"]       = "child"
        return base

    # 2. Direct district_reference match with admin_type
    if at_known:
        info = kab_kota_ref.get((prov, name, admin_type))
        if info:
            base["district_id"]  = info["district_id"]
            base["district_num"] = info["district_num"]
            base["match_status"] = "matched_with_admin_type"
            return base
        # admin_type known but not in KAB/KOTA pairs — fall through to unambiguous lookup

    # 3. Province+name match (pre-2008 or unknown admin_type)
    if (prov, name) in kab_kota_pairs:
        base["ambiguous_kab_kota"] = True
        base["match_status"]       = "ambiguous_kab_kota"
        return base
    elif (prov, name) in unambiguous_ref:
        info = unambiguous_ref[(prov, name)]
        base["district_id"]  = info["district_id"]
        base["district_num"] = info["district_num"]
        base["match_status"] = "matched"
        return base

    # 4. Province-agnostic fallback (district moved to a different canonical province,
    #    e.g. RIAU → KEPULAUAN RIAU, JAWA BARAT → BANTEN, PAPUA → PAPUA BARAT)
    unambig_cands  = name_unambig.get(name, [])
    kab_kota_provs = name_kab_kota.get(name, set())

    if len(unambig_cands) == 1 and not kab_kota_provs:
        _, info = unambig_cands[0]
        base["district_id"]  = info["district_id"]
        base["district_num"] = info["district_num"]
        base["match_status"] = "matched_province_fallback"
    elif len(kab_kota_provs) == 1 and not unambig_cands:
        fb_prov = next(iter(kab_kota_provs))
        if at_known:
            info = kab_kota_ref.get((fb_prov, name, admin_type))
            if info:
                base["district_id"]  = info["district_id"]
                base["district_num"] = info["district_num"]
                base["match_status"] = "matched_province_fallback"
                return base
        base["ambiguous_kab_kota"] = True
        base["match_status"]       = "ambiguous_kab_kota"

    return base


# =========================================================
# MAIN
# =========================================================

def main():

    HARMONIZED_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("GEOGRAPHIC HARMONIZATION")
    print("=" * 80)

    # ------------------------------------------------------------------
    # Load crosswalks
    # ------------------------------------------------------------------

    prov_xwalk = pd.read_csv(CROSSWALK_DIR / "province_crosswalk.csv")
    prov_map = dict(zip(
        prov_xwalk["province_name_clean"],
        prov_xwalk["province_canonical"]
    ))

    name_corr = pd.read_csv(CROSSWALK_DIR / "name_corrections.csv")
    name_corr_map = dict(zip(
        name_corr["region_name_base_raw"].str.strip(),
        name_corr["region_name_base_corrected"].str.strip()
    ))

    dist_ref   = pd.read_csv(CROSSWALK_DIR / "district_reference.csv")
    split_conc = pd.read_csv(CROSSWALK_DIR / "split_concordance.csv")

    print(f"\nLoaded crosswalks:")
    print(f"  province_crosswalk : {len(prov_map)} entries")
    print(f"  name_corrections   : {len(name_corr_map)} entries")
    print(f"  district_reference : {len(dist_ref)} rows")
    print(f"  split_concordance  : {len(split_conc)} rows")

    # ------------------------------------------------------------------
    # Build district_reference lookup structures
    # ------------------------------------------------------------------

    unambiguous_ref = {}   # (province, district_name_2000) → {district_id, district_num}
    kab_kota_ref    = {}   # (province, district_name_2000, admin_type) → {district_id, district_num}
    kab_kota_pairs  = set()

    for (prov, name), grp in dist_ref.groupby(["province_canonical", "district_name_2000"]):
        if grp["admin_type"].notna().any():
            kab_kota_pairs.add((prov, name))
            for _, r in grp.iterrows():
                kab_kota_ref[(prov, name, r["admin_type"])] = {
                    "district_id":  r["district_id"],
                    "district_num": int(r["district_num"]),
                }
        else:
            r = grp.iloc[0]
            unambiguous_ref[(prov, name)] = {
                "district_id":  r["district_id"],
                "district_num": int(r["district_num"]),
            }

    # Name-only fallback indices (province-agnostic, for districts that moved provinces)
    name_unambig  = {}   # name → [(prov, info)]
    name_kab_kota = {}   # name → {prov, ...}
    for (prov, name), info in unambiguous_ref.items():
        name_unambig.setdefault(name, []).append((prov, info))
    for (prov, name) in kab_kota_pairs:
        name_kab_kota.setdefault(name, set()).add(prov)

    print(f"\nDistrict reference lookup:")
    print(f"  Unambiguous entries : {len(unambiguous_ref)}")
    print(f"  KAB/KOTA pairs      : {len(kab_kota_pairs)}")

    # ------------------------------------------------------------------
    # Build early-data carve-out set (D1)
    # Collect (province, corrected_base) from rows where:
    #   is_data_row=True AND is_pre_split_aggregate=False AND oil_excluded=False
    # in the four early files (total + capita, 1996-1999 + 2000-2001).
    # Oil-excluded sub-rows are skipped — they are companion lines of total rows
    # and their absence of #) does not signal district independence.
    # ------------------------------------------------------------------

    early_bases = set()
    early_files = [
        fp for fp in sorted(STANDARDIZED_DIR.glob("*.csv"))
        if any(tag in fp.name for tag in ["1996", "2000"])
    ]
    for fp in early_files:
        df_e = pd.read_csv(fp, low_memory=False)
        data_e = df_e[
            (df_e["is_data_row"] == True) &
            (~df_e["is_pre_split_aggregate"].fillna(False).astype(bool)) &
            (~df_e["oil_excluded"].fillna(False).astype(bool))
        ]
        for _, row in data_e.iterrows():
            prov = prov_map.get(str(row["province_name_clean"]).strip())
            base = apply_correction(row["region_name_base"], name_corr_map)
            if prov and pd.notna(base):
                early_bases.add((prov, str(base)))

    print(f"\nEarly-data carve-out: {len(early_bases)} (province, base) pairs from {len(early_files)} early files")

    # ------------------------------------------------------------------
    # Build child → parent map (admin_type-aware; excluding early-data carve-out)
    # Keyed (province, child_base, child_admin_type) so e.g. Kab. Serang is not
    # consumed by Kota Serang's concordance entry.
    # ------------------------------------------------------------------

    child_set = {}   # (province, child_base, child_admin_type) → {parent_base, parent_admin_type}
    skipped_carve_out = 0
    for _, row in split_conc.iterrows():
        prov        = row["province"]
        child_base  = apply_correction(row["child_base"], name_corr_map)
        parent_base = row["parent_base_2000"]
        child_at    = _extract_admin_type(row.get("child_name_raw"))
        parent_at   = _extract_admin_type(row.get("parent_name_raw"))
        base_key    = (prov, str(child_base))
        if base_key in early_bases:
            skipped_carve_out += 1
        else:
            key = (prov, str(child_base), child_at)
            child_set[key] = {"parent_base": parent_base, "parent_admin_type": parent_at}

    print(f"Post-2000 children (after carve-out): {len(child_set)}")
    print(f"  Skipped by early-data carve-out:    {skipped_carve_out}")

    # ------------------------------------------------------------------
    # Validate: concordance provinces should all be canonical
    # ------------------------------------------------------------------

    all_canonical    = set(prov_map.values())
    conc_provinces   = set(split_conc["province"].unique())
    unknown_prov     = conc_provinces - all_canonical
    if unknown_prov:
        print(f"\nWARNING: split_concordance has non-canonical provinces: {unknown_prov}")

    # ------------------------------------------------------------------
    # Process each standardized file
    # ------------------------------------------------------------------

    csv_files             = sorted(STANDARDIZED_DIR.glob("*.csv"))
    all_unmatched         = []
    all_presplit_mismatch = []
    file_summaries        = []

    for fp in csv_files:
        print(f"\n{'='*70}")
        print(f"Processing: {fp.name}")

        df = pd.read_csv(fp, low_memory=False)

        # Initialize new columns
        for col in NEW_COLS:
            df[col] = pd.NA
        df["is_post2000_child"]  = False
        df["ambiguous_kab_kota"] = False

        data_mask = df["is_data_row"] == True
        data = df[data_mask].copy()

        # Skip province-aggregate and junk rows
        prov_agg_mask = data["region_name_base"].str.startswith("PDRB PROVINSI", na=False)
        junk_mask = (
            data["region_name_base"].isna() |
            (data["region_name_base"].str.strip() == "") |
            (data["region_name_base"].str.strip() == "-")
        )
        if prov_agg_mask.any():
            print(f"  Skipping {prov_agg_mask.sum()} province-aggregate rows (PDRB PROVINSI …)")
        if junk_mask.any():
            print(f"  Skipping {junk_mask.sum()} junk rows (empty/dash region_name_base)")
        data = data[~(prov_agg_mask | junk_mask)]

        if data.empty:
            print(f"  No data rows — skipping")
            df.to_csv(HARMONIZED_DIR / fp.name, index=False)
            continue

        # Apply province crosswalk and name corrections
        data["province_canonical"]   = data["province_name_clean"].map(prov_map)
        data["region_name_corrected"] = data["region_name_base"].apply(
            lambda x: apply_correction(x, name_corr_map)
        )

        # District lookup (one row at a time via apply)
        def _lookup(row):
            return pd.Series(lookup_district(
                prov        = row["province_canonical"],
                name        = row["region_name_corrected"],
                admin_type  = row.get("admin_type"),
                child_set        = child_set,
                unambiguous_ref  = unambiguous_ref,
                kab_kota_ref     = kab_kota_ref,
                kab_kota_pairs   = kab_kota_pairs,
                name_unambig     = name_unambig,
                name_kab_kota    = name_kab_kota,
            ))

        lookup_cols = ["is_post2000_child", "parent_district_id",
                       "district_id", "district_num",
                       "ambiguous_kab_kota", "match_status"]
        data[lookup_cols] = data.apply(_lookup, axis=1)

        # Collect unmatched for audit
        unmatched = data[data["match_status"] == "unmatched"]
        for _, row in unmatched.iterrows():
            all_unmatched.append({
                "source_file":           fp.name,
                "province_canonical":    row["province_canonical"],
                "region_name_corrected": row["region_name_corrected"],
                "admin_type":            row.get("admin_type"),
                "year":                  row.get("year"),
            })

        # Collect pre-split mismatch audit (is_pre_split_aggregate=True but not child/matched)
        presplit_ok = {"child", "matched", "matched_with_admin_type"}
        presplit_flag = (
            data["is_pre_split_aggregate"].fillna(False).astype(bool) &
            ~data["match_status"].isin(presplit_ok)
        )
        for _, row in data[presplit_flag].iterrows():
            all_presplit_mismatch.append({
                "source_file":           fp.name,
                "province_canonical":    row["province_canonical"],
                "region_name_corrected": row["region_name_corrected"],
                "admin_type":            row.get("admin_type"),
                "match_status":          row["match_status"],
                "year":                  row.get("year"),
            })
        presplit_count = int(presplit_flag.sum())

        # Write harmonization columns back into full df
        df.update(data)

        # Ensure bool columns are bool (df.update can widen to object)
        df["is_post2000_child"]  = df["is_post2000_child"].fillna(False).astype(bool)
        df["ambiguous_kab_kota"] = df["ambiguous_kab_kota"].fillna(False).astype(bool)

        # Per-file summary
        counts = data["match_status"].value_counts().to_dict()
        n_data = len(data)
        print(f"  Data rows                    : {n_data:>6,}")
        print(f"  matched                      : {counts.get('matched', 0):>6,}")
        print(f"  matched_with_admin_type      : {counts.get('matched_with_admin_type', 0):>6,}")
        print(f"  matched_province_fallback    : {counts.get('matched_province_fallback', 0):>6,}")
        print(f"  child (post-2000)            : {counts.get('child', 0):>6,}")
        print(f"  ambiguous_kab_kota           : {counts.get('ambiguous_kab_kota', 0):>6,}")
        print(f"  no_province_or_name          : {counts.get('no_province_or_name', 0):>6,}")
        print(f"  unmatched                    : {counts.get('unmatched', 0):>6,}")
        if presplit_count:
            print(f"  presplit mismatch (audit)    : {presplit_count:>6,}")

        out_path = HARMONIZED_DIR / fp.name
        df.to_csv(out_path, index=False)
        print(f"  Written: {out_path}")

        file_summaries.append({
            "file":                       fp.name,
            "total_data_rows":            n_data,
            "matched":                    counts.get("matched", 0),
            "matched_with_admin_type":    counts.get("matched_with_admin_type", 0),
            "matched_province_fallback":  counts.get("matched_province_fallback", 0),
            "child":                      counts.get("child", 0),
            "ambiguous_kab_kota":         counts.get("ambiguous_kab_kota", 0),
            "no_province_or_name":        counts.get("no_province_or_name", 0),
            "unmatched":                  counts.get("unmatched", 0),
            "presplit_mismatch":          presplit_count,
        })

    # ------------------------------------------------------------------
    # Audit outputs
    # ------------------------------------------------------------------

    summary_df = pd.DataFrame(file_summaries)
    summary_df.to_csv(AUDIT_DIR / "harmonize_summary.csv", index=False)
    print(f"\nSummary: {AUDIT_DIR / 'harmonize_summary.csv'}")

    if all_unmatched:
        unmatched_df = pd.DataFrame(all_unmatched)
        unmatched_df.to_csv(AUDIT_DIR / "harmonize_unmatched.csv", index=False)
        print(f"Unmatched ({len(all_unmatched)} rows): {AUDIT_DIR / 'harmonize_unmatched.csv'}")
    else:
        print("No unmatched rows.")

    if all_presplit_mismatch:
        presplit_df = pd.DataFrame(all_presplit_mismatch)
        presplit_df.to_csv(AUDIT_DIR / "harmonize_presplit_mismatch.csv", index=False)
        print(f"Pre-split mismatch ({len(all_presplit_mismatch)} rows): {AUDIT_DIR / 'harmonize_presplit_mismatch.csv'}")
    else:
        print("No pre-split mismatch rows.")

    # ------------------------------------------------------------------
    # Overall summary
    # ------------------------------------------------------------------

    print("\n" + "=" * 80)
    print("HARMONIZATION COMPLETE")
    print("=" * 80)

    total = summary_df["total_data_rows"].sum()
    print(f"Total data rows : {total:,}")
    for col in ["matched", "matched_with_admin_type", "matched_province_fallback",
                "child", "ambiguous_kab_kota", "no_province_or_name", "unmatched",
                "presplit_mismatch"]:
        n   = summary_df[col].sum()
        pct = 100 * n / total if total else 0
        print(f"  {col:<28} {n:>6,}  ({pct:.1f}%)")


if __name__ == "__main__":
    main()
