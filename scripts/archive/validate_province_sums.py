#!/usr/bin/env python3
"""
validate_province_sums.py — QA: compare district sums to published province totals.

For each publication × province × year × series, reads the province total row
and all district data rows from the standardized CSVs and raises three flag types:

  district_dominates  : a single district claims > SHARE_THRESH of province total.
                        Classic BPS source error signature (e.g. Fak-Fak 1999 =
                        62% of Irian Jaya total — caught mechanically by this check).

  sum_exceeds_total   : district sum > province total × RATIO_HIGH.
                        Indicates double-counting or a district value too large.

  large_gap           : district sum < province total × RATIO_LOW (after nulls).
                        A substantial portion of the province total is unexplained.
                        Can mean: known-bad district was nulled (expected), or an
                        uncorrected outlier inflated the published province total.

Runs on pipeline_out/standardized/ (post-correction, pre-harmonization).
Skips per-capita files — district per-capitas are a weighted average, not a sum.
Output: pipeline_out/audits/province_sum_validation.csv
"""

from pathlib import Path

import pandas as pd

STANDARDIZED_DIR = Path("pipeline_out/standardized")
OUT_PATH = Path("pipeline_out/audits/province_sum_validation.csv")

RATIO_HIGH   = 1.05   # district sum > 105% of province total → sum_exceeds_total
SHARE_THRESH = 0.55   # single district > 55% of province total → district_dominates
RATIO_LOW    = 0.50   # district sum < 50% of province total → large_gap

GROUP_COLS = ["province_name_clean", "year", "table_type", "base_year", "oil_excluded"]


def check_file(path: Path) -> list:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["value_standardized"] = pd.to_numeric(df["value_standardized"], errors="coerce")

    if "row_type" not in df.columns or "province_name_clean" not in df.columns:
        return []

    prov_rows = df[df["row_type"] == "province"]
    data_rows = df[df["row_type"] == "data"]
    flags = []

    for keys, prov_group in prov_rows.groupby(GROUP_COLS, dropna=False):
        province, year, table_type, base_year, oil_excluded = keys

        valid_totals = prov_group["value_standardized"].dropna()
        if valid_totals.empty:
            continue
        prov_total = valid_totals.iloc[0]
        if prov_total == 0 or pd.isna(prov_total):
            continue

        mask = (
            (data_rows["province_name_clean"] == province)
            & (data_rows["year"] == year)
            & (data_rows["table_type"] == table_type)
            & (data_rows["base_year"] == base_year)
            & (data_rows["oil_excluded"] == oil_excluded)
        )
        districts = data_rows[mask]
        if districts.empty:
            continue

        n_total  = len(districts)
        n_null   = int(districts["value_standardized"].isna().sum())
        dist_sum = districts["value_standardized"].sum(skipna=True)
        ratio    = dist_sum / prov_total

        base = {
            "source_file":   path.name,
            "province":      province,
            "year":          year,
            "table_type":    table_type,
            "base_year":     base_year,
            "oil_excluded":  oil_excluded,
            "prov_total_T":  round(prov_total / 1e12, 3),
            "dist_sum_T":    round(dist_sum   / 1e12, 3),
            "ratio":         round(ratio, 4),
            "n_districts":   n_total,
            "n_null":        n_null,
        }

        # Flag: single district dominates
        dominant = districts[
            districts["value_standardized"] > prov_total * SHARE_THRESH
        ]
        for _, row in dominant.iterrows():
            share = row["value_standardized"] / prov_total
            flags.append({
                **base,
                "flag":           "district_dominates",
                "offender":       row["region_name_raw"],
                "district_share": round(share, 3),
            })

        # Flag: district sum exceeds province total
        if ratio > RATIO_HIGH:
            big = districts[
                districts["value_standardized"] > prov_total * 0.25
            ]["region_name_raw"].tolist()
            flags.append({
                **base,
                "flag":    "sum_exceeds_total",
                "offender": "; ".join(big) if big else "multiple",
                "district_share": None,
            })

        # Flag: large unexplained gap (only meaningful if not all districts are null)
        if n_null < n_total and ratio < RATIO_LOW:
            flags.append({
                **base,
                "flag":    "large_gap",
                "offender": f"{n_null}/{n_total} districts null — sum is {ratio:.1%} of total",
                "district_share": None,
            })

    return flags


def main():
    files = sorted(
        f for f in STANDARDIZED_DIR.glob("*.csv")
        if "capita" not in f.name.lower()
    )
    print(f"Checking {len(files)} total-PDRB standardized files...\n")

    all_flags = []
    for path in files:
        flags = check_file(path)
        status = f"{len(flags)} flag(s)" if flags else "OK"
        print(f"  {path.name:45s} {status}")
        all_flags.extend(flags)

    if not all_flags:
        print("\nNo flags. Province sums look clean.")
        return

    out = pd.DataFrame(all_flags)

    sort_order = {"district_dominates": 0, "sum_exceeds_total": 1, "large_gap": 2}
    out["_sort"] = out["flag"].map(sort_order)
    out = (
        out.sort_values(["_sort", "source_file", "province", "year", "table_type"])
        .drop(columns=["_sort"])
        .reset_index(drop=True)
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    print(f"\n{'='*60}")
    print(f"Total flags: {len(all_flags)}")
    print(out["flag"].value_counts().to_string())
    print(f"\nSaved to {OUT_PATH}")

    dom = out[out["flag"] == "district_dominates"].copy()
    if not dom.empty:
        print("\n--- district_dominates (most actionable — potential BPS source errors) ---")
        print(
            dom[[
                "source_file", "province", "year", "table_type",
                "offender", "district_share", "prov_total_T",
            ]].to_string(index=False)
        )

    exceed = out[out["flag"] == "sum_exceeds_total"]
    if not exceed.empty:
        print("\n--- sum_exceeds_total ---")
        print(
            exceed[[
                "source_file", "province", "year", "table_type",
                "ratio", "prov_total_T", "dist_sum_T", "offender",
            ]].to_string(index=False)
        )


if __name__ == "__main__":
    main()
