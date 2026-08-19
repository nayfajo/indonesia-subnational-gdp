"""
fix_p1_spelling_variants.py

P1: Merge 4 spelling-variant id pairs that cause phantom district splits in the panel.

Problem: BPS publications use inconsistent spellings across eras for 4 districts.
The district_reference.csv has both spellings as separate district_ids, so the
harmonizer assigns different district_ids to the same physical district depending
on the publication era — creating artificial year gaps.

Canonical chosen = the form used by the majority of publications (modern BPS form):
  BATANG HARI (JAMBI)              — 1996-2001 print BATANGHARI; 2002+ print BATANG HARI
  BUKITTINGGI (SUMATERA BARAT)     — 1996-2001 print BUKIT TINGGI; 2002+ print BUKITTINGGI
  SAWAH LUNTO (SUMATERA BARAT)     — 1996-2001 print SAWAHLUNTO;  2002+ print SAWAH LUNTO
  BANJAR BARU (KALIMANTAN SELATAN) — 2000-2001 print BANJARBARU;  2002+ print BANJAR BARU

Fix:
  1. name_corrections.csv — add/update entries to map non-canonical → canonical
  2. district_reference.csv — remove the 4 non-canonical duplicate rows
"""

from pathlib import Path
import pandas as pd

CROSSWALKS = Path("crosswalks")


# ── 1. name_corrections.csv ─────────────────────────────────────────────────

nc_path = CROSSWALKS / "name_corrections.csv"
nc = pd.read_csv(nc_path, dtype=str)

# Update existing entries whose corrected value points at a now-removed variant
nc.loc[nc["region_name_base_raw"] == "BATANGHAN",    "region_name_base_corrected"] = "BATANG HARI"
nc.loc[nc["region_name_base_raw"] == "SAWAH LUNTO /","region_name_base_corrected"] = "SAWAH LUNTO"

# New spelling-variant entries
new_rows = pd.DataFrame([
    {
        "region_name_base_raw":       "BATANGHARI",
        "region_name_base_corrected": "BATANG HARI",
        "correction_type": "spelling_variant",
        "source_files": "PDRB_1996-1999_wide_a.csv,PDRB_2000-2001_wide_v2.csv,"
                        "PDRB_2011-2013_wide_v2.csv,PDRB-capita_2000-2001_wide_v2.csv,"
                        "PDRB-capita_2011-2013_wide_v2.csv",
        "notes": "One-word variant of Batang Hari (Jambi); BATANG HARI is canonical (2002+ BPS form)",
    },
    {
        "region_name_base_raw":       "BUKIT TINGGI",
        "region_name_base_corrected": "BUKITTINGGI",
        "correction_type": "spelling_variant",
        "source_files": "PDRB_1996-1999_wide_a.csv,PDRB_2000-2001_wide_v2.csv,"
                        "PDRB-capita_2000-2001_wide_v2.csv",
        "notes": "Two-word variant of Bukittinggi (Sumatera Barat); BUKITTINGGI is canonical (2002+ BPS form)",
    },
    {
        "region_name_base_raw":       "SAWAHLUNTO",
        "region_name_base_corrected": "SAWAH LUNTO",
        "correction_type": "spelling_variant",
        "source_files": "PDRB_1996-1999_wide_a.csv,PDRB_2000-2001_wide_v2.csv,"
                        "PDRB-capita_2000-2001_wide_v2.csv",
        "notes": "One-word variant of Kota Sawah Lunto (Sumatera Barat); SAWAH LUNTO is canonical. "
                 "Note: SAWAHLUNTO/SIJUNJUNG (kabupaten) is a different district — exact-match safe.",
    },
    {
        "region_name_base_raw":       "BANJARBARU",
        "region_name_base_corrected": "BANJAR BARU",
        "correction_type": "spelling_variant",
        "source_files": "PDRB_2000-2001_wide_v2.csv,PDRB-capita_2000-2001_wide_v2.csv",
        "notes": "One-word variant of Banjarbaru (Kalimantan Selatan); BANJAR BARU is canonical (2002+ BPS form)",
    },
])

nc = pd.concat([nc, new_rows], ignore_index=True)
nc.to_csv(nc_path, index=False)
print(f"name_corrections.csv: updated 2 rows, added 4 rows → {len(nc)} total")


# ── 2. district_reference.csv ────────────────────────────────────────────────

dr_path = CROSSWALKS / "district_reference.csv"
dr = pd.read_csv(dr_path, dtype=str)

to_remove = {
    "JAMBI_BATANGHARI",
    "KALIMANTAN_SELATAN_BANJARBARU",
    "SUMATERA_BARAT_BUKIT_TINGGI",
    "SUMATERA_BARAT_SAWAHLUNTO",
}

before = len(dr)
dr = dr[~dr["district_id"].isin(to_remove)]
dr.to_csv(dr_path, index=False)
print(f"district_reference.csv: removed {before - len(dr)} rows → {len(dr)} total")
print(f"  Removed: {sorted(to_remove)}")
