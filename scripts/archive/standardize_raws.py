# scripts/standardize_raws.py
# v1

"""
Per-file structural standardization.

Purpose:
- normalize schemas
- standardize units
- preserve raw geographic information
- extract semantic metadata from names
- remove mechanical formatting noise
- preserve reversibility

NO geographic harmonization performed here.
"""

from pathlib import Path
import pandas as pd
import numpy as np
import re

VERSION = "1.1"

# =========================================================
# CONFIG
# =========================================================

RAW_DIR = Path("raw/csv")
OUT_DIR = Path("standardized")
AUDIT_DIR = Path("audits")

OUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# COLUMN STANDARDIZATION
# =========================================================

COLUMN_MAP = {

    # province
    "province": "province_name_raw",
    "province_name": "province_name_raw",

    # region
    "region": "region_name_raw",
    "region_name": "region_name_raw",
    "kabupaten": "region_name_raw",

    # table number variants
    "table_num": "table_number",

    # codes
    "regency_code": "regency_code_raw",
    "region_code": "regency_code_raw",

    # values
    "pdrb": "value",
    "gdp": "value",
    "value_billion_rupiah": "value",
    "value_rupiah": "value",
    "value_thousand_rupiah": "value",

    # year flag
    "year_qualifier": "year_flag",
}

DISCARD_COLUMNS = ["price_basis"]

YEAR_FLAG_RECODE = {
    "preliminary": "*",
    "very_preliminary": "**",
}

# =========================================================
# CANONICAL SCHEMA
# =========================================================

STANDARD_COLUMNS = [

    # provenance
    "source_file",

    # province
    "province_name_raw",
    "province_name_clean",

    # region
    "region_name_raw",
    "region_name_clean",
    "region_name_base",

    # semantic metadata
    "admin_type",
    "footnote_marker",

    # codes
    "regency_code_raw",

    # time/value
    "year",
    "year_flag",
    "value",
    "value_flag",
    "value_standardized",

    # flags from parsing
    "name_flag",

    # units/prices
    "table_header_raw",
    "unit_raw",
    "unit",
    "unit_multiplier",
    "table_type",
    "price_type",
    "base_year",
    "base_year_raw",

    # flags
    "oil_excluded",
    "is_pre_split_aggregate",
    "row_type",
    "is_data_row",
    "has_numeric_name_contamination",

    # provenance
    "page_number",
    "table_number",
    "raw_text_hash",
]

# =========================================================
# UNIT STANDARDIZATION
# =========================================================

UNIT_MULTIPLIERS = {
    "billion rupiah": 1_000_000_000,
    "milyar rupiah": 1_000_000_000,
    "miliar rupiah": 1_000_000_000,
    "million rupiah": 1_000_000,
    "juta rupiah": 1_000_000,
    "thousand rupiah": 1_000,
    "ribu rupiah": 1_000,
    "rupiah": 1,
}

# =========================================================
# SEMANTIC EXTRACTION
# =========================================================

def extract_admin_type(x):

    if pd.isna(x):
        return np.nan

    x = str(x).upper().strip()

    if re.search(r"^KAB\.?\s", x):
        return "kabupaten"

    if re.search(r"^KOTA\s", x):
        return "kota"

    if re.search(r"^KODYA\s", x):
        return "kotamadya"

    return np.nan


def extract_footnote_marker(x):

    if pd.isna(x):
        return np.nan

    x = str(x).strip()

    m = re.search(r"(\d+\)|#\))$", x)

    if m:
        return m.group(1)

    return np.nan


def detect_oil_excluded(x):

    if pd.isna(x):
        return False

    x = str(x).upper()

    patterns = [
        r"EXCL\.?\s*OIL",
        r"TANPA\s*MIGAS",
        r"NON[\-\s]?MIGAS",
    ]

    return any(
        re.search(p, x)
        for p in patterns
    )


def detect_pre_split_aggregate(x):

    if pd.isna(x):
        return False

    return bool(
        re.search(r"pre.?split\s+aggregate", str(x), re.IGNORECASE)
    )


def coerce_bool(series):
    return series.map(
        lambda x: False if pd.isna(x) else str(x).strip().lower() == "true"
    )

# =========================================================
# CLEANING FUNCTIONS
# =========================================================

def clean_name(x):
    """
    Conservative mechanical normalization.

    Preserves semantic distinctions like:
    - KAB.
    - KOTA
    - KODYA

    Removes:
    - OCR spillover
    - HTML
    - punctuation noise
    - footnotes
    - EXCL OIL annotations
    """

    if pd.isna(x):
        return np.nan

    x = str(x).upper().strip()

    # remove html
    x = re.sub(r"<.*?>", " ", x)

    # remove numbering prefixes
    # example: "1. ACEH"
    x = re.sub(r"^\d+\.\s*", "", x)

    # remove oil annotations
    x = re.sub(
        r"\(?\s*EXCL\.?\s*OIL\s*\)?",
        "",
        x
    )

    x = re.sub(
        r"\(?\s*NON[\-\s]?MIGAS\s*\)?",
        "",
        x
    )

    x = re.sub(
        r"\(?\s*TANPA\s*MIGAS\s*\)?",
        "",
        x
    )

    # remove trailing footnotes
    x = re.sub(r"\s*(\d+\)|#\))$", "", x)

    # remove OCR numeric spillover
    x = re.sub(
        r"\s+\d[\d\.,OB\s]{3,}$",
        "",
        x
    )

    # normalize whitespace
    x = re.sub(r"\s+", " ", x)

    # remove pipe artifacts
    x = re.sub(r"[|]+", "", x)

    return x.strip()


def build_region_base(x):
    """
    More aggressive canonical base name.

    Removes administrative prefixes so:
    - KAB. BANDUNG
    - KOTA BANDUNG

    both map to:
    BANDUNG

    Useful for candidate matching later.
    """

    if pd.isna(x):
        return np.nan

    x = clean_name(x)

    x = re.sub(r"^KAB\.?\s+", "", x)
    x = re.sub(r"^KOTA\s+", "", x)
    x = re.sub(r"^KODYA\s+", "", x)

    x = re.sub(r"\s+", " ", x)

    return x.strip()


def detect_numeric_contamination(x):

    if pd.isna(x):
        return False

    return bool(
        re.search(
            r"\s+\d[\d\.,OB\s]{3,}$",
            str(x).upper()
        )
    )


def classify_row_type(region_name):

    if pd.isna(region_name):
        return "empty"

    x = str(region_name).upper().strip()

    if re.search(r"KAB\.?/KOTA", x):
        return "total_regmun"

    if re.search(r"REG\.?\s*/?\s*MUN\.?", x):
        return "total_regmun"

    if re.search(r"^JUMLAH|^JML\s|^TOTAL", x):
        return "total_regmun"

    if re.search(r"^(PROPINSI|PROVINSI|PROVINCE)", x):
        return "province"

    if re.search(r"KABUPATEN/KOTA", x):
        return "table_header"

    return "data"


def infer_price_type(table_type):

    if pd.isna(table_type):
        return np.nan

    x = str(table_type).lower()

    if "constant" in x or "konstan" in x:
        return "real"

    if "current" in x or "berlaku" in x:
        return "nominal"

    return np.nan


def extract_unit_raw(header):
    """Extract the unit substring from a verbatim table header."""
    if pd.isna(header):
        return np.nan
    patterns = [
        r"miliar rupiah", r"juta rupiah", r"ribu rupiah",
        r"billion rupiah", r"million rupiah", r"thousand rupiah",
        r"rupiah",  # must be last — substring of all patterns above
    ]
    h = str(header).lower()
    for p in patterns:
        if re.search(p, h):
            m = re.search(p, h)
            return str(header)[m.start():m.end()]
    return np.nan


def standardize_unit(unit):

    if pd.isna(unit):
        return np.nan

    unit_clean = (
        str(unit)
        .lower()
        .strip()
        .replace("_", " ")
    )

    for k, v in sorted(UNIT_MULTIPLIERS.items(), key=lambda x: -len(x[0])):

        if k in unit_clean:
            return v

    return np.nan

# =========================================================
# MAIN STANDARDIZATION
# =========================================================

def standardize_file(fp):

    print("\n" + "=" * 80)
    print(f"PROCESSING: {fp.name}")
    print("=" * 80)

    # -----------------------------------------------------
    # READ FILE
    # -----------------------------------------------------

    df = pd.read_csv(fp)

    print(f"Rows: {len(df):,}")
    print(f"Cols: {len(df.columns)}")

    # -----------------------------------------------------
    # RENAME COLUMNS
    # -----------------------------------------------------

    rename_dict = {
        c: COLUMN_MAP[c]
        for c in df.columns
        if c in COLUMN_MAP
    }

    df = df.rename(columns=rename_dict)

    # -----------------------------------------------------
    # SOURCE FILE
    # -----------------------------------------------------

    df["source_file"] = fp.name

    # -----------------------------------------------------
    # ENSURE COLUMNS
    # -----------------------------------------------------

    for col in STANDARD_COLUMNS:

        if col not in df.columns:
            df[col] = np.nan

    # -----------------------------------------------------
    # PRESERVE RAW BASE YEAR
    # -----------------------------------------------------

    df["base_year_raw"] = df["base_year"]

    # -----------------------------------------------------
    # DTYPE COERCION
    # -----------------------------------------------------

    df["year"] = pd.to_numeric(
        df["year"],
        errors="coerce"
    ).astype("Int64")

    df["value"] = pd.to_numeric(
        df["value"],
        errors="coerce"
    )

    df["base_year"] = pd.to_numeric(
        df["base_year"],
        errors="coerce"
    ).astype("Int64")

    # -----------------------------------------------------
    # OIL EXCLUDED
    # -----------------------------------------------------

    oil_from_name = df["region_name_raw"].apply(detect_oil_excluded)
    oil_from_header = df["table_header_raw"].apply(detect_oil_excluded)
    df["oil_excluded"] = oil_from_name | oil_from_header

    # -----------------------------------------------------
    # SEMANTIC EXTRACTION
    # -----------------------------------------------------

    df["admin_type"] = (
        df["region_name_raw"]
        .apply(extract_admin_type)
    )

    df["footnote_marker"] = (
        df["region_name_raw"]
        .apply(extract_footnote_marker)
    )

    df["is_pre_split_aggregate"] = (
        df["region_name_raw"]
        .apply(detect_pre_split_aggregate)
    )

    # -----------------------------------------------------
    # CLEAN NAMES
    # -----------------------------------------------------

    df["province_name_clean"] = (
        df["province_name_raw"]
        .apply(clean_name)
    )

    df["region_name_clean"] = (
        df["region_name_raw"]
        .apply(clean_name)
    )

    df["region_name_base"] = (
        df["region_name_raw"]
        .apply(build_region_base)
    )

    # -----------------------------------------------------
    # DETECT OCR CONTAMINATION
    # -----------------------------------------------------

    df["has_numeric_name_contamination"] = (
        df["region_name_raw"]
        .apply(detect_numeric_contamination)
    )

    # -----------------------------------------------------
    # PRICE TYPE
    # -----------------------------------------------------

    df["price_type"] = (
        df["table_type"]
        .apply(infer_price_type)
    )

    # -----------------------------------------------------
    # UNITS
    # -----------------------------------------------------

    df["unit_raw"] = df["table_header_raw"].apply(extract_unit_raw)

    df["unit"] = df["unit_raw"].apply(
        lambda x: str(x).lower().strip().replace("_", " ") if pd.notna(x) else np.nan
    )

    df["unit_multiplier"] = (
        df["unit"]
        .apply(standardize_unit)
    )

    df["value_standardized"] = (
        df["value"] * df["unit_multiplier"]
    )

    df.loc[
        df["unit_multiplier"].isna(),
        "value_standardized"
    ] = df["value"]

    # -----------------------------------------------------
    # ROW TYPE
    # -----------------------------------------------------

    df["row_type"] = (
        df["region_name_clean"]
        .apply(classify_row_type)
    )

    df.loc[df["is_pre_split_aggregate"], "row_type"] = "province"

    df["is_data_row"] = df["row_type"] == "data"

    # -----------------------------------------------------
    # YEAR FLAG
    # -----------------------------------------------------

    df["year_flag"] = df["year_flag"].map(
        lambda x: YEAR_FLAG_RECODE.get(str(x).strip(), x)
        if pd.notna(x) else x
    )

    # -----------------------------------------------------
    # DISCARD COLUMNS
    # -----------------------------------------------------

    df = df.drop(
        columns=[c for c in DISCARD_COLUMNS if c in df.columns]
    )

    # -----------------------------------------------------
    # REORDER
    # -----------------------------------------------------

    remaining_cols = [
        c for c in df.columns
        if c not in STANDARD_COLUMNS
    ]

    final_cols = STANDARD_COLUMNS + remaining_cols

    df = df[final_cols]

    # -----------------------------------------------------
    # EXPORT STANDARDIZED FILE
    # -----------------------------------------------------

    out_fp = OUT_DIR / fp.name

    df.to_csv(out_fp, index=False)

    print(f"Saved standardized file:")
    print(out_fp)

    # -----------------------------------------------------
    # OUTPUT SUMMARY
    # -----------------------------------------------------

    data_rows = df[df["row_type"] == "data"]
    n_provinces = df["province_name_raw"].nunique()
    n_regions = data_rows["region_name_raw"].nunique()
    n_years = data_rows["year"].nunique()
    year_range = (
        f"{int(data_rows['year'].min())}–{int(data_rows['year'].max())}"
        if data_rows["year"].notna().any() else "unknown"
    )
    value_coverage = (
        data_rows["value"].notna().sum() / len(data_rows) * 100
        if len(data_rows) > 0 else 0
    )
    oil_excl = int(df["oil_excluded"].sum())
    missing_cols = [c for c in STANDARD_COLUMNS if c not in df.columns]
    unexpected_types = set(
        df["row_type"].dropna().unique()
    ) - {"data", "total_regmun", "province", "table_header", "empty"}
    duplicates = int(df["raw_text_hash"].dropna().duplicated().sum())

    print("\nOUTPUT SUMMARY")
    print(f"  Provinces         : {n_provinces}")
    print(f"  Regions (data rows): {n_regions}")
    print(f"  Years covered     : {year_range} ({n_years} distinct years)")
    print(f"  Unit              : {df['unit'].dropna().unique().tolist()}")
    print(f"  Value coverage    : {value_coverage:.1f}% of data rows have a value")
    print(f"  Oil-excluded rows : {oil_excl:,}")
    print(f"  Duplicate hashes  : {duplicates:,}")
    print(f"  Numeric OCR flags : {int(df['has_numeric_name_contamination'].sum()):,}")
    print(f"  Pre-split agg rows: {int(df['is_pre_split_aggregate'].sum()):,}")
    if missing_cols:
        print(f"  MISSING COLS      : {missing_cols}")
    if unexpected_types:
        print(f"  UNEXPECTED ROW TYPES: {unexpected_types}")

    # -----------------------------------------------------
    # EXPORT SUSPICIOUS ROWS
    # -----------------------------------------------------

    suspicious = df.loc[
        (
            df["row_type"] != "data"
        ) |
        (
            df["has_numeric_name_contamination"]
        )
    ]

    audit_fp = (
        AUDIT_DIR /
        f"{fp.stem}_suspicious_rows.csv"
    )

    suspicious.to_csv(
        audit_fp,
        index=False
    )

    print(f"Suspicious rows flagged: {len(suspicious):,}")
    for rt, grp in suspicious.groupby("row_type"):
        print(f"  {rt}: {len(grp):,}")

# =========================================================
# RUN PIPELINE
# =========================================================

def main():

    csv_files = sorted(RAW_DIR.glob("*.csv"))

    if not csv_files:

        raise FileNotFoundError(
            f"No CSV files found in {RAW_DIR}"
        )

    print("=" * 80)
    print(f"FOUND {len(csv_files)} FILES")
    print(f"VERSION: {VERSION}")
    print("=" * 80)

    for fp in csv_files:

        try:
            standardize_file(fp)

        except Exception as e:

            print("\n" + "!" * 80)
            print(f"ERROR PROCESSING: {fp.name}")
            print(e)
            print("!" * 80)

    print("\n" + "=" * 80)
    print("STANDARDIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()