#!/usr/bin/env python3
"""
Stage 1.5 — apply_corrections.py

Idempotent, content-keyed corrections to the 21 parsed CSVs.
Must be run after parse_pdfs_text.py / parse_pdfs_scan.py and before standardize_pipeline.py.

3-state logic per correction:
  applied  — bad value found; replaced with good value
  skipped  — good value already present; no change
  failed   — neither bad nor good found; unexpected state

Usage:
    python scripts/apply_corrections.py [--dry-run]

Outputs (skipped under --dry-run):
    Reads  originals from pipeline_out/full_runs/csvs/ (left untouched)
    Writes corrected copies to pipeline_out/full_runs/corrected_csvs/
    Writes sidecar: corrections/corrections_applied.csv
"""

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CSVS = Path("pipeline_out/full_runs/csvs")
CORRECTED = Path("pipeline_out/full_runs/corrected_csvs")
SIDECAR = Path("corrections/corrections_applied.csv")


def _source_path(fname):
    """Read from the corrected copy if it already exists (so a file appearing
    in more than one correction pass chains correctly), else the original."""
    corrected = CORRECTED / fname
    return corrected if corrected.exists() else CSVS / fname

_ANY = object()  # sentinel: do not filter rows by name_flag


# ─── core engine ──────────────────────────────────────────────────────────────


def _matches(cell, target):
    """True if cell equals target. target=None means NaN/missing."""
    if target is None:
        return pd.isna(cell)
    return not pd.isna(cell) and str(cell) == str(target)


def _hashes_for(df, idxs):
    """Return raw_text_hash values for the given row indices (skip if column absent)."""
    if "raw_text_hash" not in df.columns:
        return []
    return [df.at[i, "raw_text_hash"] for i in idxs]


def fix_cell(df, *, fix_id, province, district, year, bad, good, name_flag=_ANY):
    """
    Apply one correction with 3-state logic.

    Returns (state: str, message: str, hashes: list).
    Modifies df["value"] in-place when state == "applied".
    hashes = raw_text_hash values of the rows actually touched (applied) or matched at
    the good value (skipped); [] on failed.

    name_flag=_ANY  → match all rows regardless of name_flag
    name_flag=None  → match only rows where name_flag IS NaN
    name_flag="*'"  → match rows where name_flag == "*'"
    """
    mask = (
        (df["province_name"].str.upper() == province.upper())
        & (df["region_name_raw"].str.upper() == district.upper())
        & (df["year"] == str(year))
    )
    if name_flag is not _ANY:
        if name_flag is None or (isinstance(name_flag, float) and np.isnan(name_flag)):
            mask &= df["name_flag"].isna()
        else:
            mask &= df["name_flag"] == name_flag

    rows = df[mask]
    if rows.empty:
        return "failed", f"no rows found for ({province!r}, {district!r}, {year})", []

    n_bad  = sum(_matches(v, bad)  for v in rows["value"])
    n_good = sum(_matches(v, good) for v in rows["value"])

    if n_bad > 0:
        write_val = np.nan if good is None else good
        touched = []
        for idx in rows.index:
            if _matches(df.at[idx, "value"], bad):
                df.at[idx, "value"] = write_val
                touched.append(idx)
        return "applied", f"{n_bad} cell(s): {bad!r} → {write_val!r}", _hashes_for(df, touched)

    if n_good > 0:
        good_idxs = [i for i in rows.index if _matches(df.at[i, "value"], good)]
        return "skipped", f"already correct ({n_good} row(s) at good value)", _hashes_for(df, good_idxs)

    sample = rows["value"].iloc[0]
    n_other = len(rows)
    return "failed", (
        f"expected bad={bad!r} or good={good!r}; "
        f"found {sample!r} ({n_other} row(s) matched)"
    ), []


def fix_flag(df, *, fix_id, province, district, year, value_key, bad_flag, good_flag):
    """
    Fix name_flag for a specific row identified by (province, district, year, value_key).

    Used when the parser sets name_flag incorrectly, which then mis-drives oil_excluded
    at standardize time. value_key discriminates between duplicate rows (e.g. oil-inclusive
    vs oil-exclusive when both share the same region_name_raw).

    Returns (state: str, message: str, hashes: list).
    Modifies df["name_flag"] in-place when state == "applied".
    hashes = raw_text_hash values of the rows actually touched (applied) or matched at
    the good flag (skipped); [] on failed.

    bad_flag=None  → match rows where name_flag IS NaN
    good_flag=None → correction sets name_flag to NaN
    """
    mask = (
        (df["province_name"].str.upper() == province.upper())
        & (df["region_name_raw"].str.upper() == district.upper())
        & (df["year"] == str(year))
        & df["value"].apply(lambda v: _matches(v, value_key))
    )
    rows = df[mask]
    if rows.empty:
        return "failed", f"no rows found for ({province!r}, {district!r}, {year}, value={value_key!r})", []

    n_bad  = sum(_matches(v, bad_flag)  for v in rows["name_flag"])
    n_good = sum(_matches(v, good_flag) for v in rows["name_flag"])

    if n_bad > 0:
        write_flag = np.nan if good_flag is None else good_flag
        touched = []
        for idx in rows.index:
            if _matches(df.at[idx, "name_flag"], bad_flag):
                df.at[idx, "name_flag"] = write_flag
                touched.append(idx)
        return "applied", f"{n_bad} flag(s): {bad_flag!r} → {write_flag!r} (value={value_key!r})", _hashes_for(df, touched)

    if n_good > 0:
        good_idxs = [i for i in rows.index if _matches(df.at[i, "name_flag"], good_flag)]
        return "skipped", f"flag already correct ({n_good} row(s))", _hashes_for(df, good_idxs)

    sample = rows["name_flag"].iloc[0]
    return "failed", (
        f"expected bad_flag={bad_flag!r} or good_flag={good_flag!r}; "
        f"found {sample!r} ({len(rows)} row(s) matched at value={value_key!r})"
    ), []


# ─── corrections table ────────────────────────────────────────────────────────

# Each entry is a dict with keys:
#   fix_id, province, district, year, bad, good
#   name_flag (optional; default _ANY)
# bad=None  → cell is NaN in a fresh parse
# good=None → correction nulls the cell

CORRECTIONS_BY_FILE = {

    "PDRB_1996-1999.csv": [
        # FAKFAK_err: Fak-Fak 1996-1999 nominal and real/1993 — BPS Irian Jaya table error.
        # PDF confirms these ARE the printed values; 1999 nominal 11.4T → 2000 nominal 0.45T
        # (DAPOER-confirmed) is a ×25 drop — BPS source error, not parser error.
        # Treat Fakfak pre-2000 as unusable (data guide note).
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1996, "bad": "4.348.830,21",  "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1997, "bad": "4.631.154,51",  "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1998, "bad": "12.545.086,18", "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1999, "bad": "11.413.494,11", "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1996, "bad": "3.666.665,57",  "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1997, "bad": "3.812.546,05",  "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1998, "bad": "5.157.192,12",  "good": None},
        {"fix_id": "FAKFAK_err", "province": "IRIAN JAYA", "district": "Fak-Fak", "year": 1999, "bad": "5.086.803,23",  "good": None},
        # W3: Banjarmasin 1997 real — leading 'L' OCR artifact
        {"fix_id": "W3",         "province": "KALIMANTAN SELATAN", "district": "Banjarmasin",   "year": 1997, "bad": "L421.607,59",    "good": "1.421.607,59"},
        # W3d: Sumenep 1996 real — missing thousands-separator period
        {"fix_id": "W3d",        "province": "JAWA TIMUR",         "district": "Sumenep",        "year": 1996, "bad": "8521541,10",     "good": "852.541,10"},
        # W3e: Mamuju 1999 real — 232% impossible spike, BPS source error
        {"fix_id": "W3e",        "province": "SULAWESI SELATAN",   "district": "Mamuju",         "year": 1999, "bad": "649.558,43",     "good": None},
        # P5a: Barru 1998 nominal — spike-and-revert BPS source error
        {"fix_id": "P5a",        "province": "SULAWESI SELATAN",   "district": "Barru",          "year": 1998, "bad": "1.641.907,55",   "good": None},
        # OCR garbles — semicolons in place of decimal commas
        {"fix_id": "OCR_garble", "province": "LAMPUNG",            "district": "Tulang Bawang",  "year": 1998, "bad": "615.170;00",     "good": "615.170,00"},
        {"fix_id": "OCR_garble", "province": "SULAWESI TENGAH",    "district": "Morowali",       "year": 1998, "bad": "622.216;40",     "good": "622.216,40"},
        # P_recover: Mandailing Natal 1997 nominal — OCR left both duplicate rows blank; value from BPS PDF
        {"fix_id": "P_recover",  "province": "SUMATERA UTARA",     "district": "Mandailing Natal", "year": 1997, "bad": None,           "good": "675.778,17"},
        # P_MN96_dup: Mandailing Natal 1996 nominal — the 1997 value leaked into the 1996
        # column (both duplicate copies of the row). PDF (p.3, Table 2) shows 1996 blank for
        # this district (its series starts 1997); the constant-1993 table (p.31) parsed 1996
        # correctly as blank, confirming the nominal-table 1996 cell is spurious. Null it.
        {"fix_id": "P_MN96_dup", "province": "SUMATERA UTARA",     "district": "Mandailing Natal", "year": 1996, "bad": "675.778,17",   "good": None},
        # P9_recover: Bojonegoro 1999, nominal and real/1993 — BPS printed the 1998 value again
        # in the 1999 column in both tables (PDRB_1996-1999.pdf p.14 and p.42; neighbouring
        # districts grow normally that year). Recovered from PDRB_1998-2001.pdf, which prints
        # 1999 in its own column: p.36 (current price) and p.67/Table 45 (constant 1993).
        {"fix_id": "P9_recover", "province": "JAWA TIMUR",         "district": "Bojonegoro",       "year": 1999, "bad": "1.927.019,37", "good": "2.126.795,00"},
        {"fix_id": "P9_recover", "province": "JAWA TIMUR",         "district": "Bojonegoro",       "year": 1999, "bad": "978.764,27",   "good": "979.059,21"},
    ],

    "PDRB-capita_1996-1999.csv": [
        # W3c: Sambas 1996-1999 — BPS used ÷10 population denominator
        # Two duplicate rows per year (resume re-run artifact); both are corrected.
        {"fix_id": "W3c", "province": "KALIMANTAN BARAT",  "district": "Sambas", "year": 1996, "bad": "199.138,54",    "good": "1.991.385,40"},
        {"fix_id": "W3c", "province": "KALIMANTAN BARAT",  "district": "Sambas", "year": 1997, "bad": "225.282,82",    "good": "2.252.828,20"},
        {"fix_id": "W3c", "province": "KALIMANTAN BARAT",  "district": "Sambas", "year": 1998, "bad": "391.243,23",    "good": "3.912.432,30"},
        {"fix_id": "W3c", "province": "KALIMANTAN BARAT",  "district": "Sambas", "year": 1999, "bad": "397.738,19",    "good": "3.977.381,90"},
        # W3f: Kapuas 1999 — spurious leading '1' from scan shadow
        # Two duplicate rows; both are corrected.
        {"fix_id": "W3f", "province": "KALIMANTAN TENGAH", "district": "Kapuas", "year": 1999, "bad": "13.873.942,59", "good": "3.873.942,59"},
        # P5a: Barru 1998 per-capita — mirrors nominal spike
        {"fix_id": "P5a", "province": "SULAWESI SELATAN",  "district": "Barru",  "year": 1998, "bad": "10.583.677,33", "good": None},
        # OCR_col_shift: Luwu Utara 1997-1999 — parser aligned columns one position left
        # PDF shows only 1998 (4,899,781.05) and 1999 (6,673,440.67); 1997 must be blank
        {"fix_id": "OCR_col_shift", "province": "SULAWESI SELATAN", "district": "Luwu Utara", "year": 1997, "bad": "4.899.781,05", "good": None},
        {"fix_id": "OCR_col_shift", "province": "SULAWESI SELATAN", "district": "Luwu Utara", "year": 1998, "bad": "6.673.440,67", "good": "4.899.781,05"},
        {"fix_id": "OCR_col_shift", "province": "SULAWESI SELATAN", "district": "Luwu Utara", "year": 1999, "bad": "4",           "good": "6.673.440,67"},
    ],

    "PDRB_2000-2001.csv": [
        # W3a: Kampar real/1993 2000-2003 — BPS source error (~160× too low)
        # Separate entries for NaN-flagged (total) and "*'"-flagged (oil-excluded) rows.
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2000, "bad": "11.120,92",  "good": None, "name_flag": None},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2001, "bad": "11.751,14",  "good": None, "name_flag": None},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2002, "bad": "12 462,79",  "good": None, "name_flag": None},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2003, "bad": "13 197,80",  "good": None, "name_flag": None},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2000, "bad": "1 212,37",   "good": None, "name_flag": "*'"},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2001, "bad": "1.304,22",   "good": None, "name_flag": "*'"},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2002, "bad": "1 369,94",   "good": None, "name_flag": "*'"},
        {"fix_id": "W3a", "province": "RIAU", "district": "Kampar", "year": 2003, "bad": "1 435,67",   "good": None, "name_flag": "*'"},
        # W3b: Musi Rawas 2001 nominal oil-excl — OCR multi-character garble
        {"fix_id": "W3b", "province": "SUMATERA SELATAN", "district": "MUSI Rawas", "year": 2001,
         "bad": "1 910 16o3,0.0", "good": "1.910.163,00", "name_flag": "*'"},
        # W3g: Bengkulu Selatan 2003 real/1993 — this table (p.40, Table 38) prints values in
        # comma-thousands/period-decimal form ("412,451.00"); the 2003 cell lost its decimal
        # point to a space ("220,997 00"), which the standardizer read as 220.997 (a 1000x
        # understatement). Confirmed against the PDF; the 46% YoY drop itself is genuine
        # (Kaur and Seluma split off as separate rows that year).
        {"fix_id": "W3g", "province": "BENGKULU", "district": "Bengkulu Selatan", "year": 2003, "bad": "220,997 00", "good": "220,997.00"},
        # OCR garbles — spurious characters in numeric strings
        {"fix_id": "OCR_garble", "province": "NUSA TENGGARA TIMUR", "district": "Ende",              "year": 2000, "bad": "192.3w69,.54",   "good": "192.369,54"},
        {"fix_id": "OCR_garble", "province": "KALIMANTAN SELATAN",  "district": "Tabalong",          "year": 2000, "bad": "1.439.0w10,.77", "good": "1.439.010,77"},
        {"fix_id": "OCR_garble", "province": "KALIMANTAN SELATAN",  "district": "Tabalong",          "year": 2000, "bad": "440.774.,68",    "good": "440.774,68"},
        {"fix_id": "OCR_garble", "province": "KALIMANTAN SELATAN",  "district": "Tabalong",          "year": 2001, "bad": "475 743,30",     "good": "475.743,30"},
        {"fix_id": "OCR_garble", "province": "SUMATERA UTARA",      "district": "Langkat",           "year": 2000, "bad": "4/.557.346,55",  "good": "4.557.346,55"},
        {"fix_id": "OCR_garble", "province": "SUMATERA UTARA",      "district": "Asahan",            "year": 2001, "bad": "3 269.467,29",     "good": "3.269.467,29"},
        {"fix_id": "OCR_garble", "province": "SULAWESI SELATAN",    "district": "Sidenreng Rappang", "year": 2001, "bad": "307.04.1/40",      "good": "307.041,40"},
        # Asahan 2001 nominal: 'o' for '0' + spurious period in decimal ('9.7' → '97')
        {"fix_id": "OCR_garble", "province": "SUMATERA UTARA",      "district": "Asahan",            "year": 2001, "bad": "9.292.08o9,9.7",   "good": "9.292.089,97"},
        # Kudus 2000 real/1993: 'w' + space artifacts split '615'; leading '.' in decimal
        {"fix_id": "OCR_garble", "province": "JAWA TENGAH",         "district": "Kudus",             "year": 2000, "bad": "3.087.6 w 15,.87", "good": "3.087.615,87"},
        # Karawang 2000 real/1993: space-for-period + leading '.' in decimal (has clean dup row)
        {"fix_id": "OCR_garble", "province": "JAWA BARAT",          "district": "Karawang",          "year": 2000, "bad": "2 793.987,.74",    "good": "2.793.987,74"},
        # Tuban 2000 real/1993: leading '.' in decimal (has a second row with 'b' garble)
        {"fix_id": "OCR_garble", "province": "JAWA TIMUR",          "district": "Tuban",             "year": 2000, "bad": "1.148.987,.86",    "good": "1.148.987,86"},
    ],

    "PDRB-capita_2000-2001.csv": [
        # OCR garbles — leading '.' in decimal or slash-for-comma (most have clean dup row)
        {"fix_id": "OCR_garble", "province": "JAMBI",   "district": "Jambi",         "year": 2000, "bad": "4.699.010,.24",  "good": "4.699.010,24"},
        {"fix_id": "OCR_garble", "province": "LAMPUNG", "district": "Lampung Timur", "year": 2003, "bad": "4.745.226/12",   "good": "4.745.226,12"},
        {"fix_id": "OCR_garble", "province": "JAWA TIMUR", "district": "Tuban",      "year": 2000, "bad": "2.822.110,6.9",  "good": "2.822.110,69"},
        # W2c + W2c_recover (net): SumBar per-capita — wrong ~62K population denominator
        # applied to all 15 SumBar districts 2000-2001.
        # bad  = original garbled OCR string from the mis-denominated BPS publication
        # good = correct per-capita from BPS online (Query Builder, Seri 2000 HB)
        # Kab. Solok and Kota Solok share region_name_raw="Solok"; their distinct bad values
        # serve as discriminators.
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Kepulauan Mentawai",   "year": 2000, "bad": "5 592.298,14",     "good": "5.400.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Pesisir Selatan",       "year": 2000, "bad": "21.504.131,73",    "good": "3.380.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Solok",                 "year": 2000, "bad": "26.794.436,51",    "good": "3.890.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Sawahlunto/Sijunj'ung", "year": 2000, "bad": "23.860.468,00",    "good": "5.380.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Tanah Datar",           "year": 2000, "bad": "24 914.670,18",    "good": "4.500.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang Panaman",         "year": 2000, "bad": "31.289 780,78",    "good": "3.960.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Agam",                  "year": 2000, "bad": "29.483.413,47",    "good": "4.360.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Lima Puluh Koto",       "year": 2000, "bad": "27.394.267,21",    "good": "5.490.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Pasaman",               "year": 2000, "bad": "25.302.310,62",    "good": "3.610.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang",                "year": 2000, "bad": "116.250.990,08",   "good": "10.430.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Solok",                 "year": 2000, "bad": "5.111.505,49.",    "good": "6.750.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Sawahlunto",            "year": 2000, "bad": "7.889w.330,51",    "good": "8.250.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang Panjang",        "year": 2000, "bad": "4.002.100,76",     "good": "6.190.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Bukit Tinggi",          "year": 2000, "bad": "s9.698.035,37",    "good": "6.760.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Payakumbuh",            "year": 2000, "bad": "8.283.216,91",     "good": "5.360.000,00"},

        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Kepulauan Mentawai",   "year": 2001, "bad": "6.375.113,36",     "good": "6.370.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Pesisir Selatan",       "year": 2001, "bad": "23.538.744,94",    "good": "3.630.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Solok",                 "year": 2001, "bad": "29.345.793,04",    "good": "4.410.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Sawahlunto/Sijunj'ung", "year": 2001, "bad": "26.113.778,14",    "good": "5.540.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Tanah Datar",           "year": 2001, "bad": "27.274.484,86",    "good": "5.320.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang Panaman",         "year": 2001, "bad": "34.493.602,59",    "good": "4.610.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Agam",                  "year": 2001, "bad": "32.819.790,61",    "good": "4.810.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Lima Puluh Koto",       "year": 2001, "bad": "30.133.458,i46",   "good": "5.980.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Pasaman",               "year": 2001, "bad": "27.73g0.845,18",   "good": "3.720.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang",                "year": 2001, "bad": "p130.256.731,01",  "good": "11.060.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Solok",                 "year": 2001, "bad": "5.607.412,15",     "good": "7.300.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Sawahlunto",            "year": 2001, "bad": "8.083.023,00",     "good": "8.990.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Padang Panjang",        "year": 2001, "bad": "4.413.472,06",     "good": "6.780.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Bukit Tinggi",          "year": 2001, "bad": "10.761.097,81",    "good": "7.300.000,00"},
        {"fix_id": "W2c", "province": "SUMATERA BARAT", "district": "Payakumbuh",            "year": 2001, "bad": "9.117.269,47",     "good": "5.670.000,00"},
    ],

    "PDRB_2002-2004.csv": [
        # Balikpapan 2003 nominal oil-excluded: 'w' artifact + errant comma-dot sequence
        # English-format file (comma=thousands); correct value consistent with 2002/2004 neighbors
        {"fix_id": "OCR_garble", "province": "KALIMANTAN TIMUR", "district": "Balikpapan", "year": 2003, "bad": "7,6w33.,201.87", "good": "7,633,201.87"},
        # B2 + B2-revert cancel for Kab. Bogor (net = no change); omitted.
        # P7_real: Kota Bogor REAL/2000 2002-2004 — parser garbled entire real/2000 row.
        # bad values uniquely identify Kota Bogor (Kab. Bogor ~10× larger).
        # Publication columns: 2002/2003/2004/2005*/2006** — PDF values in order:
        # 2,986,837.37 / 3,168,185.54 / 3,361,438.93 / 3,567,231.91 / 3,782,273.71
        # 2005* and 2006** match first two columns of PDRB_2005-2007 (correct in panel).
        {"fix_id": "P7_real", "table_type": "real", "province": "JAWA BARAT", "district": "Bogor", "year": 2002, "bad": "2,449,771.98", "good": "2,986,837.37"},
        {"fix_id": "P7_real", "table_type": "real", "province": "JAWA BARAT", "district": "Bogor", "year": 2003, "bad": "2,567,582.78", "good": "3,168,185.54"},
        {"fix_id": "P7_real", "table_type": "real", "province": "JAWA BARAT", "district": "Bogor", "year": 2004, "bad": "1,340,714.15", "good": "3,361,438.93"},
        # P7_recover: Kota Bogor NOMINAL 2002-2004 — OCR parse failure left these null.
        # bad=None identifies null rows; good value uniquely identifies Kota Bogor
        # among the 4 Bogor rows per year (Kab vs Kota, nominal vs real).
        # table_type="nominal": real rows for same district-year are NOT corrected.
        {"fix_id": "P7_recover", "table_type": "nominal", "province": "JAWA BARAT", "district": "Bogor", "year": 2002, "bad": None, "good": "3,459,398.26"},
        {"fix_id": "P7_recover", "table_type": "nominal", "province": "JAWA BARAT", "district": "Bogor", "year": 2003, "bad": None, "good": "3,915,569.13"},
        {"fix_id": "P7_recover", "table_type": "nominal", "province": "JAWA BARAT", "district": "Bogor", "year": 2004, "bad": None, "good": "4,515,746.82"},
        # P7_garble: Kota Bogor NOMINAL 2005-2006 — garbled to physically impossible values
        {"fix_id": "P7_garble", "table_type": "nominal", "province": "JAWA BARAT", "district": "Bogor", "year": 2005, "bad": "47,596,588.89", "good": "5,391,918.89"},
        {"fix_id": "P7_garble", "table_type": "nominal", "province": "JAWA BARAT", "district": "Bogor", "year": 2006, "bad": "65,077,543.54", "good": "6,357,742.09"},
    ],

    "PDRB-capita_2005-2007.csv": [
        # P6: Kab. Sumba Barat 2005-2006 — garbled OCR values (9,623 and 1,003 implausible)
        {"fix_id": "P6",         "province": "NUSA TENGGARA TIMUR", "district": "Kab. Sumba Barat", "year": 2005, "bad": "9,623", "good": None},
        {"fix_id": "P6",         "province": "NUSA TENGGARA TIMUR", "district": "Kab. Sumba Barat", "year": 2006, "bad": "1,003", "good": None},
        # P6_recover: Kab. Sumba Barat 2007 — previous P6 null was wrong; PDF confirms 4,640 ribu rupiah
        {"fix_id": "P6_recover", "province": "NUSA TENGGARA TIMUR", "district": "Kab. Sumba Barat", "year": 2007, "bad": None,    "good": "4,640"},
    ],

    "PDRB-capita_2017-2019.csv": [
        # W2 + W2b net: Lampung per-capita BPS publication error — wrong population denominators
        # for 5 districts in the 2017-2021 publication.
        # 2017-2019: bad = garbled print value → good = correct BPS online value
        # 2020-2021 (Bandar Lampung, Metro only): bad → null (no recovery available;
        #   higher-priority publications supply final panel values for these years)
        # Kab. Mesuji
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Mesuji",            "year": 2017, "bad": "5 4.804",  "good": "45.089"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Mesuji",            "year": 2018, "bad": "5 8.667",  "good": "48.659"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Mesuji",            "year": 2019, "bad": "6 2.056",  "good": "51.934"},
        # Kab. Tulang Bawang Barat
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Tulang Bawang Barat", "year": 2017, "bad": "4 9.746", "good": "36.611"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Tulang Bawang Barat", "year": 2018, "bad": "5 3.497", "good": "39.287"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Tulang Bawang Barat", "year": 2019, "bad": "5 7.104", "good": "41.860"},
        # Kab. Pesisir Barat
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Pesisir Barat",     "year": 2017, "bad": "14.666",   "good": "25.881"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Pesisir Barat",     "year": 2018, "bad": "15.790",   "good": "27.854"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kab. Pesisir Barat",     "year": 2019, "bad": "17.144",   "good": "30.246"},
        # Kota Bandar Lampung
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Bandar Lampung",    "year": 2017, "bad": "3 28.350", "good": "49.298"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Bandar Lampung",    "year": 2018, "bad": "3 55.198", "good": "52.824"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Bandar Lampung",    "year": 2019, "bad": "3 82.028", "good": "56.218"},
        {"fix_id": "W2",  "province": "LAMPUNG", "district": "Kota Bandar Lampung",    "year": 2020, "bad": "3 62.458", "good": None},
        {"fix_id": "W2",  "province": "LAMPUNG", "district": "Kota Bandar Lampung",    "year": 2021, "bad": "3 75.837", "good": None},
        # Kota Metro
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Metro",             "year": 2017, "bad": "5 .396",   "good": "33.635"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Metro",             "year": 2018, "bad": "5 .700",   "good": "35.671"},
        {"fix_id": "W2b", "province": "LAMPUNG", "district": "Kota Metro",             "year": 2019, "bad": "6 .002",   "good": "37.683"},
        {"fix_id": "W2",  "province": "LAMPUNG", "district": "Kota Metro",             "year": 2020, "bad": "5 .422",   "good": None},
        {"fix_id": "W2",  "province": "LAMPUNG", "district": "Kota Metro",             "year": 2021, "bad": "5 .550",   "good": None},
    ],

    "PDRB-capita_2011-2013.csv": [
        # KALTARA_shift: the parser merged the Kalimantan Utara per-capita table
        # (PDF Tabel 160, printed p.170) into the Kalimantan Timur table (Tabel 159,
        # printed p.169) and shifted the Kaltara rows one year-column LEFT:
        # 2013 values landed in 2012, 2014 in 2013, 2015 in 2014, junk ("4") in 2015.
        # The Kaltim-section rows (regency codes 06-10, 73) also carry junk "3" in 2015
        # where the PDF prints a dash. Verified against the raw PDF pages 23-24
        # (2026-08-15). Implied-population cross-check with the total file confirms
        # the shift (e.g. Tarakan pop 211k->219k->227k->236k only under the shifted
        # reading). Kaltara-section rows are identified by their bad values —
        # both sections share province_name=KALIMANTAN TIMUR and region_name_raw.
        # -- Kab. Malinau (Kaltara section, PDF: 2013=85.391, 2014=87.710, 2015=88.298)
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Malinau",     "year": 2012, "bad": "8 5.391",  "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Malinau",     "year": 2013, "bad": "8 7.710",  "good": "85.391"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Malinau",     "year": 2014, "bad": "8 8.298",  "good": "87.710"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Malinau",     "year": 2015, "bad": "4",        "good": "88.298"},
        # -- Kab. Bulungan (PDF: 2013=97.809, 2014=100.916, 2015=99.081)
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Bulungan",    "year": 2012, "bad": "9 7.809",  "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Bulungan",    "year": 2013, "bad": "1 00.916", "good": "97.809"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Bulungan",    "year": 2014, "bad": "9 9.081",  "good": "100.916"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Bulungan",    "year": 2015, "bad": "4",        "good": "99.081"},
        # -- Kab. Tana Tidung (PDF: 2013=185.363, 2014=186.239, 2015=179.665)
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Tana Tidung", "year": 2012, "bad": "1 85.363", "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Tana Tidung", "year": 2013, "bad": "1 86.239", "good": "185.363"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Tana Tidung", "year": 2014, "bad": "1 79.665", "good": "186.239"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Tana Tidung", "year": 2015, "bad": "4",        "good": "179.665"},
        # -- Kab. Nunukan (PDF: 2013=82.901, 2014=88.927, 2015=85.015)
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Nunukan",     "year": 2012, "bad": "8 2.901",  "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Nunukan",     "year": 2013, "bad": "8 8.927",  "good": "82.901"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Nunukan",     "year": 2014, "bad": "8 5.015",  "good": "88.927"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Nunukan",     "year": 2015, "bad": "4",        "good": "85.015"},
        # -- Kota Tarakan (PDF: 2013=76.959, 2014=86.177, 2015=90.422)
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kota Tarakan",     "year": 2012, "bad": "7 6.959",  "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kota Tarakan",     "year": 2013, "bad": "8 6.177",  "good": "76.959"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kota Tarakan",     "year": 2014, "bad": "9 0.422",  "good": "86.177"},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kota Tarakan",     "year": 2015, "bad": "4",        "good": "90.422"},
        # -- Kaltim-section rows: junk "3" in the 2015 column where the PDF prints "-"
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Malinau",     "year": 2015, "bad": "3",        "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Bulungan",    "year": 2015, "bad": "3",        "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Tana Tidung", "year": 2015, "bad": "3",        "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kab. Nunukan",     "year": 2015, "bad": "3",        "good": None},
        {"fix_id": "KALTARA_shift", "province": "KALIMANTAN TIMUR", "district": "Kota Tarakan",     "year": 2015, "bad": "3",        "good": None},
    ],
}

# Flag corrections: clear mis-set name_flag for specific rows.
# Parser set name_flag='1)' on both the oil-inclusive and oil-exclusive rows for
# Riau's Indragiri Hulu and Pelalawan in the 2008-2010 capita publication (all 5
# years, 2008-2012). The higher value in each pair is oil-inclusive; clearing its
# flag lets standardize assign oil_excluded=False. Identified by consistent
# tanpa/dengan ratio ~0.96-0.97 across all years, anchored to the 2010 reference
# where the two rows are distinguishable by name_flag (NaN vs "1)").
FLAG_CORRECTIONS_BY_FILE = {
    "PDRB-capita_2008-2010.csv": [
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Indragiri Hulu", "year": 2008,
         "value_key": "35.609", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Pelalawan",       "year": 2008,
         "value_key": "47.229", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Indragiri Hulu", "year": 2009,
         "value_key": "42.157", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Pelalawan",       "year": 2009,
         "value_key": "52.025", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Indragiri Hulu", "year": 2010,
         "value_key": "48.394", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Pelalawan",       "year": 2010,
         "value_key": "54.230", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Indragiri Hulu", "year": 2011,
         "value_key": "58.884", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Pelalawan",       "year": 2011,
         "value_key": "61.618", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Indragiri Hulu", "year": 2012,
         "value_key": "66.376", "bad_flag": "1)", "good_flag": None},
        {"fix_id": "BUG_E", "province": "RIAU", "district": "Kab. Pelalawan",       "year": 2012,
         "value_key": "65.229", "bad_flag": "1)", "good_flag": None},
    ],
}


# ─── file-level orchestration ─────────────────────────────────────────────────


def _log_fix(applied_log, *, fname, fix_id, region_name, year, table_type, hashes):
    """
    Fan out one sidecar row per raw_text_hash the fix touched.

    If a fix touched no hashes (e.g. raw_text_hash column absent), still emit one row
    with an empty hash so the sidecar stays backward-compatible.
    """
    rows_hashes = hashes if hashes else [""]
    for h in rows_hashes:
        applied_log.append({
            "source_file": fname,
            "fix_id": fix_id,
            "region_name": region_name,
            "year": year,
            "table_type": table_type,
            "raw_text_hash": h,
        })


def apply_file(fname, corrections, dry_run, applied_log):
    path = _source_path(fname)
    if not path.exists():
        print(f"\n  [MISSING ] {fname}", file=sys.stderr)
        return 0, 0, 1

    out_path = CORRECTED / fname
    print(f"\n{fname}")
    df = pd.read_csv(path, dtype=str)
    n_applied = n_skipped = n_failed = 0

    for c in corrections:
        state, msg, hashes = fix_cell(
            df,
            fix_id=c["fix_id"],
            province=c["province"],
            district=c["district"],
            year=c["year"],
            bad=c["bad"],
            good=c["good"],
            name_flag=c.get("name_flag", _ANY),
        )
        tag = f"[{state.upper():8s}]"
        print(f"  {tag} {c['fix_id']}/{c['district']}/{c['year']}: {msg}")

        if state in ("applied", "skipped"):
            n_applied += (state == "applied")
            n_skipped += (state == "skipped")
            _log_fix(
                applied_log,
                fname=fname,
                fix_id=c["fix_id"],
                region_name=c["district"],
                year=c["year"],
                table_type=c.get("table_type", ""),
                hashes=hashes,
            )
        else:
            n_failed += 1

    if n_applied > 0 and not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"  → wrote {out_path}")

    return n_applied, n_skipped, n_failed


def apply_file_flags(fname, corrections, dry_run, applied_log):
    path = _source_path(fname)
    if not path.exists():
        print(f"\n  [MISSING ] {fname}", file=sys.stderr)
        return 0, 0, 1

    out_path = CORRECTED / fname
    print(f"\n{fname} (flag corrections)")
    df = pd.read_csv(path, dtype=str)
    n_applied = n_skipped = n_failed = 0

    for c in corrections:
        state, msg, hashes = fix_flag(
            df,
            fix_id=c["fix_id"],
            province=c["province"],
            district=c["district"],
            year=c["year"],
            value_key=c["value_key"],
            bad_flag=c["bad_flag"],
            good_flag=c["good_flag"],
        )
        tag = f"[{state.upper():8s}]"
        print(f"  {tag} {c['fix_id']}/{c['district']}/{c['year']}: {msg}")

        if state in ("applied", "skipped"):
            n_applied += (state == "applied")
            n_skipped += (state == "skipped")
            _log_fix(
                applied_log,
                fname=fname,
                fix_id=c["fix_id"],
                region_name=c["district"],
                year=c["year"],
                table_type="",
                hashes=hashes,
            )
        else:
            n_failed += 1

    if n_applied > 0 and not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"  → wrote {out_path}")

    return n_applied, n_skipped, n_failed


# ─── entry point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing files")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — no files will be modified\n")

    total_applied = total_skipped = total_failed = 0
    applied_log = []

    for fname, corrections in CORRECTIONS_BY_FILE.items():
        na, ns, nf = apply_file(fname, corrections, args.dry_run, applied_log)
        total_applied += na
        total_skipped += ns
        total_failed  += nf

    for fname, corrections in FLAG_CORRECTIONS_BY_FILE.items():
        na, ns, nf = apply_file_flags(fname, corrections, args.dry_run, applied_log)
        total_applied += na
        total_skipped += ns
        total_failed  += nf

    # Pass-through: mirror every source CSV into corrected_csvs/ so downstream
    # stages (standardize_pipeline.py) read a complete set. Files that had no
    # applied corrections are copied verbatim; corrected files are already
    # written by the passes above and are not overwritten.
    if not args.dry_run:
        CORRECTED.mkdir(parents=True, exist_ok=True)
        n_copied = 0
        for src in sorted(CSVS.glob("*.csv")):
            dst = CORRECTED / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                n_copied += 1
        if n_copied:
            print(f"\nCopied {n_copied} unchanged CSV(s) verbatim into {CORRECTED}")

    print(f"\n{'─'*60}")
    print(f"  applied : {total_applied}")
    print(f"  skipped : {total_skipped}")
    print(f"  failed  : {total_failed}")

    if total_failed > 0:
        print("\nFAILED corrections require investigation.", file=sys.stderr)

    if not args.dry_run and applied_log:
        SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(applied_log).to_csv(SIDECAR, index=False)
        print(f"\nSidecar written: {SIDECAR} ({len(applied_log)} row(s))")

    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
