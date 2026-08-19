# scripts/standardize_pipeline.py
# v1.0
#
# Standardizes pipeline-parsed CSVs (pipeline_out/full_runs/corrected_csvs/)
# into the canonical schema used by harmonize_regions.py and build_panel.py.
#
# Reads  : pipeline_out/full_runs/corrected_csvs/*.csv  (output of apply_corrections.py)
# Writes : pipeline_out/standardized/*.csv
# Audits : pipeline_out/audits/
#
# Key differences from standardize_raws.py (which reads raw/csv/):
#   - Deduplication on raw_text_hash (resume re-runs can produce duplicates)
#   - Value cleaning: removes BPS watermark artifact letters; handles
#     Indonesian comma-decimal format (Group A/B) and period-decimal (Group C)
#   - table_type and base_year derived from table_header_raw (not from parser)
#   - oil_excluded detected from name_flag structure (not string-matched)
#   - is_pre_split_aggregate detected from name_flag == '#)'
#   - table_header_english preserved as extra column

from pathlib import Path
import pandas as pd
import numpy as np
import re

VERSION = "1.9"

IN_DIR    = Path("pipeline_out/full_runs/corrected_csvs")
OUT_DIR   = Path("pipeline_out/standardized")
AUDIT_DIR = Path("pipeline_out/audits")

OUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# UNIT MULTIPLIERS
# Longest-key-first order for correct substring matching.
# =========================================================

UNIT_MULTIPLIERS = [
    ("billion rupiah",  1_000_000_000),
    ("milyar rupiah",   1_000_000_000),
    ("miliar rupiah",   1_000_000_000),
    ("million rupiah",  1_000_000),
    ("jutaan rupiah",   1_000_000),
    ("juta rupiah",     1_000_000),
    ("thousand rupiah", 1_000),
    ("ribu rupiah",     1_000),
    ("rupiah",          1),
]

UNIT_EXTRACT_PATTERNS = [
    r"miliar rupiah",
    r"milyar rupiah",
    r"jutaan rupiah",
    r"juta rupiah",
    r"ribu rupiah",
    r"billion rupiah",
    r"million rupiah",
    r"thousand rupiah",
    r"rupiah",  # must be last: substring of all above
]

# =========================================================
# CANONICAL SCHEMA
# Must match standardize_raws.py STANDARD_COLUMNS exactly
# so harmonize_regions.py and build_panel.py work unchanged.
# =========================================================

STANDARD_COLUMNS = [
    "source_file",
    "province_name_raw",
    "province_name_clean",
    "region_name_raw",
    "region_name_clean",
    "region_name_base",
    "admin_type",
    "footnote_marker",
    "regency_code_raw",
    "year",
    "year_flag",
    "value",
    "value_flag",
    "value_standardized",
    "name_flag",
    "table_header_raw",
    "unit_raw",
    "unit",
    "unit_multiplier",
    "table_type",
    "price_type",
    "base_year",
    "base_year_raw",
    "oil_excluded",
    "is_pre_split_aggregate",
    "row_type",
    "is_data_row",
    "has_numeric_name_contamination",
    "page_number",
    "table_number",
    "raw_text_hash",
]

# =========================================================
# VALUE CLEANING
# =========================================================

# Strings that represent "no data" after artifact removal
_NULL_MARKERS = {"", "-", "...", "n.a.", "n.a", "na"}


def clean_value(raw, period_is_thousands=False):
    """
    Clean a raw value string from the parsed CSV.

    Returns (float_or_nan, value_type) where value_type is one of:
      'numeric'          — parsed cleanly with no changes
      'artifact_cleaned' — stray letters removed before parsing
      'non_numeric'      — could not parse (garbled OCR, unknown artifact)
      'source_null'      — source cell was NaN/empty or a BPS null marker (-, --, …)
      Note: 'null' is intentionally avoided — pandas read_csv treats it as NaN.

    Format detected by which separator appears last:
      Indonesian (period=thousands, comma=decimal): '138.801,52' → comma last → 138801.52
      English   (comma=thousands, period=decimal):  '197,253.22' → period last → 197253.22

    period_is_thousands is kept as a parameter for compatibility but no longer gates the
    single-period rule (see v1.6 note below).

    v1.5 additions:
      - Consecutive periods collapsed: '23..243' → '23.243'
      - Leading period stripped: '.4.958' → '4.958'
      - Multi-period thousands universal: '1.223.310' → 1223310

    v1.6 additions:
      - Single-period 3-digit rule now universal (was era-gated ≤2007): BPS consistently
        uses period=thousands across all publication years; pdfplumber preserves this.
        '7.308' miliar → 7308, '91.852' ribu → 91852. Affects ~25k rows in 2008+ files.
      - OCR-split thousands: '42.1.08' → 42108 (pdfplumber split a 5-digit group).
      - Leading/trailing junk strip: ':/4.110.950,99' → '4.110.950,99',
        '10278.619^»' → '10278.619'.
      - Fused decimal (≤2007): '1.454.70412' → 1454704.12 (OCR dropped comma in decimal).
    """
    if pd.isna(raw):
        return np.nan, "source_null"

    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return np.nan, "source_null"

    original = s

    # Remove stray ASCII letters (BPS watermark URL artifact: bps.go.id)
    s = re.sub(r"[a-zA-Z]", "", s)
    # Collapse spaces (split-number artifact: '2 .043' → '2.043')
    s = s.replace(" ", "")
    # Collapse consecutive periods ('23..243' → '23.243', double OCR artifact)
    s = re.sub(r"\.{2,}", ".", s)
    # Strip trailing periods ('3.241.' → '3.241')
    s = s.rstrip(".")
    # Strip leading periods (pdfplumber cell-split artifact: '.4.958' → '4.958')
    s = s.lstrip(".")
    # Normalize Unicode minus/en-dash/em-dash to ASCII hyphen, then collapse multiples.
    # Catches: − (U+2212), – (U+2013), — (U+2014), and double-dash '--'.
    s = re.sub(r"[−–—]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip()

    if not s:
        return np.nan, "non_numeric"
    if s in _NULL_MARKERS:
        return np.nan, "source_null"

    # Strip leading non-numeric prefix (BPS watermark / footnote text bleeding into cell).
    # E.g. ':/4.110.950,99' → '4.110.950,99', ':/141' → '141'.
    # BUG B fix: strip leading minus too — PDRB values are never legitimately negative.
    s = re.sub(r'^[^0-9]+', '', s)
    # Strip trailing non-numeric suffix (OCR artifacts like '^»', ')').
    # E.g. '10278.619^»' → '10278.619'.
    s = re.sub(r'[^0-9.,]+$', '', s)

    if not s:
        return np.nan, "non_numeric"

    artifact_cleaned = s != original

    # Detect decimal format from which separator appears last:
    #   Indonesian (period=thousands, comma=decimal): '138.801,52' → comma last
    #   English   (comma=thousands, period=decimal):  '197,253.22' → period last
    last_comma  = s.rfind(",")
    last_period = s.rfind(".")
    if last_comma != -1 and last_period != -1:
        if last_comma > last_period:
            # Indonesian: remove thousand-periods, comma → decimal point
            s = s.replace(".", "").replace(",", ".")
        else:
            # English: remove thousand-commas, keep period as decimal
            s = s.replace(",", "")
    elif last_comma != -1:
        # Only commas present
        after_comma = s[last_comma + 1:]
        if len(after_comma) == 3:
            # Thousands separator (e.g. '197,253') → strip commas
            s = s.replace(",", "")
        else:
            # Decimal comma (e.g. '647,98') → replace comma
            s = s.replace(",", ".")
    elif last_period != -1:
        parts = s.split(".")
        all_digit_groups = all(p.isdigit() for p in parts)
        all_3digit_after_first = all(len(p) == 3 for p in parts[1:])
        # Multi-period thousands: unambiguous regardless of era ('1.223.310' → 1223310).
        multi_period = len(parts) > 2 and all_digit_groups and all_3digit_after_first
        # Single-period thousands: BPS uses period=thousands across ALL publication years.
        # pdfplumber preserves the original Indonesian formatting, so x.yyy with a 3-digit
        # tail is ALWAYS a thousands separator, never a decimal. '7.308' miliar → 7308.
        single_period_era = all_digit_groups and all_3digit_after_first
        # OCR-split thousands: pdfplumber occasionally splits a thousands group, producing
        # x.y.zz where the middle group is 1-2 digits instead of 3. This cannot be a
        # valid decimal (two decimal points are invalid) or a valid Indonesian thousands
        # format (which requires exactly 3-digit groups). Concatenate all parts.
        # E.g. '42.1.08' from BPS '42.108' → 42108; '262.4.44' → 262444.
        ocr_split = (
            len(parts) == 3
            and all_digit_groups
            and not all_3digit_after_first
            and len(parts[1]) <= 2
            and len(parts[2]) <= 3
        )
        # Fused decimal (≤2007 only): OCR dropped the comma, merging integer and decimal.
        # Pattern x.yyy.nnndd: parts = [x, yyy(3d), nnndd(5d)].
        # E.g. '1.454.70412' from BPS '1.454.704,12' → 1454704.12.
        fused_decimal = (
            period_is_thousands
            and len(parts) == 3
            and all_digit_groups
            and len(parts[1]) == 3
            and len(parts[2]) == 5
        )
        if multi_period or single_period_era or ocr_split:
            s = s.replace(".", "")
        elif fused_decimal:
            integer_part = parts[0] + parts[1] + parts[2][:3]
            decimal_part = parts[2][3:]
            s = integer_part + "." + decimal_part

    try:
        value = float(s)
        vtype = "artifact_cleaned" if artifact_cleaned else "numeric"
        return value, vtype
    except (ValueError, TypeError):
        return np.nan, "non_numeric"


# =========================================================
# NAME FLAG NORMALIZATION
# =========================================================

# OCR variants of '#)' (pre-split aggregate marker):
#   #} → ) OCR'd as }   |  «) → # OCR'd as «
#   x) → BPS 2011-2013 "pecahan dari kabupaten yang berada diatasnya" (confirmed PDF p.20)
#   #) d / #) b / ... → canonical marker + trailing BPS watermark letters
_FLAG_PRE_SPLIT_RE = re.compile(r"^[#«x]\s*[})]\s*[a-zA-Z\s]*$")

# Literal strings that mean a bad row (header label leaked into flag column)
_FLAG_JUNK = {"name_flag"}


def normalize_name_flag(x):
    """
    Normalize name_flag to one of: '#)', '1)', or NaN.

    '#)' — pre-split aggregate (child district, shown alongside its parent)
    '1)' — oil/gas exclusion sub-row (BPS footnote: tidak termasuk minyak & gas bumi)

    'x)' and '#)' OCR variants → '#)' (verified by structural test + PDF p.20).
    All other non-empty flags → '1)' (verified by structural test: every such row is
    a paired oil-exclusion sub-row; garbled forms include *', 2), ^', *^, lj, etc.).
    Header-label bleed ('name_flag') → NaN.
    """
    if pd.isna(x):
        return x
    s = str(x).strip()
    if not s or s in _FLAG_JUNK:
        return np.nan
    if _FLAG_PRE_SPLIT_RE.match(s):
        return "#)"
    return "1)"


# =========================================================
# TABLE HEADER PARSING
# =========================================================


def extract_table_type_and_base_year(header):
    """Derive table_type ('nominal'/'real') and base_year from table_header_raw."""
    if pd.isna(header):
        return np.nan, np.nan

    h = str(header).upper()

    if "BERLAKU" in h or "BERUKU" in h or "CURRENT" in h:
        return "nominal", np.nan

    if "KONSTAN" in h or "CONSTANT" in h:
        m = re.search(r"KONSTAN\s*(?:TAHUN\s*)?(\d{4})", h)
        if not m:
            m = re.search(r"CONSTANT\s*(\d{4})", h)
        base_year = int(m.group(1)) if m else np.nan
        return "real", base_year

    return np.nan, np.nan


def _normalize_header_for_unit(h):
    """Remove inter-word OCR punctuation artifacts before unit extraction.

    Handles e.g. 'Million. Rupiahs' → 'Million Rupiahs' (period between words
    in Sulawesi Utara English headers breaks the 'million rupiah' pattern).
    """
    if pd.isna(h):
        return h
    return re.sub(r'(?<=[a-zA-Z])[\.,]\s*(?=[a-zA-Z])', ' ', str(h))


def extract_unit_raw(header):
    """Extract the unit substring from a verbatim table header."""
    if pd.isna(header):
        return np.nan
    h = str(header).lower()
    for p in UNIT_EXTRACT_PATTERNS:
        m = re.search(p, h)
        if m:
            return str(header)[m.start():m.end()]
    return np.nan


def standardize_unit(unit):
    """Map unit string to numeric multiplier."""
    if pd.isna(unit):
        return np.nan
    u = str(unit).lower().strip()
    for key, multiplier in UNIT_MULTIPLIERS:
        if key in u:
            return multiplier
    return np.nan


# =========================================================
# NAME CLEANING  (identical logic to standardize_raws.py)
# =========================================================


def clean_name(x):
    if pd.isna(x):
        return np.nan
    x = str(x).upper().strip()
    x = re.sub(r"<.*?>", " ", x)
    x = re.sub(r"^\d+\.\s*", "", x)
    x = re.sub(r"\(?\s*EXCL\.?\s*OIL\s*\)?", "", x)
    x = re.sub(r"\(?\s*NON[\-\s]?MIGAS\s*\)?", "", x)
    x = re.sub(r"\(?\s*TANPA\s*MIGAS\s*\)?", "", x)
    x = re.sub(r"\s*(\d+\)|#\))$", "", x)
    x = re.sub(r"\s+\d[\d\.,OB\s]{3,}$", "", x)
    x = re.sub(r"\s+", " ", x)
    x = re.sub(r"[|]+", "", x)
    return x.strip()


def build_region_base(x):
    if pd.isna(x):
        return np.nan
    x = clean_name(x)
    x = re.sub(r"^KAB\.?\s+", "", x)
    x = re.sub(r"^KOTA\s+", "", x)
    x = re.sub(r"^KODYA\s+", "", x)
    return re.sub(r"\s+", " ", x).strip()


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
    """Extract trailing footnote marker from region_name_raw (old-pipeline compat)."""
    if pd.isna(x):
        return np.nan
    m = re.search(r"(\d+\)|#\))$", str(x).strip())
    return m.group(1) if m else np.nan


def detect_numeric_contamination(x):
    if pd.isna(x):
        return False
    return bool(re.search(r"\s+\d[\d\.,OB\s]{3,}$", str(x).upper()))


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


def _admin_from_code(raw):
    """Derive admin_type from BPS regency_code_raw.

    BPS convention: per-province codes 1–69 = kabupaten, 71+ = kota; 70 unused.
    mod 100 handles any 4-digit BPS codes.
    Returns pd.NA (not np.nan) so the result is compatible with pandas 3 StringDtype.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return pd.NA
    try:
        n = int(float(str(raw).strip()))
        r = n % 100
        if r >= 71:
            return "kota"
        if 1 <= r <= 69:
            return "kabupaten"
    except ValueError:
        pass
    return pd.NA


# =========================================================
# MAIN STANDARDIZATION
# =========================================================


def standardize_file(fp):
    print(f"\n{'='*80}\nPROCESSING: {fp.name}\n{'='*80}")

    df = pd.read_csv(fp)
    print(f"  Raw rows    : {len(df):,}")

    # ----------------------------------------------------------
    # 1. Deduplicate on raw_text_hash
    # ----------------------------------------------------------
    n_before = len(df)
    df = df.drop_duplicates(subset=["raw_text_hash"])
    n_dupes = n_before - len(df)
    if n_dupes:
        print(f"  Dedup removed: {n_dupes:,} duplicate rows")

    # ----------------------------------------------------------
    # 2. Rename to canonical column names
    # ----------------------------------------------------------
    df = df.rename(columns={
        "province_name": "province_name_raw",
        "regency_code":  "regency_code_raw",
    })

    # ----------------------------------------------------------
    # 3. Source file tag
    # ----------------------------------------------------------
    df["source_file"] = fp.name

    # ----------------------------------------------------------
    # 4. Value cleaning
    # Publications ≤ 2007 use Indonesian format: period = thousands separator.
    # This only affects period-only values (no comma present); multi-separator
    # values are handled by the last-separator rule regardless of this flag.
    # ----------------------------------------------------------
    m = re.search(r"(\d{4})", fp.name)
    start_year = int(m.group(1)) if m else 9999
    period_is_thousands = (start_year <= 2007)
    print(f"  Period format : {'thousands (≤2007 era)' if period_is_thousands else 'decimal (≥2008 era)'}")
    # BUG C: save raw value strings before cleaning to detect single-digit footnote bleeds
    raw_value_stripped = df["value"].apply(lambda x: str(x).strip() if pd.notna(x) else "")
    results = df["value"].apply(lambda x: clean_value(x, period_is_thousands=period_is_thousands))
    df["value"]      = [r[0] for r in results]
    df["value_type"] = [r[1] for r in results]

    # BUG C: single digits 1–9 are footnote numbers bleeding into data cells, not real values.
    # Must filter on raw string, not on value threshold (threshold would incorrectly drop
    # legitimate ~800K–999K rupiah/capita rows from 1996 for poor districts).
    _SINGLE_DIGITS = {"1", "2", "3", "4", "5", "6", "7", "8", "9"}
    bugc_mask = raw_value_stripped.isin(_SINGLE_DIGITS)
    if bugc_mask.any():
        df.loc[bugc_mask, "value"]      = np.nan
        df.loc[bugc_mask, "value_type"] = "non_numeric"
        print(f"  BUG C single-digit filter: {bugc_mask.sum():,} rows → non_numeric")

    # ----------------------------------------------------------
    # 5. table_type and base_year from table_header_raw
    # ----------------------------------------------------------
    tt = df["table_header_raw"].apply(extract_table_type_and_base_year)
    df["table_type"]    = [r[0] for r in tt]
    df["base_year_raw"] = [r[1] for r in tt]
    # Fallback to English header for rows where Indonesian header is garbled
    # (e.g. "BERLAKU" → "BERUKU" via OCR dropout — all such rows are nominal)
    if "table_header_english" in df.columns:
        missing_idx = df.index[df["table_type"].isna()]
        if len(missing_idx):
            tt_eng = df.loc[missing_idx, "table_header_english"].apply(
                extract_table_type_and_base_year
            )
            df.loc[missing_idx, "table_type"] = [r[0] for r in tt_eng]
            eng_by = pd.Series([r[1] for r in tt_eng], index=missing_idx)
            still_nan_by = missing_idx[df.loc[missing_idx, "base_year_raw"].isna()]
            df.loc[still_nan_by, "base_year_raw"] = eng_by.loc[still_nan_by]
            n_recovered = len(missing_idx) - int(df["table_type"].isna().sum())
            if n_recovered:
                print(f"  table_type fallback: recovered {n_recovered:,} rows via English header")
    # assign to column first so pd.to_numeric operates on a Series, not a list
    df["base_year"]     = pd.to_numeric(df["base_year_raw"], errors="coerce").astype("Int64")

    # ----------------------------------------------------------
    # 6. Normalize name_flag: map all OCR-garbled variants to canonical '#)' / '1)'.
    # ----------------------------------------------------------
    raw_flag_variants = df["name_flag"].dropna().value_counts()
    if len(raw_flag_variants):
        print(f"  name_flag raw variants: {dict(raw_flag_variants)}")
    df["name_flag"] = df["name_flag"].apply(normalize_name_flag)

    # ----------------------------------------------------------
    # 7. Oil excluded — structural detection via name_flag
    #    Any non-empty name_flag that is not '#)' marks an
    #    oil/gas exclusion sub-row. '#)' marks child districts.
    # ----------------------------------------------------------
    flag = df["name_flag"].fillna("").astype(str).str.strip()
    df["oil_excluded"] = flag.ne("") & flag.ne("#)")

    # ----------------------------------------------------------
    # 8. Pre-split aggregate — name_flag == '#)'
    # ----------------------------------------------------------
    df["is_pre_split_aggregate"] = flag.eq("#)")

    # ----------------------------------------------------------
    # 9. footnote_marker (for old-pipeline compatibility;
    #    in the new pipeline this signal is already in name_flag)
    # ----------------------------------------------------------
    df["footnote_marker"] = df["region_name_raw"].apply(extract_footnote_marker)

    # 9b. B1 fix — footnote_marker oil-exclusion catch.
    # Some oil-excluded sub-rows have '1)' embedded in the district name
    # (e.g. "Kab. Indragiri Hulu1)"), captured as footnote_marker="1)" but
    # name_flag stays NaN, so the step-7 detection left oil_excluded=False.
    footnote_oil = (
        df["footnote_marker"].astype(str).str.strip() == "1)"
    ) & df["name_flag"].isna()
    if footnote_oil.any():
        df.loc[footnote_oil, "oil_excluded"] = True
        print(f"  B1 footnote-marker oil fix: {footnote_oil.sum():,} rows → oil_excluded=True")

    # ----------------------------------------------------------
    # 9. Unit extraction and value_standardized
    # ----------------------------------------------------------
    df["unit_raw"] = df["table_header_raw"].apply(extract_unit_raw)

    # BUG D: English fallback when Indonesian extraction returns bare 'rupiah' (OCR fallthrough)
    # or NaN. English headers are always present and always correct. Passive unit_from_english
    # column is written for all rows (informational — no downstream logic depends on it).
    # _normalize_header_for_unit strips inter-word OCR punctuation (e.g. 'Million. Rupiahs')
    # before pattern matching, fixing the Sulawesi Utara 28-row unit error.
    if "table_header_english" in df.columns:
        eng_unit_raw = df["table_header_english"].apply(
            lambda h: extract_unit_raw(_normalize_header_for_unit(h))
        )
        df["unit_from_english"] = eng_unit_raw.apply(
            lambda x: str(x).lower().strip() if pd.notna(x) else np.nan
        )
        ind_unit_lower = df["unit_raw"].apply(
            lambda x: np.nan if pd.isna(x) else str(x).lower().strip()
        )
        needs_fallback = ind_unit_lower.isna() | (ind_unit_lower == "rupiah")
        fallback_mask  = needs_fallback & eng_unit_raw.notna()
        if fallback_mask.any():
            df.loc[fallback_mask, "unit_raw"] = eng_unit_raw.loc[fallback_mask]
            print(f"  BUG D English fallback: {fallback_mask.sum():,} rows unit_raw upgraded via English header")

    df["unit"]            = df["unit_raw"].apply(
        lambda x: str(x).lower().strip() if pd.notna(x) else np.nan
    )
    df["unit_multiplier"] = df["unit"].apply(standardize_unit)
    df["value_standardized"] = df["value"] * df["unit_multiplier"]
    df.loc[df["unit_multiplier"].isna(), "value_standardized"] = df["value"]

    # BUG A: Aceh unit header typo in capita files. BPS wrote "(miliar rupiah)" for Aceh
    # but all values are clearly at ribu scale. Explicit province+file override — do NOT
    # use a unit-threshold approach (would destroy 5,000+ legitimate total-PDRB rows).
    if "capita" in fp.name.lower():
        aceh_mask = df["province_name_raw"].str.upper().str.strip().isin(
            {"ACEH", "NANGGROE ACEH DARUSSALAM", "NANGGROE ACEH DARUSSALAM (NAD)"}
        )
        wrong_unit_mask = df["unit"] == "miliar rupiah"
        override_mask   = aceh_mask & wrong_unit_mask
        if override_mask.any():
            df.loc[override_mask, "unit"]               = "ribu rupiah"
            df.loc[override_mask, "unit_multiplier"]    = 1_000
            df.loc[override_mask, "value_standardized"] = df.loc[override_mask, "value"] * 1_000
            print(f"  BUG A Aceh override: {override_mask.sum():,} rows corrected (miliar → ribu rupiah)")

    # Round value_standardized to 2dp: avoids Excel apostrophe display for floating-point
    # imprecision (e.g. 546771.42 × 1e6 → 546771420000.00006 stored as text with trailing digits).
    df["value_standardized"] = df["value_standardized"].round(2)

    # ----------------------------------------------------------
    # 10. Name cleaning
    # ----------------------------------------------------------
    df["province_name_clean"] = df["province_name_raw"].apply(clean_name)
    df["region_name_clean"]   = df["region_name_raw"].apply(clean_name)
    df["region_name_base"]    = df["region_name_raw"].apply(build_region_base)

    # ----------------------------------------------------------
    # 11. Admin type
    # ----------------------------------------------------------
    df["admin_type"] = df["region_name_raw"].apply(extract_admin_type).astype(object)

    # 11a. kotamadya → kota (harmonize only accepts kabupaten/kota)
    df["admin_type"] = df["admin_type"].replace("kotamadya", "kota")

    # 11b. Derive admin_type from regency_code_raw for rows with no name prefix (Q3).
    code_derived = df["regency_code_raw"].apply(_admin_from_code)
    no_admin = df["admin_type"].isna()
    df.loc[no_admin, "admin_type"] = code_derived.loc[no_admin]
    n_code_derived = (no_admin & code_derived.notna()).sum()
    if n_code_derived:
        print(f"  Admin type from code: {n_code_derived:,} rows")

    # 11c. Forward-fill admin_type for sub-rows with empty regency_code
    # (oil-exclusion and pre-split sub-rows appear immediately after their paired total row)
    empty_code = df["regency_code_raw"].isna() | (df["regency_code_raw"].astype(str).str.strip() == "")
    need_fill = empty_code & df["admin_type"].isna()
    if need_fill.any():
        df.loc[need_fill, "admin_type"] = df["admin_type"].ffill().loc[need_fill]
        print(f"  Admin type inherited: {need_fill.sum():,} empty-code sub-rows")

    # ----------------------------------------------------------
    # 12. Numeric contamination flag
    # ----------------------------------------------------------
    df["has_numeric_name_contamination"] = (
        df["region_name_raw"].apply(detect_numeric_contamination)
    )

    # ----------------------------------------------------------
    # 13. Row type
    # ----------------------------------------------------------
    df["row_type"] = df["region_name_clean"].apply(classify_row_type)
    df["is_data_row"] = df["row_type"] == "data"

    # ----------------------------------------------------------
    # 14. price_type (alias for table_type for compat)
    # ----------------------------------------------------------
    df["price_type"] = df["table_type"].map(
        {"nominal": "nominal", "real": "real"}
    )

    # ----------------------------------------------------------
    # 15. Year coercion
    # ----------------------------------------------------------
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    # ----------------------------------------------------------
    # 15a. D4: Year artifact filter
    # year < 1990 is unambiguously an artifact (data starts 1996).
    # Lower-bound only — no upper bound so future publications are not silently dropped.
    # ----------------------------------------------------------
    artifact_year = df["year"].notna() & (df["year"] < 1990)
    if artifact_year.any():
        df.loc[artifact_year, "is_data_row"] = False
        print(f"  D4 year artifact: {artifact_year.sum():,} rows year<1990 → is_data_row=False")

    # ----------------------------------------------------------
    # 16. Ensure all standard columns present
    # ----------------------------------------------------------
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # ----------------------------------------------------------
    # 17. Reorder: standard columns first, then extras
    # ----------------------------------------------------------
    extras = [c for c in df.columns if c not in STANDARD_COLUMNS]
    df = df[STANDARD_COLUMNS + extras]

    # ----------------------------------------------------------
    # 18. Export
    # ----------------------------------------------------------
    out_fp = OUT_DIR / fp.name
    df.to_csv(out_fp, index=False)

    # ----------------------------------------------------------
    # 19. Summary
    # ----------------------------------------------------------
    data = df[df["is_data_row"]]
    n_prov    = df["province_name_raw"].nunique()
    n_regions = data["region_name_raw"].nunique()
    n_years   = data["year"].nunique()
    yr_range  = (
        f"{int(data['year'].min())}–{int(data['year'].max())}"
        if data["year"].notna().any() else "unknown"
    )
    val_cov   = (
        data["value"].notna().sum() / len(data) * 100
        if len(data) > 0 else 0
    )
    tt_counts = df["table_type"].value_counts().to_dict()
    vt_counts = df["value_type"].value_counts().to_dict()
    unit_vals = df["unit"].dropna().unique().tolist()
    base_yrs  = sorted(df["base_year"].dropna().unique().tolist())
    missing_cols = [c for c in STANDARD_COLUMNS if c not in df.columns]
    unexpected_rt = (
        set(df["row_type"].dropna().unique())
        - {"data", "total_regmun", "province", "table_header", "empty"}
    )

    print(f"\n  OUTPUT SUMMARY")
    print(f"  Rows (post-dedup)  : {len(df):,}")
    print(f"  Provinces          : {n_prov}")
    print(f"  Regions (data rows): {n_regions}")
    print(f"  Years              : {yr_range} ({n_years} distinct)")
    print(f"  Table types        : {tt_counts}")
    print(f"  Base years         : {base_yrs}")
    print(f"  Units              : {unit_vals}")
    print(f"  Value coverage     : {val_cov:.1f}% of data rows")
    print(f"  Value types        : {vt_counts}")
    print(f"  Oil-excluded rows  : {int(df['oil_excluded'].sum()):,}")
    print(f"  Pre-split agg rows : {int(df['is_pre_split_aggregate'].sum()):,}")
    print(f"  Numeric OCR flags  : {int(df['has_numeric_name_contamination'].sum()):,}")
    if missing_cols:
        print(f"  MISSING COLS       : {missing_cols}")
    if unexpected_rt:
        print(f"  UNEXPECTED ROW TYPES: {unexpected_rt}")

    # ----------------------------------------------------------
    # 20. Audit exports
    # ----------------------------------------------------------
    # Artifact-cleaned and non-numeric values
    bad_values = df[df["value_type"].isin(["artifact_cleaned", "non_numeric"])]
    if len(bad_values):
        audit_fp = AUDIT_DIR / f"{fp.stem}_value_issues.csv"
        bad_values[
            ["source_file", "province_name_raw", "region_name_raw",
             "year", "value", "value_type", "table_header_raw", "page_number"]
        ].to_csv(audit_fp, index=False)
        print(f"  Value issues audit : {len(bad_values):,} rows → {audit_fp.name}")
        for vt, grp in bad_values.groupby("value_type"):
            print(f"    {vt}: {len(grp):,}")

    # Suspicious rows (non-data or numeric-name contamination)
    suspicious = df[
        (df["row_type"] != "data") | df["has_numeric_name_contamination"]
    ]
    audit_fp2 = AUDIT_DIR / f"{fp.stem}_suspicious_rows.csv"
    suspicious.to_csv(audit_fp2, index=False)
    print(f"  Suspicious rows    : {len(suspicious):,} → {audit_fp2.name}")
    for rt, grp in suspicious.groupby("row_type"):
        print(f"    {rt}: {len(grp):,}")

    print(f"\n  Saved: {out_fp}")


# =========================================================
# RUN
# =========================================================


def main():
    csv_files = sorted(IN_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {IN_DIR}")

    print("=" * 80)
    print(f"standardize_pipeline.py  v{VERSION}")
    print(f"Input : {IN_DIR}  ({len(csv_files)} files)")
    print(f"Output: {OUT_DIR}")
    print("=" * 80)

    errors = []
    for fp in csv_files:
        try:
            standardize_file(fp)
        except Exception as e:
            print(f"\n{'!'*80}\nERROR: {fp.name}\n{e}\n{'!'*80}")
            errors.append(fp.name)

    print(f"\n{'='*80}")
    print(f"DONE — {len(csv_files) - len(errors)}/{len(csv_files)} files processed")
    if errors:
        print(f"FAILED: {errors}")
    print("=" * 80)


if __name__ == "__main__":
    main()
