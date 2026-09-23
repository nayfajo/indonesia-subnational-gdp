#!/usr/bin/env python3
"""
Stage 6 QA and Validation for the PDRB panel — v2.

Runs 11 checks across both panels and writes audit files to pipeline_out/audits/qa_*.csv.
Prints a summary at the end. Exits 1 if any FAIL check fires.

Checks:
  1. Uniqueness         — no duplicate panel keys
  2. Missing years      — year gaps within a series' observed range
  3. Growth anomalies   — extreme YoY swings in value_standardized
  4. Province totals    — district sums within tolerance of reported province totals
  5. Overlap revisions  — report BPS revision sizes at 2021-2022 overlap years
  6. Null-parent children — post-2000 children with no resolvable parent (should be 0)
  7. Total vs capita gap — district coverage difference across the two panels
  8. Within-file duplicates — same corrected name appears twice in one harmonized file
  9. Implied population — total ÷ per-capita plausibility and smoothness (Section 7.14)
 10. Implied deflator   — nominal ÷ real smoothness, base-2010 era
 11. Roster completeness — sandwich-missing districts across publications (Section 7.12)
"""

from pathlib import Path
import sys
import pandas as pd

OUTPUT_DIR       = Path("outputs")
HARMONIZED_DIR   = Path("pipeline_out/harmonized")
STANDARDIZED_DIR = Path("pipeline_out/standardized")
AUDIT_DIR        = Path("pipeline_out/audits")

PANEL_KEY = ["district_id", "year", "table_type", "base_year", "oil_excluded"]

TOTAL_FILES = [
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

# Overlap: 2020-2022 (priority 9) and 2021-2023 (priority 10) share years 2021 and 2022
TOTAL_OVERLAPS = [
    ("PDRB_2020-2022.csv", "PDRB_2021-2023.csv", [2021, 2022]),
]
CAPITA_OVERLAPS = [
    ("PDRB-capita_2020-2022.csv", "PDRB-capita_2021-2023.csv", [2021, 2022]),
]

NOMINAL_GROWTH_HI = 3.00   # 300% YoY
NOMINAL_GROWTH_LO = -0.80  # -80% YoY
REAL_GROWTH_HI    = 0.70   # 70% YoY
REAL_GROWTH_LO    = -0.50  # -50% YoY

PROVINCE_TOL_PCT  = 20.0   # district sum vs independently-measured PROPINSI figure (loose: BPS residual)


# ---------------------------------------------------------------------------
# CHECK 1 — Uniqueness
# ---------------------------------------------------------------------------

def check1_uniqueness(total, capita):
    frames = []
    for label, df in [("total", total), ("capita", capita)]:
        dupes = df[df.duplicated(subset=PANEL_KEY, keep=False)].copy()
        if len(dupes):
            dupes.insert(0, "panel", label)
            frames.append(dupes)

    if not frames:
        return 0, "CHECK 1 PASS  : no duplicate panel keys"

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(AUDIT_DIR / "qa_duplicates.csv", index=False)
    return len(out), f"CHECK 1 FAIL  : {len(out)} duplicate rows → pipeline_out/audits/qa_duplicates.csv"


# ---------------------------------------------------------------------------
# CHECK 2 — Missing years within a series
# ---------------------------------------------------------------------------

def check2_missing_years(total, capita):
    group_key = ["district_id", "table_type", "base_year", "oil_excluded"]
    rows = []

    for label, df in [("total", total), ("capita", capita)]:
        for keys, grp in df.groupby(group_key, dropna=False):
            years = set(grp["year"].astype(int))
            y_min, y_max = min(years), max(years)
            missing = sorted(set(range(y_min, y_max + 1)) - years)
            if missing:
                rows.append({
                    "panel":        label,
                    "district_id":  keys[0],
                    "table_type":   keys[1],
                    "base_year":    keys[2],
                    "oil_excluded": keys[3],
                    "year_min":     y_min,
                    "year_max":     y_max,
                    "missing_years": str(missing),
                    "n_missing":    len(missing),
                })

    if not rows:
        return 0, "CHECK 2 PASS  : no year gaps within any series"

    out = pd.DataFrame(rows)
    out.to_csv(AUDIT_DIR / "qa_missing_years.csv", index=False)
    return len(rows), f"CHECK 2 WARN  : {len(rows)} series have year gaps → pipeline_out/audits/qa_missing_years.csv"


# ---------------------------------------------------------------------------
# CHECK 3 — Growth anomalies
# ---------------------------------------------------------------------------

def check3_growth_anomalies(total, capita):
    group_key = ["district_id", "table_type", "base_year", "oil_excluded"]
    frames = []

    for label, df in [("total", total), ("capita", capita)]:
        for keys, grp in df.groupby(group_key, dropna=False):
            tt = keys[1]
            hi = NOMINAL_GROWTH_HI if tt == "nominal" else REAL_GROWTH_HI
            lo = NOMINAL_GROWTH_LO if tt == "nominal" else REAL_GROWTH_LO

            s = grp.sort_values("year")[["year", "value_standardized", "source_file"]].copy()
            s["yoy"] = s["value_standardized"].pct_change()
            bad = s[(s["yoy"] > hi) | (s["yoy"] < lo)].dropna(subset=["yoy"])
            if len(bad):
                bad = bad.copy()
                bad["panel"]        = label
                bad["district_id"]  = keys[0]
                bad["table_type"]   = tt
                bad["base_year"]    = keys[2]
                bad["oil_excluded"] = keys[3]
                frames.append(bad)

    if not frames:
        return 0, "CHECK 3 PASS  : no extreme YoY growth anomalies"

    out = pd.concat(frames, ignore_index=True)[
        ["panel", "district_id", "table_type", "base_year", "oil_excluded",
         "year", "value_standardized", "yoy", "source_file"]
    ]
    out.to_csv(AUDIT_DIR / "qa_growth_anomalies.csv", index=False)
    return len(out), (
        f"CHECK 3 WARN  : {len(out)} growth anomalies "
        f"(>{NOMINAL_GROWTH_HI*100:.0f}% or <{NOMINAL_GROWTH_LO*100:.0f}%) "
        f"→ pipeline_out/audits/qa_growth_anomalies.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 4 — Province totals
# ---------------------------------------------------------------------------

def check4_province_totals():
    """
    Sum district data rows by province and compare to the BPS-reported PROPINSI
    totals in the standardized files. Excludes per-capita (cannot sum) and
    oil_excluded=True tables (structurally incomplete sums — only oil districts
    listed).

    Dual-section publications (e.g. 2000-2001) and publication overlaps (2020-2022
    vs 2021-2023) print the same rows twice. Exact repeats — same
    (province, year, table_type, base_year, district name, value) — are collapsed
    before summing so the district side is not double-counted. Province rows are
    likewise deduplicated (the original code already did this; the data-row
    dedup below is the 2026-09 fix for the DKI Jakarta / Lampung +90% false
    positives).

    A tighter parse-fidelity check against the printed "Jml N Kab./Kota" total
    (row_type == "total_regmun") is a TODO: it needs robust handling of blank/
    garbled district names and of the "#)" sub-row accounting, which varies by
    publication era.
    """
    group_key = ["province_name_clean", "year", "table_type", "base_year"]
    frames = []

    for fname in TOTAL_FILES:
        fp = STANDARDIZED_DIR / fname
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False)

        prov_rows = df[(df["row_type"] == "province") &
                       (df["oil_excluded"].astype(str) == "False")].copy()
        data_rows = df[(df["is_data_row"].astype(str) == "True") &
                       (df["oil_excluded"].astype(str) == "False")].copy()
        if prov_rows.empty or data_rows.empty:
            continue

        # Collapse exact-repeat rows from dual-section pages / publication overlaps.
        # Keying on the value too means a genuine district that appears twice with
        # *different* values is left alone (it should surface, not be hidden).
        data_rows = data_rows.drop_duplicates(
            subset=group_key + ["region_name_base", "value_standardized"], keep="first")
        prov_rows = prov_rows.drop_duplicates(subset=group_key, keep="first")

        prov_agg = (
            prov_rows.groupby(group_key, dropna=False)["value_standardized"]
            .sum().reset_index()
            .rename(columns={"value_standardized": "province_reported"})
        )
        dist_agg = (
            data_rows.groupby(group_key, dropna=False)["value_standardized"]
            .sum().reset_index()
            .rename(columns={"value_standardized": "district_sum"})
        )

        merged = prov_agg.merge(dist_agg, on=group_key, how="inner")
        if merged.empty:
            continue

        merged = merged[merged["province_reported"] != 0]
        merged["pct_diff"]    = (merged["district_sum"] / merged["province_reported"] - 1) * 100
        merged["source_file"] = fname
        bad = merged[merged["pct_diff"].abs() > PROVINCE_TOL_PCT]
        if len(bad):
            frames.append(bad)

    if not frames:
        return 0, (
            f"CHECK 4 PASS  : district sums ≈ province totals "
            f"(within {PROVINCE_TOL_PCT}%, total PDRB, oil_excluded=False)"
        )

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(AUDIT_DIR / "qa_province_totals.csv", index=False)
    return len(out), (
        f"CHECK 4 WARN  : {len(out)} province-year combos with >{PROVINCE_TOL_PCT}% discrepancy "
        f"→ pipeline_out/audits/qa_province_totals.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 5 — Overlap revisions (2021-2022)
# ---------------------------------------------------------------------------

def _nan_safe_key(df, key_cols):
    df = df.copy()
    for c in key_cols:
        df[c] = df[c].fillna("__NA__").astype(str)
    return df


def check5_overlap_revisions(total, capita):
    """
    Check that the panel uses PDRB_2021-2023 (priority 10) over PDRB_2020-2022 (priority 9)
    at years 2021 and 2022. Report revision magnitudes between the two publications.
    """
    key           = ["district_id", "table_type", "base_year", "oil_excluded"]
    panel_wrong   = []
    revision_records = []

    for series_label, file_pairs, panel in [
        ("total",  TOTAL_OVERLAPS,  total),
        ("capita", CAPITA_OVERLAPS, capita),
    ]:
        for earlier_file, later_file, overlap_years in file_pairs:
            for overlap_year in overlap_years:
                early = pd.read_csv(HARMONIZED_DIR / earlier_file, low_memory=False)
                late  = pd.read_csv(HARMONIZED_DIR / later_file,   low_memory=False)

                e = (early[(early["is_data_row"].astype(str) == "True") &
                           (early["year"] == overlap_year)][key + ["value_standardized"]]
                     .dropna(subset=["value_standardized"])
                     .drop_duplicates(subset=key)
                     .rename(columns={"value_standardized": "value_early"}))
                l = (late[(late["is_data_row"].astype(str) == "True") &
                          (late["year"] == overlap_year)][key + ["value_standardized"]]
                     .dropna(subset=["value_standardized"])
                     .drop_duplicates(subset=key)
                     .rename(columns={"value_standardized": "value_late"}))

                e_s = _nan_safe_key(e, key)
                l_s = _nan_safe_key(l, key)
                merged = e_s.merge(l_s, on=key)
                merged["revision_pct"] = (merged["value_late"] / merged["value_early"] - 1) * 100
                merged["overlap_year"] = overlap_year
                merged["series"]       = series_label
                merged["earlier_file"] = earlier_file
                merged["later_file"]   = later_file
                revision_records.append(merged)

                # Panel should use later-file value
                panel_yr   = panel[panel["year"] == overlap_year].copy()
                panel_yr_s = _nan_safe_key(panel_yr, key)
                late_keys  = l_s[key].copy()
                late_keys["_in_late"] = True
                panel_check = panel_yr_s.merge(late_keys, on=key, how="left")
                wrong = panel_check[
                    (panel_check["source_file"] == earlier_file) &
                    (panel_check["_in_late"] == True)
                ]
                if len(wrong):
                    wrong = wrong.copy()
                    wrong["series"]       = series_label
                    wrong["overlap_year"] = overlap_year
                    panel_wrong.append(wrong)

    n_wrong = sum(len(w) for w in panel_wrong)

    if revision_records:
        all_rev = pd.concat(revision_records, ignore_index=True)
        all_rev.to_csv(AUDIT_DIR / "qa_overlap_revisions.csv", index=False)
        n_rev    = len(all_rev)
        rev_rng  = (f"[{all_rev['revision_pct'].min():.1f}%, "
                    f"{all_rev['revision_pct'].max():.1f}%]")
        rev_note = f"  {n_rev} overlap records (2021-2022); revision range {rev_rng}"
    else:
        rev_note = "  no overlap data found"

    if n_wrong:
        if panel_wrong:
            pd.concat(panel_wrong, ignore_index=True).to_csv(
                AUDIT_DIR / "qa_overlap_wrong_source.csv", index=False)
        return n_wrong, (
            f"CHECK 5 FAIL  : {n_wrong} panel rows used earlier publication at "
            f"overlap year → pipeline_out/audits/qa_overlap_wrong_source.csv\n{rev_note}"
        )
    return 0, f"CHECK 5 PASS  : panel correctly uses later publication at 2021-2022 overlap\n{rev_note}"


# ---------------------------------------------------------------------------
# CHECK 6 — Children with null parent_district_id
# ---------------------------------------------------------------------------

def check6_null_parent_children():
    frames = []
    for fname in TOTAL_FILES + CAPITA_FILES:
        fp = HARMONIZED_DIR / fname
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False)
        df = df[df["is_data_row"].astype(str) == "True"]
        null_parent = df[
            (df["is_post2000_child"].astype(str) == "True") &
            df["parent_district_id"].isna()
        ].copy()
        if len(null_parent):
            null_parent["source_file_loaded"] = fname
            frames.append(null_parent)

    if not frames:
        return 0, "CHECK 6 PASS  : no children with null parent_district_id"

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(AUDIT_DIR / "qa_null_parent_children.csv", index=False)
    n = len(out)
    return 0, (
        f"CHECK 6 INFO  : {n} null-parent child rows "
        f"(expected 0 with Q3 resolved) "
        f"→ pipeline_out/audits/qa_null_parent_children.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 7 — Total vs capita district gap
# ---------------------------------------------------------------------------

def check7_district_gap(total, capita):
    total_ids  = set(total["district_id"].dropna().unique())
    capita_ids = set(capita["district_id"].dropna().unique())

    only_total  = sorted(total_ids - capita_ids)
    only_capita = sorted(capita_ids - total_ids)

    records = (
        [{"panel": "total_only",  "district_id": d} for d in only_total] +
        [{"panel": "capita_only", "district_id": d} for d in only_capita]
    )
    if records:
        pd.DataFrame(records).to_csv(AUDIT_DIR / "qa_district_gap.csv", index=False)

    base = (
        f"{len(total_ids)} districts in total, {len(capita_ids)} in capita; "
        f"{len(only_total)} total-only, {len(only_capita)} capita-only"
    )
    suffix = " → pipeline_out/audits/qa_district_gap.csv" if records else ""
    return 0, f"CHECK 7 INFO  : {base}{suffix}"


# ---------------------------------------------------------------------------
# CHECK 8 — Within-file duplicates in harmonized files
# ---------------------------------------------------------------------------

def check8_within_file_duplicates():
    """
    Flag district-year combinations that appear twice in a single harmonized file with
    the same corrected name, admin_type, table_type, base_year, and oil_excluded.
    These can arise from:
      - footnote_marker oil-exclusion rows not captured as oil_excluded=True (standardize bug)
      - garbled+clean name collision (both forms corrected to the same name)
    Does NOT fail the pipeline — produces an INFO audit file.
    """
    dup_key = [
        "province_canonical", "region_name_corrected", "admin_type",
        "year", "table_type", "base_year", "oil_excluded",
    ]
    frames = []
    for fname in TOTAL_FILES + CAPITA_FILES:
        fp = HARMONIZED_DIR / fname
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False)
        df = df[df["is_data_row"].astype(str) == "True"].copy()
        df = df.dropna(subset=["value_standardized"])
        dupes = df[df.duplicated(subset=dup_key, keep=False)].copy()
        if len(dupes):
            dupes["harmonized_file"] = fname
            frames.append(dupes[[
                "harmonized_file", "province_canonical", "region_name_corrected",
                "admin_type", "year", "table_type", "base_year", "oil_excluded",
                "value_standardized", "region_name_raw",
            ]])

    if not frames:
        return 0, "CHECK 8 PASS  : no within-file duplicate district-year rows"

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(AUDIT_DIR / "qa_within_file_dupes.csv", index=False)
    n = len(out)
    n_files = out["harmonized_file"].nunique()
    return 0, (
        f"CHECK 8 INFO  : {n} within-file duplicate rows across {n_files} files "
        f"(likely footnote_marker oil-exclusion bug or garble+clean collision) "
        f"→ pipeline_out/audits/qa_within_file_dupes.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 9 — Implied population (total ÷ per-capita cross-publication check)
# ---------------------------------------------------------------------------

def check9_implied_population(total, capita):
    """
    The total and per-capita panels come from different BPS publications, so
    total ÷ per-capita = implied population is a cross-check between two
    independent transcriptions. Flags:
      - implied population outside [10k, 12M] (implausible for any district)
      - YoY implied-population change beyond ±25%
    Jumps at pemekaran years for split parents are EXPECTED (the capita panel
    keeps rump-parent territory after a split — data guide Section 7.14); such
    rows are annotated near_known_split=True. Does not fail the pipeline.
    """
    t = total[(total["table_type"] == "nominal") & (total["oil_excluded"] == False)][
        ["district_id", "district_name_2000", "year", "value_standardized"]
    ].rename(columns={"value_standardized": "total_idr"})
    c = capita[(capita["table_type"] == "nominal") & (capita["oil_excluded"] == False)][
        ["district_id", "year", "value_standardized"]
    ].rename(columns={"value_standardized": "capita_idr"})
    m = t.merge(c, on=["district_id", "year"])
    m = m[(m["total_idr"] > 0) & (m["capita_idr"] > 0)].copy()
    m["implied_pop"] = m["total_idr"] / m["capita_idr"]
    m = m.sort_values(["district_id", "year"])
    m["pop_chg"] = m.groupby("district_id")["implied_pop"].pct_change()

    con = pd.read_csv("crosswalks/split_concordance.csv")
    split_parents = set(con["parent_base"].astype(str).str.upper().str.strip())

    m["flag_implausible"] = (m["implied_pop"] < 10_000) | (m["implied_pop"] > 12_000_000)
    m["flag_jump"] = m["pop_chg"].abs() > 0.25
    out = m[m["flag_implausible"] | m["flag_jump"]].copy()
    out["near_known_split"] = out["district_name_2000"].astype(str).str.upper().isin(split_parents)

    if not len(out):
        return 0, "CHECK 9 PASS  : implied population plausible and smooth everywhere"
    out.to_csv(AUDIT_DIR / "qa_implied_population.csv", index=False)
    n_unexpl = int((~out["near_known_split"]).sum())
    return 0, (
        f"CHECK 9 INFO  : {len(out)} implied-population flags "
        f"({n_unexpl} not at a known split parent) "
        f"→ pipeline_out/audits/qa_implied_population.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 10 — Implied deflator smoothness (nominal ÷ real, base-2010 era)
# ---------------------------------------------------------------------------

def check10_deflator(total):
    """
    Within the total panel, nominal ÷ real (base 2010) is the implied GDP
    deflator. A transcription error in either series shows up as an isolated
    deflator jump. Flags YoY deflator changes beyond ±15%. Commodity-price
    episodes are genuine economics and will appear here (e.g. the 2022 coal
    price record produced +13% median deflator growth in coal provinces —
    verified against the HBA reference price). Does not fail the pipeline.
    """
    n = total[(total["table_type"] == "nominal") & (total["oil_excluded"] == False)][
        ["district_id", "province_canonical", "year", "value_standardized"]
    ].rename(columns={"value_standardized": "nom"})
    r = total[(total["table_type"] == "real") & (total["base_year"] == 2010)][
        ["district_id", "year", "value_standardized"]
    ].rename(columns={"value_standardized": "real"})
    d = n.merge(r, on=["district_id", "year"])
    d = d[(d["nom"] > 0) & (d["real"] > 0)].copy()
    d["deflator"] = d["nom"] / d["real"]
    d = d.sort_values(["district_id", "year"])
    d["defl_chg"] = d.groupby("district_id")["deflator"].pct_change()
    out = d[d["defl_chg"].abs() > 0.15].copy()

    if not len(out):
        return 0, "CHECK 10 PASS : implied deflator smooth everywhere (base-2010 era)"
    out.to_csv(AUDIT_DIR / "qa_deflator.csv", index=False)
    return 0, (
        f"CHECK 10 INFO : {len(out)} deflator jumps >15% "
        f"(commodity-price years expected) → pipeline_out/audits/qa_deflator.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 11 — Roster completeness (sandwich-missing districts)
# ---------------------------------------------------------------------------

ROSTER_SERIES = [
    "PDRB_1996-1999.csv", "PDRB_2000-2001.csv",
    "PDRB_2002-2004.csv", "PDRB_2005-2007.csv",
    "PDRB_2008-2010.csv", "PDRB_2011-2013.csv",
    "PDRB_2014-2016.csv", "PDRB_2017-2019.csv",
    "PDRB_2020-2022.csv", "PDRB_2021-2023.csv",
]

def check11_roster_completeness():
    """
    A district present in publication i-1 and i+1 but absent from publication i
    is the signature of a silently-collided name (data guide Section 7.12) or a
    dropped table page. Uses the native panel, which retains every source's
    rows. Expected result: zero.
    """
    nat = pd.read_csv(OUTPUT_DIR / "panel_pdrb_total_native.csv", low_memory=False)
    d = nat[nat["source_file"].isin(ROSTER_SERIES)]
    rosters = {
        f: set(zip(d.loc[d["source_file"] == f, "province_canonical"],
                   d.loc[d["source_file"] == f, "region_name_corrected"]))
        for f in ROSTER_SERIES
    }
    rows = []
    for i in range(1, len(ROSTER_SERIES) - 1):
        missing = (rosters[ROSTER_SERIES[i - 1]] & rosters[ROSTER_SERIES[i + 1]]) \
                  - rosters[ROSTER_SERIES[i]]
        for prov, name in sorted(missing):
            rows.append({"publication": ROSTER_SERIES[i],
                         "province_canonical": prov, "region_name_corrected": name})
    if not rows:
        return 0, "CHECK 11 PASS : no sandwich-missing districts across the 10 publications"
    out = pd.DataFrame(rows)
    out.to_csv(AUDIT_DIR / "qa_roster_completeness.csv", index=False)
    return 0, (
        f"CHECK 11 WARN : {len(out)} sandwich-missing districts (possible silent "
        f"name collision) → pipeline_out/audits/qa_roster_completeness.csv"
    )


# ---------------------------------------------------------------------------
# CHECK 12 — Frozen values (exact year-over-year repeats)
# ---------------------------------------------------------------------------

def check12_frozen_values():
    """
    A value that exactly repeats its prior year (to the rupiah) within the same
    series is invisible to CHECK 3 (growth anomalies): 0% year-over-year change
    trips no threshold. It is nonetheless a strong transcription-error signature
    — real districts do not report the identical rupiah figure two years running
    — and this class caught two confirmed errors during construction (Bojonegoro
    1999, both series duplicating 1998; Mandailing Natal 1996 duplicating 1997),
    both since corrected (correction_id P9_recover, P_MN96_dup). Runs on the
    native panels (source-level, pre-aggregation) so a real repeat is not
    diluted or created by child-summation.
    """
    group_key = ["district_id", "table_type", "base_year", "oil_excluded"]
    frames = []

    for label, fname in [("total", "panel_pdrb_total_native.csv"),
                         ("capita", "panel_pdrb_capita_native.csv")]:
        df = pd.read_csv(OUTPUT_DIR / fname, low_memory=False)
        df = df[(~df["is_pre_split_aggregate"].fillna(False).astype(bool)) &
                df["value_standardized"].notna() & (df["value_standardized"] > 0) &
                df["district_id"].notna()].copy()
        df = df.sort_values("source_priority").drop_duplicates(group_key + ["year"], keep="first")
        df = df.sort_values(group_key + ["year"])
        g = df.groupby(group_key, dropna=False)
        df["prev_value"] = g["value_standardized"].shift(1)
        df["prev_year"]  = g["year"].shift(1)
        frozen = df[(df["prev_year"] == df["year"] - 1) &
                   (df["value_standardized"] == df["prev_value"])].copy()
        if len(frozen):
            frozen["panel"] = label
            frames.append(frozen[["panel", "district_id", "year", "table_type",
                                  "base_year", "oil_excluded", "value_standardized",
                                  "source_file"]])

    if not frames:
        return 0, "CHECK 12 PASS : no frozen (exact year-over-year repeat) values"

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(AUDIT_DIR / "qa_frozen_values.csv", index=False)
    return len(out), (
        f"CHECK 12 WARN : {len(out)} frozen year-over-year values "
        f"→ pipeline_out/audits/qa_frozen_values.csv"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("PDRB PANEL — STAGE 6 QA AND VALIDATION v2")
    print("=" * 70)

    total  = pd.read_csv(OUTPUT_DIR / "panel_pdrb_total_2000bounds.csv",  low_memory=False)
    capita = pd.read_csv(OUTPUT_DIR / "panel_pdrb_capita_2000bounds.csv", low_memory=False)

    print(f"\nLoaded total  : {len(total):>7,} rows  "
          f"({total['district_id'].nunique()} districts, "
          f"years {int(total['year'].min())}–{int(total['year'].max())})")
    print(f"Loaded capita : {len(capita):>7,} rows  "
          f"({capita['district_id'].nunique()} districts, "
          f"years {int(capita['year'].min())}–{int(capita['year'].max())})")
    print()

    results = []
    results.append(check1_uniqueness(total, capita))
    results.append(check2_missing_years(total, capita))
    results.append(check3_growth_anomalies(total, capita))
    results.append(check4_province_totals())
    results.append(check5_overlap_revisions(total, capita))
    results.append(check6_null_parent_children())
    results.append(check7_district_gap(total, capita))
    results.append(check8_within_file_duplicates())
    results.append(check9_implied_population(total, capita))
    results.append(check10_deflator(total))
    results.append(check11_roster_completeness())
    results.append(check12_frozen_values())

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    total_fails = 0
    for n_issues, msg in results:
        print(f"  {msg}")
        if "FAIL" in msg:
            total_fails += n_issues

    print()
    if total_fails == 0:
        print("No FAIL checks.")
    else:
        print(f"{total_fails} FAIL issue(s) — review audit files in pipeline_out/audits/.")
    sys.exit(0 if total_fails == 0 else 1)


if __name__ == "__main__":
    main()
