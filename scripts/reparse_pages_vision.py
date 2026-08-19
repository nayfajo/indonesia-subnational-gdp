"""
reparse_pages_vision.py — Re-run specific pages in vision mode to fix misassigned rows.

Approach A: after text-mode parse, detect misassigned page numbers via split_concordance,
re-run only those pages in vision mode (Claude sees rendered image, reads column positions
correctly), output a patch CSV.

Workflow:
1. Load parsed CSV + split_concordance → find misassigned page_numbers
2. For each page, call vision mode on that single page from the PDF
3. Parse using same Group B parser (parse_response + melt_to_long)
4. Write patch CSV; print before/after comparison for affected districts

Usage:
    .venv/bin/python3.14 scripts/reparse_pages_vision.py \\
        --csv pipeline_out/trial_b/csvs/PDRB_2000-2003_wide_b_7.csv \\
        --pdf raw/pdf/PDRB_2000-2003.pdf \\
        --output pipeline_out/trial_b/csvs/PDRB_2000-2003_wide_b_7_vision_patch.csv
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import anthropic
import pandas as pd


BPS_NULL_MARKERS = {'-', '...', 'n.a.', 'n.a', 'na'}


def load_parse_b() -> object:
    spec = importlib.util.spec_from_file_location(
        "parse_b", Path(__file__).parent / "parse_pdfs_text.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_misassigned_pages(csv_path: Path, crosswalk_path: Path) -> tuple[set[int], set[str]]:
    df = pd.read_csv(csv_path, dtype=str)
    splits = pd.read_csv(crosswalk_path, dtype=str)
    splits = splits[['child_base', 'year']].drop_duplicates()
    splits = splits.rename(columns={'year': 'creation_year'})
    splits['creation_year'] = splits['creation_year'].astype(int)
    splits['name_norm'] = splits['child_base'].str.upper().str.strip()
    df['name_norm'] = df['region_name_raw'].str.upper().str.strip()
    df = df.merge(splits[['name_norm', 'creation_year']], on='name_norm', how='left')
    df['year_int'] = pd.to_numeric(df['year'], errors='coerce')
    df['_has_value'] = (
        df['value'].notna() &
        (df['value'].str.strip() != '') &
        (~df['value'].str.strip().isin(BPS_NULL_MARKERS))
    )
    misassigned = df[
        df['_has_value'] &
        df['creation_year'].notna() &
        (df['year_int'] < df['creation_year'])
    ]
    pages = set(
        pd.to_numeric(misassigned['page_number'], errors='coerce')
        .dropna().astype(int).unique()
    )
    district_names = set(misassigned['name_norm'].unique())

    print(f"Misassigned rows: {len(misassigned)}")
    for _, row in misassigned.iterrows():
        print(f"  {row['region_name_raw']!r} flag={row['name_flag']!r} "
              f"year={row['year']} value={row['value']!r} page={row['page_number']}")
    print(f"Pages to re-run: {sorted(pages)}")
    return pages, district_names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', required=True)
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--crosswalk', default='crosswalks/split_concordance.csv')
    parser.add_argument('--api-key', default=os.environ.get('ANTHROPIC_API_KEY'))
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("ANTHROPIC_API_KEY not set.")

    parse_b = load_parse_b()
    client = anthropic.Anthropic(api_key=args.api_key, timeout=600)

    pages, district_names = get_misassigned_pages(Path(args.csv), Path(args.crosswalk))
    if not pages:
        print("No misassigned rows found — nothing to re-run.")
        return

    pdf_path = Path(args.pdf)
    all_rows = []

    for page_num in sorted(pages):
        print(f"\nRe-running page {page_num} in vision mode…")
        pdf_b64 = parse_b.pdf_page_range_b64(pdf_path, page_num, page_num)
        raw = parse_b.call_vision(client, pdf_b64)
        headers_df, data_df, anomalies = parse_b.parse_response(raw)
        rows = parse_b.melt_to_long(headers_df, data_df)
        print(f"  → {len(rows)} rows parsed from page {page_num}")
        if anomalies:
            print(f"  Anomalies ({len(anomalies)}): {anomalies[:3]}")
        all_rows.extend(rows)

    if not all_rows:
        print("No rows parsed from vision re-run.")
        return

    patch_df = pd.DataFrame(all_rows, columns=parse_b.REQUIRED_COLUMNS)
    patch_df.to_csv(args.output, index=False)
    print(f"\nPatch CSV: {args.output} ({len(patch_df)} rows)")

    # before/after comparison for the affected districts
    patch_df['name_norm'] = patch_df['region_name_raw'].str.upper().str.strip()
    relevant = patch_df[patch_df['name_norm'].isin(district_names)]

    original = pd.read_csv(Path(args.csv), dtype=str)
    original['name_norm'] = original['region_name_raw'].str.upper().str.strip()
    orig_relevant = original[original['name_norm'].isin(district_names)]

    print("\n── BEFORE (text mode) ──")
    if not orig_relevant.empty:
        print(orig_relevant[['region_name_raw', 'name_flag', 'year', 'value']].to_string(index=False))
    else:
        print("  (no rows found)")

    print("\n── AFTER (vision mode) ──")
    if not relevant.empty:
        print(relevant[['region_name_raw', 'name_flag', 'year', 'value']].to_string(index=False))
    else:
        print("  (no rows found — district name may differ between modes)")


if __name__ == '__main__':
    main()
