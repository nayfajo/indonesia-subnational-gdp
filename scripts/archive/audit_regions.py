# scripts/audit_regions.py

"""
Geographic auditing stage.

Purpose:
- inventory province and region names
- identify likely duplicates
- identify unresolved OCR artifacts
- summarize harmonization workload

NO harmonization performed here.
Audit only.
"""

from pathlib import Path
import pandas as pd
import numpy as np
import re

# =========================================================
# CONFIG
# =========================================================

STANDARDIZED_DIR = Path("standardized")
AUDIT_DIR = Path("audits")

AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# SUSPICIOUS NAME DETECTION
# =========================================================

def detect_suspicious_name(x):

    if pd.isna(x):
        return False

    x = str(x)

    patterns = [
        r"\d+\)$",
        r"<.*?>",
        r"\.\.+",
        r"/",
        r"\(",
        r"\s{2,}",
        r"[^\w\s\.\-/\(\)]",
    ]

    return any(
        re.search(p, x)
        for p in patterns
    )

# =========================================================
# MAIN
# =========================================================

def main():

    # -----------------------------------------------------
    # LOAD STANDARDIZED FILES
    # -----------------------------------------------------

    csv_files = sorted(STANDARDIZED_DIR.glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found in {STANDARDIZED_DIR}"
        )

    print("=" * 80)
    print(f"FOUND {len(csv_files)} STANDARDIZED FILES")
    print("=" * 80)

    dfs = []

    for fp in csv_files:
        print(f"Loading: {fp.name}")
        df = pd.read_csv(fp)
        df["source_file"] = fp.name
        dfs.append(df)

    panel = pd.concat(dfs, ignore_index=True)

    print("\nCOMBINED PANEL")
    print(f"Rows: {len(panel):,}")
    print(f"Cols: {len(panel.columns)}")

    # -----------------------------------------------------
    # FILTER TO DATA ROWS
    # -----------------------------------------------------

    excluded = pd.DataFrame()

    if "is_data_row" in panel.columns:

        panel_all = panel.copy()

        panel = panel_all.loc[
            panel_all["is_data_row"] == True
        ].copy()

        excluded = panel_all.loc[
            panel_all["is_data_row"] != True
        ].copy()

        excluded.to_csv(
            AUDIT_DIR / "excluded_non_data_rows.csv",
            index=False
        )

        print("\nFILTERED NON-DATA ROWS")
        print(f"Before:   {len(panel_all):,}")
        print(f"After:    {len(panel):,}")
        print(f"Excluded: {len(excluded):,}")

    # -----------------------------------------------------
    # BASIC UNIQUES
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("UNIQUE COUNTS")
    print("=" * 80)

    province_unique = (
        panel["province_name_clean"]
        .dropna()
        .nunique()
    )

    region_unique = (
        panel["region_name_clean"]
        .dropna()
        .nunique()
    )

    print(f"Unique provinces: {province_unique:,}")
    print(f"Unique regions:   {region_unique:,}")

    # -----------------------------------------------------
    # UNIQUE PROVINCES
    # -----------------------------------------------------

    province_audit = (
        panel[
            [
                "province_name_raw",
                "province_name_clean",
                "source_file",
            ]
        ]
        .drop_duplicates()
        .sort_values(["province_name_clean", "province_name_raw"])
    )

    province_audit.to_csv(
        AUDIT_DIR / "unique_provinces.csv",
        index=False
    )

    print(f"\nSaved: {AUDIT_DIR / 'unique_provinces.csv'}")

    # -----------------------------------------------------
    # UNIQUE REGIONS
    # -----------------------------------------------------

    region_audit = (
        panel[
            [
                "province_name_clean",
                "region_name_raw",
                "region_name_clean",
                "regency_code_raw",
                "source_file",
            ]
        ]
        .drop_duplicates()
        .sort_values(["province_name_clean", "region_name_clean"])
    )

    region_audit.to_csv(
        AUDIT_DIR / "unique_regions.csv",
        index=False
    )

    print(f"Saved: {AUDIT_DIR / 'unique_regions.csv'}")

    # -----------------------------------------------------
    # SUSPICIOUS REGION NAMES
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("DETECTING SUSPICIOUS REGION NAMES")
    print("=" * 80)

    suspicious = panel.loc[
        panel["region_name_clean"]
        .apply(detect_suspicious_name)
    ]

    suspicious = suspicious[
        [
            "province_name_clean",
            "region_name_raw",
            "region_name_clean",
            "source_file",
        ]
    ].drop_duplicates()

    suspicious.to_csv(
        AUDIT_DIR / "suspicious_region_names.csv",
        index=False
    )

    print(f"Suspicious names: {len(suspicious):,}")
    print(f"Saved: {AUDIT_DIR / 'suspicious_region_names.csv'}")

    # -----------------------------------------------------
    # REGION VARIANT COUNTS
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("REGION VARIANT COUNTS")
    print("=" * 80)

    variant_counts = (
        panel[["region_name_clean", "region_name_raw"]]
        .drop_duplicates()
        .groupby("region_name_clean")
        .agg(raw_variant_count=("region_name_raw", "nunique"))
        .reset_index()
        .sort_values("raw_variant_count", ascending=False)
    )

    variant_counts.to_csv(
        AUDIT_DIR / "region_variant_counts.csv",
        index=False
    )

    print(f"Saved: {AUDIT_DIR / 'region_variant_counts.csv'}")

    # -----------------------------------------------------
    # BASE NAME CONFLICTS
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("BASE NAME CONFLICTS")
    print("=" * 80)

    base_conflicts = pd.DataFrame()

    if "region_name_base" in panel.columns:

        base_conflicts = (
            panel[["region_name_clean", "region_name_base"]]
            .drop_duplicates()
            .groupby("region_name_base")
            .filter(
                lambda g: g["region_name_clean"].nunique() > 1
            )
            .sort_values("region_name_base")
        )

        base_conflicts.to_csv(
            AUDIT_DIR / "base_name_conflicts.csv",
            index=False
        )

        print(f"Base name conflicts: {len(base_conflicts):,}")
        print(f"Saved: {AUDIT_DIR / 'base_name_conflicts.csv'}")

    else:
        print("region_name_base not found — skipping")

    # -----------------------------------------------------
    # REGION FREQUENCY + TEMPORAL COVERAGE
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("REGION FREQUENCY + TEMPORAL COVERAGE")
    print("=" * 80)

    region_frequency = (
        panel
        .groupby(["province_name_clean", "region_name_clean"])
        .agg(
            obs_count=("region_name_clean", "size"),
            n_years=("year", "nunique"),
            first_year=("year", "min"),
            last_year=("year", "max"),
            n_source_files=("source_file", "nunique"),
            raw_name_variants=("region_name_raw", "nunique"),
        )
        .reset_index()
        .sort_values(["obs_count", "n_years"], ascending=False)
    )

    region_frequency.to_csv(
        AUDIT_DIR / "region_frequency_temporal.csv",
        index=False
    )

    print(f"Saved: {AUDIT_DIR / 'region_frequency_temporal.csv'}")

    # -----------------------------------------------------
    # RARE REGIONS
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("SINGLETON / RARE REGION CHECK")
    print("=" * 80)

    rare_regions = region_frequency.loc[
        region_frequency["obs_count"] <= 2
    ].copy()

    rare_regions.to_csv(
        AUDIT_DIR / "rare_regions.csv",
        index=False
    )

    print(f"Rare regions: {len(rare_regions):,}")
    print(f"Saved: {AUDIT_DIR / 'rare_regions.csv'}")

    # -----------------------------------------------------
    # TEMPORAL GAP CHECK
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("TEMPORAL GAP CHECK")
    print("=" * 80)

    gap_records = []

    grouped = panel.groupby(
        ["province_name_clean", "region_name_clean"]
    )

    for (province, region), g in grouped:

        years = sorted(g["year"].dropna().unique())

        if len(years) <= 1:
            continue

        gaps = []

        for i in range(len(years) - 1):

            current_year = years[i]
            next_year = years[i + 1]

            if next_year - current_year > 1:
                missing = list(range(current_year + 1, next_year))
                gaps.extend(missing)

        if gaps:
            gap_records.append({
                "province_name_clean": province,
                "region_name_clean": region,
                "first_year": min(years),
                "last_year": max(years),
                "missing_years": ",".join(map(str, gaps)),
                "n_missing_years": len(gaps),
            })

    gap_df = pd.DataFrame(gap_records)

    gap_df.to_csv(
        AUDIT_DIR / "region_temporal_gaps.csv",
        index=False
    )

    print(f"Regions with gaps: {len(gap_df):,}")
    print(f"Saved: {AUDIT_DIR / 'region_temporal_gaps.csv'}")

    # -----------------------------------------------------
    # MULTIPLE CODES
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("MULTIPLE CODE CHECK")
    print("=" * 80)

    multi_code = pd.DataFrame()

    if "regency_code_raw" in panel.columns:

        multi_code = (
            panel[
                [
                    "province_name_clean",
                    "region_name_clean",
                    "regency_code_raw",
                ]
            ]
            .dropna(subset=["regency_code_raw"])
            .drop_duplicates()
            .groupby(["province_name_clean", "region_name_clean"])
            .agg(code_count=("regency_code_raw", "nunique"))
            .reset_index()
            .query("code_count > 1")
            .sort_values("code_count", ascending=False)
        )

        multi_code.to_csv(
            AUDIT_DIR / "regions_multiple_codes.csv",
            index=False
        )

        print(f"Regions with multiple codes: {len(multi_code):,}")
        print(f"Saved: {AUDIT_DIR / 'regions_multiple_codes.csv'}")

    else:
        print("regency_code_raw not found — skipping")

# -----------------------------------------------------
    # MASTER AUDIT WORKBOOK
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("WRITING MASTER AUDIT WORKBOOK")
    print("=" * 80)

    master_fp = AUDIT_DIR / "master_audit.xlsx"

    # build metadata sheet
    metadata = pd.DataFrame([
        {
            "sheet": "README",
            "description": "This file. Sheet index and usage notes.",
            "rows_represent": "One row per sheet",
            "key_columns": "sheet, description",
            "notes": f"Generated by audit_regions.py. Source: {STANDARDIZED_DIR}. Files loaded: {len(csv_files)}.",
        },
        {
            "sheet": "provinces",
            "description": "All unique province name variants observed across standardized files.",
            "rows_represent": "One row per unique (province_name_raw, province_name_clean, source_file) combination",
            "key_columns": "province_name_raw, province_name_clean, source_file",
            "notes": "Use to identify inconsistent province naming across files. No harmonization applied.",
        },
        {
            "sheet": "regions",
            "description": "All unique region name variants observed across standardized files.",
            "rows_represent": "One row per unique (province, region_raw, region_clean, code, source_file) combination",
            "key_columns": "region_name_raw, region_name_clean, regency_code_raw",
            "notes": "Primary inventory of all region names. Starting point for harmonization review.",
        },
        {
            "sheet": "suspicious_names",
            "description": "Region names that passed standardization cleaning but still contain likely OCR artifacts or formatting noise.",
            "rows_represent": "One row per suspicious (province, region_raw, region_clean, source_file) combination",
            "key_columns": "region_name_raw, region_name_clean",
            "notes": "Requires manual review. Flags: footnote markers, HTML remnants, repeated punctuation, parentheses, unusual characters.",
        },
        {
            "sheet": "variant_counts",
            "description": "How many distinct raw spellings map to each cleaned region name.",
            "rows_represent": "One row per unique region_name_clean",
            "key_columns": "region_name_clean, raw_variant_count",
            "notes": "High raw_variant_count indicates OCR inconsistency or name changes over time. Sort descending to find worst cases.",
        },
        {
            "sheet": "base_name_conflicts",
            "description": "Clean region names that share the same base name after stripping KAB./KOTA/KODYA prefixes.",
            "rows_represent": "One row per (region_name_base, region_name_clean) pair where base has multiple clean variants",
            "key_columns": "region_name_base, region_name_clean",
            "notes": "Candidates for cross-prefix entity resolution in harmonization. E.g. KAB. BANDUNG and KOTA BANDUNG both appear under BANDUNG. Does not mean they are the same entity.",
        },
        {
            "sheet": "frequency_temporal",
            "description": "Per-region observation counts and temporal coverage across all source files.",
            "rows_represent": "One row per (province, region) pair",
            "key_columns": "obs_count, n_years, first_year, last_year, n_source_files, raw_name_variants",
            "notes": "Use to assess data density and coverage. Regions with low n_years relative to (last_year - first_year) may have gaps.",
        },
        {
            "sheet": "rare_regions",
            "description": "Regions with 2 or fewer total observations across all files.",
            "rows_represent": "One row per (province, region) pair with obs_count <= 2",
            "key_columns": "obs_count, n_years, first_year, last_year",
            "notes": "Likely causes: OCR misread producing one-off name variant, genuine short-lived administrative unit, or data entry error.",
        },
        {
            "sheet": "temporal_gaps",
            "description": "Regions with missing years within their observed time span.",
            "rows_represent": "One row per (province, region) pair that has at least one gap",
            "key_columns": "missing_years, n_missing_years, first_year, last_year",
            "notes": "missing_years is a comma-separated list of absent years. Does not flag truncation — a region that simply stops appearing is not shown here.",
        },
        {
            "sheet": "excluded_rows",
            "description": "Rows filtered out by is_data_row == False before audit analysis ran.",
            "rows_represent": "One row per excluded panel row",
            "key_columns": "region_name_raw, region_name_clean, is_data_row",
            "notes": "Includes totals, province headers, table structure rows. Present for completeness — no data is discarded from source files.",
        },
        {
            "sheet": "multiple_codes",
            "description": "Regions associated with more than one regency_code_raw value.",
            "rows_represent": "One row per (province, region) pair with code_count > 1",
            "key_columns": "code_count",
            "notes": "Possible causes: administrative boundary changes, code reassignment, or OCR errors in code column. Cross-reference with frequency_temporal for temporal context.",
        },
    ])

    with pd.ExcelWriter(
        master_fp,
        engine="openpyxl"
    ) as writer:

        # write README first so it's the landing sheet
        metadata.to_excel(
            writer, sheet_name="README", index=False
        )

        province_audit.to_excel(
            writer, sheet_name="provinces", index=False
        )

        region_audit.to_excel(
            writer, sheet_name="regions", index=False
        )

        suspicious.to_excel(
            writer, sheet_name="suspicious_names", index=False
        )

        variant_counts.to_excel(
            writer, sheet_name="variant_counts", index=False
        )

        if not base_conflicts.empty:
            base_conflicts.to_excel(
                writer, sheet_name="base_name_conflicts", index=False
            )

        region_frequency.to_excel(
            writer, sheet_name="frequency_temporal", index=False
        )

        rare_regions.to_excel(
            writer, sheet_name="rare_regions", index=False
        )

        gap_df.to_excel(
            writer, sheet_name="temporal_gaps", index=False
        )

        if not excluded.empty:
            excluded.to_excel(
                writer, sheet_name="excluded_rows", index=False
            )

        if not multi_code.empty:
            multi_code.to_excel(
                writer, sheet_name="multiple_codes", index=False
            )

    print(f"Saved: {master_fp}")

    # -----------------------------------------------------
    # SUMMARY REPORT
    # -----------------------------------------------------

    print("\n" + "=" * 80)
    print("AUDIT SUMMARY")
    print("=" * 80)

    print(f"Unique provinces:        {province_unique:,}")
    print(f"Unique regions:          {region_unique:,}")
    print(f"Suspicious region names: {len(suspicious):,}")
    print(f"Base name conflicts:     {len(base_conflicts):,}")
    print(f"Regions with gaps:       {len(gap_df):,}")
    print(f"Rare regions:            {len(rare_regions):,}")
    print(f"Excluded rows:           {len(excluded):,}")

    if not multi_code.empty:
        print(f"Regions w/ multiple codes: {len(multi_code):,}")
    else:
        print(f"Regions w/ multiple codes: 0")

    print("\nAUDIT COMPLETE")


if __name__ == "__main__":
    main()