"""
fix_misassigned_years.py — Heuristic fix for sparse-row year misassignment.

Problem: Claude at temperature=0 places lone values in the first year column for
newly-created (split-off) districts because pdfplumber text extraction strips
spatial column position. The value belongs in a later year column.

Heuristic: for BPS split-off districts, data appears in the most recent year(s)
of a publication — not the earliest. If a district has a non-null value in a year
before its creation year, move it to the latest year >= creation_year that is
currently empty.

Source of creation years: crosswalks/split_concordance.csv (pemekaran reference).

Usage:
    python scripts/fix_misassigned_years.py \
        --input pipeline_out/trial_b/csvs/PDRB_2000-2003_wide_b_7.csv \
        --output pipeline_out/trial_b/csvs/PDRB_2000-2003_wide_b_7_fixed.csv
"""

import argparse
import pandas as pd
from pathlib import Path


def load_creation_years(crosswalk_path: Path) -> pd.DataFrame:
    splits = pd.read_csv(crosswalk_path, dtype=str)
    splits = splits[['child_base', 'year']].drop_duplicates()
    splits = splits.rename(columns={'year': 'creation_year'})
    splits['creation_year'] = splits['creation_year'].astype(int)
    splits['name_norm'] = splits['child_base'].str.upper().str.strip()
    return splits[['name_norm', 'creation_year']]


def fix_misassigned(df: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['name_norm'] = df['region_name_raw'].str.upper().str.strip()
    df = df.merge(splits, on='name_norm', how='left')

    # BPS null markers: '-' means no data, '...' means not yet available, etc.
    BPS_NULL_MARKERS = {'-', '...', 'n.a.', 'n.a', 'na'}

    df['year_int'] = pd.to_numeric(df['year'], errors='coerce')
    df['_has_value'] = (
        df['value'].notna() &
        (df['value'].str.strip() != '') &
        (~df['value'].str.strip().isin(BPS_NULL_MARKERS))
    )

    df['value_raw'] = df['value']
    df['year_misassigned'] = False
    df['year_corrected'] = False

    misassigned_df = df[
        df['_has_value'] &
        df['creation_year'].notna() &
        (df['year_int'] < df['creation_year'])
    ].sort_values('year_int')

    claimed = set()  # target indices already assigned in this pass

    for idx, row in misassigned_df.iterrows():
        name = row['name_norm']
        flag = row['name_flag']
        value = row['value']
        creation_year = int(row['creation_year'])

        # candidate rows: same district + same name_flag, year >= creation, no value, not yet claimed
        candidates = df[
            (df['name_norm'] == name) &
            (df['name_flag'] == flag) &
            (df['year_int'] >= creation_year) &
            (~df['_has_value']) &
            (~df.index.isin(claimed))
        ]

        df.loc[idx, 'value'] = pd.NA
        df.loc[idx, 'year_misassigned'] = True

        if candidates.empty:
            print(f"  WARNING: no valid target year for {name!r} (flag={flag!r}, "
                  f"value={value!r}) — nullified, value preserved in value_raw")
            continue

        target_idx = candidates['year_int'].idxmax()
        claimed.add(target_idx)
        df.loc[target_idx, 'value'] = value
        df.loc[target_idx, 'year_corrected'] = True
        print(f"  MOVED: {name!r} flag={flag!r} | "
              f"year {int(row['year_int'])} → {int(df.loc[target_idx,'year_int'])} "
              f"| value={value!r}")

    df = df.drop(columns=['name_norm', 'year_int', '_has_value', 'creation_year'])
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--crosswalk', default='crosswalks/split_concordance.csv')
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str)
    splits = load_creation_years(Path(args.crosswalk))

    print(f"Input: {args.input} ({len(df)} rows)")
    fixed = fix_misassigned(df, splits)

    n_misassigned = fixed['year_misassigned'].sum()
    n_corrected = fixed['year_corrected'].sum()
    print(f"Misassigned rows nullified: {n_misassigned}")
    print(f"Rows receiving corrected value: {n_corrected}")

    fixed.to_csv(args.output, index=False)
    print(f"Output: {args.output}")

    if n_misassigned:
        print("\nAffected rows:")
        affected = fixed[fixed['year_misassigned'] | fixed['year_corrected']]
        print(affected[['region_name_raw', 'name_flag', 'year', 'value',
                         'value_raw', 'year_misassigned', 'year_corrected']].to_string())


if __name__ == '__main__':
    main()
