# Subnational GDP for Indonesia: A District-Level Panel, 1996–2025 — Data Notes and Codebook

*Nayfa Johan (Purdue University, Department of Economics) and Russell Hillberry (Purdue University, Department of Agricultural Economics).*[^funding]

[^funding]: This research was supported by the Purdue University Research Center in Economics (PURCE).

[^bps_pub]: BPS publication portal: <https://www.bps.go.id/id/publication?keyword=Produk+Domestik+Regional+Bruto+Kabupaten%2FKota+di+Indonesia+2020-2024&sort=latest> (search interface; accessed 14 August 2026).

[^dapoer]: World Bank Indonesia Database for Policy and Economic Research (DAPOER): <https://databank.worldbank.org/source/indonesia-database-for-policy-and-economic-research> (accessed 14 August 2026).

## Abstract

We provide a district-level panel of Indonesian regional GDP (Produk Domestik Regional Bruto, PDRB) covering 1996 to 2025 (2024–25 provisional). The panel reports nominal, real (constant-price), and per-capita PDRB, harmonized to 2000-vintage administrative boundaries so that more than 350 districts stay consistently defined across three decades of administrative splits (*pemekaran*). The panel is built from 21 archival BPS (Badan Pusat Statistik, Statistics Indonesia) publications, parsed from PDF; all source files, crosswalks, scripts, and outputs are included for full replication, and the unharmonized ("native") panels are retained alongside the harmonized ones. We cross-validate against the World Bank's INDO-DAPOER database. 
*Contents: Quick Start · Background: Key Concepts · §1 Introduction · §2 File Structure · §3 Source Data · §4 Pipeline · §5 Column Definitions · §6 Working with the Data · §7 Known Limitations · §8 DAPOER Cross-Validation · §9 Corrections and Provenance · Errata and contact*

---

## Quick Start

The dataset ships five panel files:

| File | Series | Years |
| --- | --- | --- |
| `outputs/panel_pdrb_total_2000bounds.csv` | total PDRB, harmonized to 2000 boundaries | 1996–2025 |
| `outputs/panel_pdrb_capita_2000bounds.csv` | per-capita PDRB, harmonized | 1996–2025 |
| `outputs/panel_pdrb_chained_2000bounds.csv` | chain-linked real (2010 base), harmonized | 2002–2025 |
| `outputs/panel_pdrb_total_native.csv` | total PDRB, native (unharmonized) | 1996–2025 |
| `outputs/panel_pdrb_capita_native.csv` | per-capita PDRB, native (unharmonized) | 1996–2025 |

The `_2000bounds` files are the recommended default. Use the `_native` files when you need exactly what a BPS publication printed; use the chained file only for cross-base-year growth analysis.

Load a panel and filter to a working series:

```python
import pandas as pd
df = pd.read_csv("outputs/panel_pdrb_total_2000bounds.csv")

# Nominal PDRB, confirmed figures, no pre-split aggregate rows
nom = df[
    (df.table_type == "nominal") &
    (df.is_provisional == False) &
    (df.is_pre_split_aggregate == False)
]
```

Values in `value_standardized` are in rupiah. Divide by `1e6` to match the DAPOER convention (IDR million). Always drop `is_pre_split_aggregate == True` rows before any aggregation; they repeat a child district's value inside its parent and double-count on summation (§7.9).

The three real GDP series are not comparable across base years: `real/1993` (1996–2003), `real/2000` (2002–2012), and `real/2010` (2011–2025) use different price bases and SNA vintages. Jumps at 2003 or 2013 are methodological breaks, not economic signals. Use nominal for a continuous series, or the chained panel for cross-regime growth (§7.1).

Aceh district values for 2000–2001 reflect contemporaneous conflict-period reporting and are substantially below BPS's later retrospective revisions for several districts. For pre-2002 Aceh, restrict to 2002 onward or substitute DAPOER's revised values, documenting the choice (§7.2).

The per-capita `_2000bounds` panel is not territory-consistent across split years. After a district splits, the parent's per-capita series covers the rump territory only, not the full 2000-vintage area. The most visible case is Sumbawa, which drops 66% in 2004 when its mine separates. For a boundary-consistent per-capita series across a split year, divide total-panel PDRB by an external population series (§7.14).

The chained panel's levels are synthetic and not additive across districts. Do not sum them into a province total; use the chained file for growth rates only (§7.8).

Known errors have been corrected and documented (143 corrections; §9), but undetected errors may remain. For analysis sensitive to individual cell values, verify against `parsed_csvs/` (replication package) or the source PDF (§7.15).

---

## Background: Key Concepts

PDRB (Produk Domestik Regional Bruto) is the regional analogue of GDP: the gross value added produced within a district (*kabupaten*/regency or *kota*/city) in a given year. BPS publishes it both at current prices (nominal) and at constant prices of a fixed base year (real). Three accounting regimes appear in this dataset: SNA 1993 at base year 1993 (publications covering 1996–2003), SNA 1993 at base year 2000 (2002–2012), and SNA 2008 at base year 2010 (2011–2025). A base year fixes the price vector used to value real output; an SNA vintage fixes the accounting methodology, including sector definitions, imputations, and coverage. Real levels are therefore not comparable across regimes: a jump at a rebasing boundary (2003 or 2013) reflects a methodological change rather than an economic event. Nominal values are continuous across the full period.

Since decentralization began in 1999, Indonesia has repeatedly split districts and provinces (*pemekaran*), creating hundreds of new *kabupaten* and *kota*; a district reported as one unit in 1998 may be four units by 2015. To build a consistent panel, we fix a single boundary vintage of 2000 and aggregate later child districts back to their 2000-vintage parents (Section 4; residual complications in Section 7). BPS also routinely publishes two PDRB variants: a total that includes oil and gas, and a *tanpa migas* variant that excludes the oil-and-gas sector, whose output is volatile and geographically concentrated. Where BPS published both variants, we retain them as separate panel rows. The oil-excluded variant exists only in the publications covering 1996 to 2010.

Sumbawa, in Nusa Tenggara Barat, illustrates the mechanism. In the 2000-vintage map it is a single *kabupaten*, but in 2003 a new *kabupaten*, Sumbawa Barat, split off from it under *pemekaran*. In the `_native` panels the two appear exactly as BPS published them: one Sumbawa row before 2003, then two rows — Sumbawa and Sumbawa Barat — from 2004 onward. In the harmonized `_2000bounds` panel they are instead summed back into a single Sumbawa row for every year, so the series refers to the same 2000-vintage territory throughout. This re-aggregation, applied to roughly 120 post-2000 splits, is 2000-vintage boundary harmonization.

We also provide a chain-linked panel that splices the older series onto the 2010-price base at a 2011 pivot (`table_type == 'real_chained'`). Its levels are synthetic constant-2010-price figures. They are suitable for growth analysis, but they are not additive across districts (Section 7.8). A small set of observations was manually corrected for confirmed BPS source errors, transcription artifacts, or values recovered from BPS Query Builder exports; every corrected value carries a stable `correction_id` linked to its justification (Section 9).

---

## 1. Introduction

These data come from an undergraduate research project conducted in 2025–2026. Nayfa Johan, a native speaker of Bahasa Indonesia, conducted the primary research; Dr. Russell Hillberry supervised.

The challenge is geographic consistency: if district boundaries change mid-panel, a measured GDP drop may reflect administrative separation rather than economic decline.

INDO-DAPOER covers 2000–2020 and includes no per-capita series. This panel is built from BPS archival publications and documents how every administrative boundary change and methodology break is handled. The pipeline reproduces from the included parsed CSVs (archival PDFs also provided); DAPOER serves as a cross-validation check, not a source.

The unharmonized (native) panels are retained alongside the harmonized ones, so a user can reconstruct exactly what any individual publication printed; every value carries its source publication, a priority rank, its harmonization status, and any correction identifier. Where two publications report the same district-year, we use the later one — BPS revisions reflect improved field coverage — with the earlier figure visible in the native panels. Known source errors, boundary seams, and structural gaps are documented in Section 7 rather than quietly patched.

---

## 2. File Structure

The project root contains:

| Directory | Contents |
| --- | --- |
| `raw/` | Source material. `raw/pdf/` holds the BPS publication PDFs; `raw/csv/` and `raw/parsed/` hold intermediate parse artifacts. |
| `parsed_csvs/` | The 21 parsed CSVs (Stage 1 output), verbatim transcriptions of the source PDFs. In the replication package only (not in the GitHub repository). Stage 2 reads these and writes corrected copies to `corrected_csvs/`, which is regenerated at runtime and not shipped. |
| `corrections/` | `corrections/corrections_applied.csv`, the correction sidecar. In the replication package. (The external CSVs used for recoveries are in the full project repository, not the replication package; see Section 9.) |
| `pipeline_out/` | Intermediate pipeline outputs (`pipeline_out/standardized/` = Stage 3; `pipeline_out/harmonized/` = Stage 4; `pipeline_out/audits/` = Stage 6 QA reports). Regenerated at runtime; not included in the replication package. |
| `outputs/` | The published panels (see inventory below). These are the files a data user reads. |
| `crosswalks/` | Harmonization inputs: `district_reference.csv` (canonical district list), `province_crosswalk.csv`, `name_corrections.csv`, `split_concordance.csv` (pemekaran parent↔child map), and supporting pemekaran source tables. |
| `scripts/` | The pipeline scripts (Section 4) plus one-off fix scripts and audit utilities. |
| `docs/` | This codebook (`codebook.md`) and the methodology and decision log (`research_log.md`). The codebook ships in the replication package; `research_log.md` is in the full project repository only. |

### Published panel inventory (`outputs/`)

**Table 1. Published panels (produced outputs).** The five output panels (contrast Tables 2–3, the BPS input sources).

| File | Boundaries | Series | Rows | Districts | Years |
| --- | --- | --- | --- | --- | --- |
| `panel_pdrb_total_2000bounds.csv` | 2000-vintage (harmonized) | total PDRB | 23,743 | 361 | 1996–2025 |
| `panel_pdrb_total_native.csv` | native (unharmonized) | total PDRB | 31,035 | all incl. post-2000 children | 1996–2025 |
| `panel_pdrb_capita_2000bounds.csv` | 2000-vintage (harmonized) | per-capita PDRB | 10,400 | 363 | 1996–2025 |
| `panel_pdrb_capita_native.csv` | native (unharmonized) | per-capita PDRB | 13,894 | all incl. post-2000 children | 1996–2025 |
| `panel_pdrb_chained_2000bounds.csv` | 2000-vintage (harmonized) | chain-linked real (2010 base) | 8,315 | 348 | 2002–2025 |

The `_2000bounds` files are the recommended default. Use the `_native` files when you need exactly what a publication printed; use the chained file only for cross-base-year real growth analysis, subject to Sections 6 and 7.8. (2024–25 provisional as of deposit, Aug 2026.) Intermediate outputs (`pipeline_out/`) are generated locally by `run_all.sh` and are not shipped.

---

## 3. Source Data

The panel is built from 21 BPS source files[^bps_pub]: 11 total-PDRB source files and 10 per-capita source files. (The 11 total sources include the `PDRB_1998-2001_jabar_banten` file, a supplementary BPS volume added to fill the Banten and post-split Jawa Barat 2000–2001 window; see Section 7.7.) Source files correspond one-to-one with the parsed CSVs in `parsed_csvs/` (replication package). BPS releases rolling multi-year windows; overlaps are resolved by source priority (Section 4, Stage 5).

### Total-PDRB source files

**Table 2. Total-PDRB source publications (BPS input data).** Archival BPS volumes ingested by the pipeline. Each row is one published volume; base year and SNA vintage fix the price and methodology regime (see Background). Windows overlap by design and are reconciled by source priority in Stage 5.

| Source file (window) | Base year | SNA vintage | Parsing notes |
| --- | --- | --- | --- |
| `PDRB_1996-1999` | 1993 | SNA 1993 | Physical scan PDF; parsed in vision mode |
| `PDRB_1998-2001_jabar_banten` | 1993 | SNA 1993 | Supplementary BPS volume; supplies Banten + post-split Jawa Barat 2000–2001 (Section 7.7) |
| `PDRB_2000-2001` | 1993 | SNA 1993 | Digital PDF; constant-price tables are still base-1993 despite the publication title (see Coverage Summary below) |
| `PDRB_2002-2004` | 2000 | SNA 1993 | Digital PDF |
| `PDRB_2005-2007` | 2000 | SNA 1993 | Image-only PDF; parsed in vision mode |
| `PDRB_2008-2010` | 2000 | SNA 1993 | Digital PDF |
| `PDRB_2011-2013` | 2010 | SNA 2008 | Digital PDF |
| `PDRB_2014-2016` | 2010 | SNA 2008 | Digital PDF |
| `PDRB_2017-2019` | 2010 | SNA 2008 | Digital PDF |
| `PDRB_2020-2022` | 2010 | SNA 2008 | Digital PDF |
| `PDRB_2021-2023` | 2010 | SNA 2008 | Extends provisionally to 2025 |

### Per-capita source files

**Table 3. Per-capita PDRB source publications (BPS input data).** Ten per-capita volumes parallel the ten main total-PDRB volumes, one per window. (The per-capita panel is nominal.)

| Source file (window) | Base year | SNA vintage | Parsing notes |
| --- | --- | --- | --- |
| `PDRB-capita_1996-1999` | 1993 | SNA 1993 | Physical scan PDF; parsed in vision mode |
| `PDRB-capita_2000-2001` | 2000 | SNA 1993 | Sumatera Barat 2000–2001 corrected using BPS Query Builder (Section 9, W2c). Per-capita is nominal only; base year reflects the publication label (contrast `PDRB_2000-2001` in Table 2, which is base-1993 in content despite its title). |
| `PDRB-capita_2002-2004` | 2000 | SNA 1993 | Digital PDF |
| `PDRB-capita_2005-2007` | 2000 | SNA 1993 | Image-only PDF; parsed in vision mode |
| `PDRB-capita_2008-2010` | 2000 | SNA 1993 | Digital PDF |
| `PDRB-capita_2011-2013` | 2010 | SNA 2008 | Kalimantan Utara column shift corrected (Section 9, KALTARA_shift) |
| `PDRB-capita_2014-2016` | 2010 | SNA 2008 | Digital PDF |
| `PDRB-capita_2017-2019` | 2010 | SNA 2008 | Five Lampung districts had wrong population denominators; corrected (Section 9, W2/W2b) |
| `PDRB-capita_2020-2022` | 2010 | SNA 2008 | Digital PDF |
| `PDRB-capita_2021-2023` | 2010 | SNA 2008 | Extends provisionally to 2025 |

The per-capita panel includes 1996–1999 data for 139 districts from the 1996–1999 per-capita volume, but several districts (including Banda Aceh and Ambon) lack pre-2000 per-capita observations; their coverage begins in 2000.

### Coverage summary

| Panel | Districts | Years | Rows |
| --- | --- | --- | --- |
| total_2000bounds | 361 | 1996–2025 | 23,743 |
| capita_2000bounds | 363 | 1996–2025 | 10,400 |
| chained | 348 | 2002–2025 | 8,315 |

Real-series windows in the (non-chained) total panel:
- **real/1993:** 1996–2003 (SNA 1993, base 1993)
- **real/2000:** 2002–2012 (SNA 1993, base 2000; the 2000–2001 publication's constant-price tables are still base-1993)
- **real/2010:** 2011–2025 (SNA 2008, base 2010)
- **nominal:** continuous 1996–2025
- **oil-excluded:** available in 1996–2010-era publications only.

### Parsing methodology (including LLM use)

We parsed the BPS PDF tables to wide-format CSVs with a large language model (Claude), which transcribes each table verbatim, preserving Indonesian number formatting. Two publications are physical scans (1996–1999 total and 2005–2007 total) and were parsed in vision mode, in which the model reads the rendered page image rather than an embedded text layer. Numeric interpretation (format conversion, series-type extraction, unit handling) happens at later deterministic stages, so parse output can be diffed directly against the source page. Every parsed CSV is retained in `parsed_csvs/` (replication package).

LLM transcription introduces occasional character-level errors, and the BPS sources themselves contain errors; a manual correction stage applies 143 content-keyed corrections (22 fix families), each documented and reversible (Section 9).

---

## 4. Pipeline

The pipeline runs in seven stages. Scripts live in `scripts/`. Stage 1 requires a paid vision API and is not re-run in replication; its output ships in `parsed_csvs/`. `run_all.sh` chains Stages 2–7 in order and writes SHA-256 checksums of the five output panels.

**Stage 1: Parse. `parse_pdfs_text.py` / `parse_pdfs_scan.py` / `reparse_pages_vision.py` → `parsed_csvs/`**
Emits one wide-format CSV per publication, transcribed verbatim. `parse_pdfs_text.py` processes the digital PDFs (2000–2023) in text-extraction mode; `parse_pdfs_scan.py` handles the 1996–1999 physical scan in vision mode. `reparse_pages_vision.py` re-parses individual pages in vision mode where text extraction misassigns column positions (sparse new-district rows and image-only pages). 
**Stage 2: Corrections. `apply_corrections.py` → `corrected_csvs/` (regenerated at runtime, not shipped)**
Applies the 143 corrections for confirmed BPS source errors, transcription artifacts, and BPS Query Builder recoveries; the source files are not modified. Each correction is content-keyed, matched on (province, district, year, current value) rather than row index, so it survives re-parsing and re-ordering. Each resolves to one of three states: apply (the bad value is found and corrected), skip (the good value is already present — the correction was previously applied), or hard-fail (the value is neither the expected bad value nor the corrected one, which signals an unexpected upstream change and stops the run for inspection). A sidecar, `corrections/corrections_applied.csv`, records every applied correction with its `correction_id` (Section 9).

**Stage 3: Standardize. `standardize_pipeline.py` → `pipeline_out/standardized/` (21 files)**
Converts Indonesian-formatted strings to floats and extracts series metadata from headers and row structure: `table_type`, `base_year`, `oil_excluded`, `admin_type`, and `unit`/`unit_multiplier`. Deterministic rules handle known quirks: a recurring garbled header, BPS structural sub-total markers that mimic oil-excluded rows, and a unit override for one mislabeled Aceh per-capita table.

**Stage 4: Harmonize. `harmonize_regions.py` → `pipeline_out/harmonized/` (21 files)**
Assigns the canonical `district_id`, applies name corrections (`crosswalks/name_corrections.csv`), and resolves pemekaran via `crosswalks/split_concordance.csv`; the legal basis (UU number) for each split was verified against JDIH (peraturan.bpk.go.id) and Kemendagri pemekaran records.[^pemekaran_sources] Post-2000 child districts are aggregated back to their 2000-vintage parent (`is_child_aggregate = True` on summed rows), subject to an early-data carve-out: a concordance child that appears as a standalone, non-`#)` data row in an early file (1996–1999 or 2000–2001) is treated as its own 2000-vintage unit, regardless of magnitude. Every row receives a `match_status`.

[^pemekaran_sources]: Kemendagri PELITA: <https://pelita.kemendagri.go.id/>. Kemendagri daerah otonom pemekaran data (kabupaten/kota, 1994–2014): <https://ppid.kemendagri.go.id/front/dokumen/detail/500391609>. RISED Pemekaran Daerah Kabupaten/Kota dataset: <https://figshare.com/> (search "RISED Pemekaran").

**Stage 5: Build panel. `build_panel.py` → `outputs/`**
Stacks the 21 harmonized files and enforces uniqueness on the panel key `(district_id, year, table_type, base_year, oil_excluded)`. On a collision, the higher `source_priority` (later publication) wins, and non-provisional rows are promoted over provisional ones.

**Stage 6: Validate. `validate_panel.py` → `pipeline_out/audits/`**
Eleven QA checks: duplicate keys, within-district year gaps, growth-rate anomalies, province-sum reconciliation, implied-population and implied-deflator smoothness, and roster completeness across publications. Reports are reviewed manually and inform Section 7.

**Stage 7 (optional): Chain-link. `chain_link.py` → `outputs/panel_pdrb_chained_2000bounds.csv`**
Splices the real/2000 series onto the real/2010 base using `link_year = 2011`, producing a synthetic constant-2010-price level series. See Section 7.8.

---

## 5. Column Definitions

Columns are defined for the primary panels (`panel_pdrb_total_2000bounds.csv`, `panel_pdrb_capita_2000bounds.csv`), which share an identical column set. Columns exclusive to the chained panel are marked **(chained only)**.

### Identification

| Column | Type | Definition |
| --- | --- | --- |
| `district_id` | string | Canonical permanent identifier at 2000-vintage boundary, format `PROVINCE_DISTRICT_NAME` (e.g., `ACEH_BANDA_ACEH`). Where a kabupaten and kota share the same name, a `_KAB` or `_KOTA` suffix disambiguates (e.g., `JAWA_BARAT_BOGOR_KAB`, `JAWA_BARAT_BOGOR_KOTA`). Stable across the panel. |
| `year` | integer | Calendar year of observation. |
| `district_num` | integer | District sequence number in the BPS reference list (`crosswalks/district_reference.csv`). |
| `bps_code` | string | Official BPS 4-digit Kode Wilayah (e.g., `1107` for Aceh Barat). Standard cross-dataset join key for BPS administrative data. Two caveats: (1) roughly 15 pre-split parent/successor pairs share the same code (e.g., `BUNGOTEBO` and `BUNGO` both map to `1509`), so `bps_code` alone is not a unique key; always join on `district_id`; (2) the province prefix of `bps_code` does not match `province_canonical` for three province-migrated districts (POLEWALIMAMASA, PASANGKAYU, KEPULAUAN_RIAU). |
| `province_canonical` | string | Harmonized province name, all-caps. |
| `district_name_2000` | string | Canonical district name at 2000-vintage boundary, all-caps. |
| `admin_type` **(chained only)** | string | `kabupaten` (regency) or `kota` (city). Assigned from the BPS regency code where the publication did not label it: `kota` if `(bps_code mod 100) ≥ 71`, else `kabupaten`. Used internally during harmonization for all panels to disambiguate kab/kota pairs; retained as an output column only in the chained panel. |

### Series key

| Column | Type | Definition |
| --- | --- | --- |
| `table_type` | string | `nominal` (current price), `real` (constant price), or `real_chained` (chained panel only). |
| `base_year` | integer / NaN | Base year of a real series: `1993`, `2000`, or `2010`. `NaN` for nominal. The three base years are not comparable across breaks. |
| `oil_excluded` | boolean | `True` = PDRB *tanpa migas* (excluding oil and gas). `False` = total PDRB (oil-inclusive). Both variants are separate panel rows where published. Oil-excluded rows exist only for 1996–2010-era publications; for 2011+ rows, `oil_excluded == False` means the row is the oil-inclusive total — those publications carry no oil-excluded variant. |

Together with `district_id` and `year`, `(table_type, base_year, oil_excluded)` form the enforced unique panel key.

### Value

| Column | Type | Definition |
| --- | --- | --- |
| `value_standardized` | float | PDRB value in rupiah (total panel) or rupiah per person (per-capita panel). BPS reported in mixed units (jutaan/miliar/ribu rupiah); all have been converted to rupiah by applying `unit_multiplier`. No further multiplier is needed at read time. |
| `unit` | string | Original BPS unit string (e.g., `juta rupiah`, `miliar rupiah`, `ribu rupiah`, `rupiah`). |
| `unit_multiplier` | float | Factor applied to reach rupiah: `1e6` (juta), `1e9` (miliar), `1e3` (ribu), `1.0` (rupiah). |

### Provenance

| Column | Type | Definition |
| --- | --- | --- |
| `source_file` | string | BPS publication CSV filename (e.g., `PDRB_2021-2023.csv`, `PDRB-capita_1996-1999.csv`). |
| `source_priority` | integer (0–10) | Publication rank; higher = later. On a key collision, the higher-priority row wins ("later wins"), reflecting BPS field-coverage revisions. |
| `match_status` | string | Harmonization outcome (Stage 4). Enumerated values below. |
| `correction_id` | string / NaN | Fix identifier linking this row to the correction sidecar (§9). Present on `_native` and chained panels; `NaN` if the row was not corrected. Not present on `_2000bounds` panels (child summation collapses multiple source rows into one). |

The `match_status` values are:

| Value | Meaning |
| --- | --- |
| `matched` | Direct match on `(province, district_name_2000)`. |
| `matched_with_admin_type` | A district whose name is shared by a *kabupaten* and a *kota* (e.g. Bogor, Bandung, Serang), disambiguated to the correct unit using the source `admin_type`. This covers 3,389 rows in the total `_2000bounds` panel and 1,500 in the per-capita panel. One historical rename means `district_reference.csv` carries 422 rows for 421 2000-vintage districts; analysts who join on that file should key on `district_id`, not name. See the research log for the specific case. |
| `matched_province_fallback` | District matched by name alone; province inferred from adjacent rows, a lower-confidence provenance (231 rows in the total `_2000bounds` panel, 54 in the per-capita `_2000bounds` panel). |
| `child` | Harmonize-layer: a post-2000 split (child) district passed through to the full granular panel with `district_id` null. Present only in the `_native` panels. |
| `child_aggregate` | Build-panel-layer: set on standalone orphan rows produced during child summation when the 2000-vintage parent is absent from that source file (the `_2000bounds` total panel). Distinct from `is_child_aggregate`, which flags the summed-parent rows. Correct at child granularity; incomplete for harmonized-parent totals, because the rump parent was absent from the source. |

`correction_id` is a separate column; it does not appear as a `match_status` value. The `_2000bounds` panels do not carry it: child summation collapses multiple source rows into one. To trace corrections for the `_2000bounds` panels, use the sidecar directly (Section 9).

### Flags

| Column | Type | Definition |
| --- | --- | --- |
| `is_provisional` | boolean | `True` if BPS marked the year preliminary (*angka sementara* / *angka sangat sementara*). Provisional rows are kept; source-priority dedup promotes non-provisional over provisional for the same key. |
| `is_pre_split_aggregate` | boolean | `True` if BPS printed a "pre-split aggregate" sub-row (marked `#)`): a child district shown before its formal split, whose value double-counts into the parent. The `#)` marker is structural, not a migas indicator, so these rows are not treated as oil-excluded. Filter these out before any aggregation. |
| `is_child_aggregate` | boolean | `True` if the row was produced by summing post-2000 child districts back to their 2000-vintage parent (the pemekaran aggregation). `False` if the district stood alone in the publication. Total panel only; always `False` in the per-capita panel, whose split parents continue as rump-territory series (Section 7.14). |
| `is_backcast` **(chained only)** | boolean | `True` if the observation was backcast from the 2010 base using the real/2000 growth rate. Backcast values are synthetic 2010-price levels, not BPS-published. |
| `link_year` **(chained only)** | integer | Pivot year used for chain-linking (`2011` throughout). |
| `link_ratio` **(chained only)** | float | Ratio of real/2010 to real/2000 at the link year, used to rescale pre-2011 real/2000 values onto the 2010 base. |
| `ratio_drift_flag` **(chained only)** | boolean | `True` if the district's real/2000 and real/2010 growth rates disagree by >5% at the 2012 validation year (one year past the pivot). 10 districts are flagged; treat their backcasts with extra caution. |

The chained panel additionally carries `region_name_corrected`, `is_post2000_child`, and `parent_district_id` for auditing the aggregation.

---

## 6. Working with the Data

The panel CSVs load directly in Stata, R, Python, or Excel without transformation.

```stata
import delimited "panel_pdrb_total_2000bounds.csv", stringcols(_all) clear
```
```r
df <- read.csv("panel_pdrb_total_2000bounds.csv", stringsAsFactors = FALSE)
```
```python
df = pd.read_csv("panel_pdrb_total_2000bounds.csv")
```

Section 5 defines every column; the notes below flag the most common sources of silent errors.

**Unit.** `value_standardized` is in rupiah — the `unit_multiplier` column has already been applied. Do not multiply again. To convert to IDR millions (the DAPOER convention), divide by 1,000,000.

**Booleans.** `is_provisional`, `is_pre_split_aggregate`, and `is_child_aggregate` are stored as `True`/`False` text in the CSV (primary panels); `is_backcast` follows the same convention in the chained panel. pandas and R auto-convert these to native logical types on read, so `== False` / `== FALSE` works directly. Stata loaded with `stringcols(_all)` keeps them as strings, so filter with `keep if is_pre_split_aggregate == "False"` (quoted).

**Nominal rows have no base year.** `base_year` is blank for nominal rows — expected, not missing data. Real levels are not comparable across base years (1993, 2000, 2010); always filter to one base year before comparing levels or growth rates.

**Panel key.** The unique key is `(district_id, year, table_type, base_year, oil_excluded)`. Verify uniqueness on this key before summing districts or provinces to avoid double-counting pre-split aggregate rows.

**Chained panel.** The chained panel values are synthetic 2010-price levels and are not additive across districts; use it for growth rates only, never sum to a province total (Section 7.8). Backcast rows (`is_backcast == True`) are model-derived; ten districts carry `ratio_drift_flag == True` and deserve extra caution.

---

## 7. Known Limitations

The issues below are features of the data, pipeline decisions, or inherited BPS conventions — not errors.

| § | Issue | User action |
|---|-------|-------------|
| 7.1 | Three real series are discontinuous across base-year regimes | Never compare real levels across a publication boundary; use nominal for a continuous level series |
| 7.2 | Aceh 2000–2001 reflects contemporaneous BPS, not the later revision | Restrict to `year >= 2002`, or substitute DAPOER values by hand and document it |
| 7.3 | Fakfak 1996–1999 nulled (boundary change) | No action — rows already nulled; Fakfak is valid from 2000 on |
| 7.4 | MAMASA carried under SULAWESI BARAT even pre-2004 | Expect `SULAWESI_BARAT_MAMASA` throughout; no action on values |
| 7.5 | Tambrauw output attributed entirely to SORONG | Note MANOKWARI aggregate is slightly understated; adjust manually if material |
| 7.6 | Per-capita denominator errors corrected for Lampung + Sumatera Barat only | Verify other provinces, or compute per-capita from total panel ÷ independent population |
| 7.7 | Banten + West Java 2000–2001 gap filled from supplementary volume | Do not silently impute residual absences |
| 7.8 | Chained series is non-additive; backcasts are synthetic levels | Do not sum districts; use for growth analysis only |
| 7.9 | Pre-split aggregate rows double-count | `df[df.is_pre_split_aggregate == False]` before aggregating |
| 7.10 | Papua UU 26/2002 promulgation date inconsistent (Oct vs Dec) | Year is correct; ignore unless exact date matters |
| 7.11 | Provisional rows extend to 2025 | Filter `df.year <= 2023` unless provisional years are needed |
| 7.12 | Residual year-misassignment risk for sparse split-off rows | Verify against source PDF if exact split-year dynamics matter |
| 7.13 | Total and per-capita panels have different district-year coverage | Prefer total panel ÷ independent population for per-capita work |
| 7.14 | Per-capita `_2000bounds` denominator shifts at split years | Do not read per-capita across a split year as one continuous territory |
| 7.15 | Undetected errors may remain | Verify in `parsed_csvs/` and, if needed, the source PDF |

### 7.1 The three real GDP series are discontinuous

`real/1993` (1996–2003), `real/2000` (2002–2012), and `real/2010` (2011–2025) correspond to different base years and different SNA vintages (SNA 1993 for the first two, SNA 2008 for the third). Cross-series level comparisons are invalid; apparent change at a publication boundary (2003 or 2013) is a methodological break, not an economic signal. The overlap years (2002–2003 and 2011–2012) allow ratio-based splicing — which the chained panel uses — at the cost of synthetic levels (Section 7.8). The nominal series is usable across the full 1996–2025 span without adjustment; use nominal for a continuous level series.

### 7.2 Aceh 2000–2001 vintage seam

All Aceh district values for 2000–2001 derive from the 2000–2001 BPS publication and reflect contemporaneous conflict-period reporting. A cross-check against INDO-DAPOER shows substantially higher values for several Aceh districts in this period. DAPOER's 2000–2001 figures are consistent with its own 2002+ series, because DAPOER used the same later BPS retrospective revision that our panel picks up from 2002 onward. Ours are contemporaneous BPS publications; DAPOER's are a later revision. For analysis touching pre-2002 Aceh, choose a vintage explicitly. One option is to restrict the analysis window to 2002 and later (our 2002+ Aceh data agree with DAPOER exactly). The alternative is to substitute DAPOER's 2000–2001 Aceh values manually, since DAPOER district-level PDRB is publicly available from the World Bank[^dapoer]; document the substitution.

### 7.3 Fakfak 1996–1999 is unusable (BPS source error, nulled)

BPS printed nominal Fakfak values of ~4.35T / 4.63T / 12.5T / 11.4T rupiah for 1996–1999, then a ~96% drop to the 2000 value, a ~25× collapse. This reflects an administrative boundary change (old Fakfak encompassed areas now in Sorong and Manokwari), not an economic collapse; the real/1993 series shows the same discontinuity. All 1996–1999 Fakfak rows are nulled. Fakfak from 2000 onward reflects the smaller post-reorganization boundary and is retained.

### 7.4 MAMASA cross-province parent seam (resolved; retained in `_2000bounds`)

MAMASA split from POLEWALI MAMASA in 2002, before SULAWESI BARAT split from SULAWESI SELATAN in 2004. MAMASA appears in both `_2000bounds` panels as its own 2000-vintage unit (`SULAWESI_BARAT_MAMASA`), with 48 rows in the total panel and 23 in the per-capita panel (2003–2025). MAMASA is carried under its later (SULAWESI BARAT) provincial assignment throughout, including for years before that province formally existed.

### 7.5 Tambrauw dual-parent limitation

TAMBRAUW (created by UU 56/2008) split from both Sorong and Manokwari, but the split concordance assigns a single primary parent (SORONG). Any 2000-vintage aggregation therefore attributes all of Tambrauw's output to SORONG's territory, understating MANOKWARI's aggregate. The effect is small, but analysts working at the West Papua provincial level or on either parent should account for it.

### 7.6 Per-capita wrong-denominator errors: Lampung and Sumatera Barat corrected; other provinces not cross-checked

Two confirmed instances of wrong population denominators in BPS per-capita publications have been corrected:

- **2017–2019 publication, five Lampung districts.** The national publication's per-capita values conflict with those published on BPS Lampung's own provincial website; the provincial figures were adopted as correct (`correction_id = W2/W2b`).
- **2000–2001 publication, fifteen Sumatera Barat districts.** BPS used a single uniform denominator (~62,000) for every district regardless of actual population (which ranges from 42,000 to 743,000). Corrected from BPS Query Builder Seri 2000 export (`correction_id = W2c`).

The same error likely exists in other provinces' per-capita publications, particularly 2017–2019; no other province has been cross-checked against BPS provincial websites.

### 7.7 Banten + West Java 2000–2001 (gap now filled from a supplementary BPS volume)

Banten was carved from Jawa Barat in 2000, and the main 2000–2001 publication's nominal tables did not cover Banten or post-split Jawa Barat (its constant-price base-1993 tables did, as did the separate per-capita publication), leaving ~28 nominal district-year gaps. These are filled from a supplementary BPS source, `PDRB_1998-2001_jabar_banten` (a nominal-only volume covering 1998–2001); the pipeline ingests its 2000–2001 tables, and Banten 2000–2001 is present in the `_2000bounds` panel (24 nominal total-PDRB rows across the two years). Any residual absences reflect genuine source coverage limits; do not impute them.

The volume's 1998–1999 columns also cross-check the 1996–1999 parse; 38 of 52 comparable district-years agree within 5%. Details and the decision not to ingest the revised 1998–1999 values are in the research log.

### 7.8 Chained series: synthetic, non-additive levels

The chained panel backcasts real/2000 growth onto the real/2010 base. Backcast values (`is_backcast == True`) are synthetic 2010-price levels, not BPS-published, and are not additive across districts. Do not sum districts to obtain a province total from the chained panel. Use it for growth analysis only. Ten districts (`ratio_drift_flag == True`) show >5% disagreement between real/2000 and real/2010 growth at the 2012 validation year; treat their backcasts with extra caution.

The link ratio is taken at 2011; the overlap year 2012 was reserved for out-of-sample validation rather than averaging. The 2011 link also crosses not only a price-base change (2000→2010) but the SNA 1993→2008 methodology break, so pre/post-2011 level comparisons are less reliable than a pure rebase would suggest.

### 7.9 Pre-split aggregate rows double-count

BPS sometimes printed a child district's values before the formal split, marked `#)`; these are flagged `is_pre_split_aggregate == True`. Including them in any district sum double-counts that area's output. Standard practice: `df[df.is_pre_split_aggregate == False]` before any aggregation.

### 7.10 Papua promulgation-date inconsistency in the split concordance

The UU 26/2002 Papua districts appear with two different promulgation dates in the concordance (25 October vs 11 December 2002). The year is correct (2002); only the exact date differs. Impact is limited to analyses that key on the exact law date.

### 7.11 Provisional rows extend to 2025

The 2021–2023 publication carries forward columns for 2024–2025 marked *angka sangat sementara* (very preliminary), flagged `is_provisional == True`. For any analysis not requiring 2024–2025, filter `df.year <= 2023`.

### 7.12 Residual year-misassignment risk for sparse split-off district rows

The parser places a lone value in the first year column when a newly-split district appears with data in only one or two columns; affected pages are re-parsed in vision mode to read column position from the rendered image. Name typos surface in the harmonizer's unmatched-name audit (`harmonize_unmatched.csv`); all cases are resolved via `name_corrections.csv`; the harmonizer reports zero unmatched rows. The residual risk is a typo that coincides exactly with a *different* valid district name, which would match silently to the wrong district. Analysts relying on exact split-year dynamics should verify those rows against the source PDFs; a pre-publication roster-completeness audit found no such collisions. Details in the research log.

### 7.13 Total-vs-per-capita coverage asymmetry

Eight districts appear in only one of the two published panels, reflecting differences in which BPS publications covered total vs. per-capita PDRB.

- **Three Jambi districts** (`JAMBI_BUNGO_TEBO`, `JAMBI_SAROLANGUN_BANGKO`, `JAMBI_TANJUNG_JABUNG`) appear in the total panel only: pre-split parent aggregates (each split c. 1999) present in the 1996–1999 total-PDRB source, for which no contemporaneous per-capita publication exists.
- **Five Papua Barat districts** (`PAPUA_BARAT_KAIMANA`, `PAPUA_BARAT_RAJA_AMPAT`, `PAPUA_BARAT_SORONG_SELATAN`, `PAPUA_BARAT_TELUK_BINTUNI`, `PAPUA_BARAT_TELUK_WONDAMA`) appear in the per-capita panel only: post-2000 splits from Sorong (all 2003), covered by per-capita publications but not by total-PDRB publications for the same years.

Analysts joining the two panels on district key should expect these 8 districts on one side only.

### 7.14 Per-capita panel is not territory-consistent across split years

The 2000-vintage aggregation applies to the total panel only: post-2000 child districts are summed back onto their parent, so a parent's total-PDRB series covers the same territory throughout. Per-capita values are not additive, so the capita panel cannot use the same mechanism; child districts are dropped, and a split parent's per-capita series continues as published by BPS, covering only the rump parent territory after the split.

A silent territory change occurs mid-series wherever a 2000-vintage parent split after 2000. The starkest case is SUMBAWA (NTB): Sumbawa Barat split off in 2003 taking the Batu Hijau copper-gold mine, and Sumbawa's per-capita series drops from 13.7M rupiah (2003, full territory) to 4.7M (2004, rump), a −66% step that is entirely boundary change, not economics. A cross-check of implied population (total ÷ per-capita) flags roughly a hundred such discontinuities, concentrated at pemekaran years; no order-of-magnitude discrepancies appear, and large disagreements fall exactly where boundary changes predict.

The capita `_2000bounds` panel is boundary-consistent for districts that never split, and boundary-consistent *within* the pre-split and post-split segments of districts that did. For analyses requiring a boundary-consistent per-capita series across a split year, either restrict to never-split districts, split the series at the pemekaran year, or construct per-capita as total-panel PDRB divided by an external population series on 2000-vintage boundaries. Population-weighted aggregation of child per-capita values would require a district-level population series on consistent boundaries.

### 7.15 Undetected errors

The correction pass (Section 9) targeted errors we identified during construction: OCR artifacts, confirmed wrong denominators, and BPS source errors with an external cross-check. Errors we did not identify — dropped digits, transposed values, wrong denominators in unchecked provinces — appear in the panel without a warning. The DAPOER cross-check (Section 8) provides the strongest external validation, but it covers only the series and years DAPOER holds and cannot catch errors consistent across both sources. For analyses sensitive to individual cell values, particularly for lightly-covered districts or years with a single source, verify against the source PDFs.

---

## 8. DAPOER Cross-Validation

We cross-validated the panel against the World Bank INDO-DAPOER[^dapoer], which covers 2000–2020 at district level and includes both SNA 1993 real (base 2000) and SNA 2008 real (base 2010) series. The cross-check covers five series: SNA 1993 nominal and real, each including and excluding oil and gas, plus SNA 2008 real. We did not cross-check SNA 2008 nominal, because it shares the same extraction pipeline as the validated series. DAPOER's uniform IDR Million convention makes ×10/×100 discrepancies identifiable as data errors rather than unit mismatches.

3,311 of 3,358 real/2010 district-year comparisons agree within 1%. Of the 47 that do not, the 15 largest (|diff| > 20%) all trace to defects on the DAPOER side, and no panel value was changed.

### Three structural patterns explain all major nominal discrepancies

These are methodological differences, not errors in either source:

1. **DAPOER backdates district splits (2000–2003).** For ~120 districts created 1999–2003, DAPOER applies current (post-split, smaller) boundaries retroactively using sub-district data, whereas we report the historical publication value (the larger pre-split district); the two agree exactly from the year each split first appears in BPS publications. This difference is by design: our panel is built on the 421 districts of the 2000-vintage administrative map; 361 appear in at least one source publication, the remaining 60 in none. Sources reporting more districts (e.g., DAPOER's 548) reflect current boundaries and therefore contain units that do not exist for most of the sample period.
2. **SNA 2008 publication vintage (2011–2013).** DAPOER's SNA 1993 nominal series ends at 2013 with lower values than our panel, which switches to SNA 2008 from 2011. This reflects different accounting methodologies, not a panel error.
3. **Riau/Kepri petroleum attribution (2000–2001).** DAPOER distributes petroleum revenue to post-split districts retroactively; we follow the historical BPS attribution.

### real/2010 cross-check: 15 flagged discrepancies (|diff| > 20%)

Beyond the structural patterns, the real/2010 cross-check flagged 15 residual discrepancies, all DAPOER-side; no panel value was changed. The strongest rest on DAPOER contradicting *itself* — Sorong Kab, Takalar, and Malinau. A second group carries a clean typo signature: Asahan 2013 and Banda Aceh 2016. The weakest cases are where our panel is smooth and DAPOER is not: Halmahera Barat 2020 and the Morowali anomaly, where the evidence is internal consistency, not independent verification against a third source.

**Per-flag mechanisms:**

| Flagged rows | DAPOER defect | Panel evidence |
| --- | --- | --- |
| Sorong Kab 2013–2016 (4), Takalar 2013–2015 (3) | ×100 data-entry error | Panel series smooth and internally consistent; DAPOER/panel ratio is 99.98–100.01 exactly. A ×100 factor would make these districts larger than Jakarta. |
| Malinau 2018–2019 (2) | End-window dropout / corrupt values | Panel 6,972→7,374→7,849→7,808 bn (2017–2020), smooth; DAPOER's 49/52 bn would require +155% single-year growth. |
| Asahan 2013 (1) | Dropped-digit entry error (not a unit error) | Panel 2011–2015: 16,940→17,872→18,893→20,003→21,117 bn, on a steady +5.5–5.9%/yr path, from the same publication as its clean neighbors. Ratio is 9.98, not 10.00: DAPOER's 1,893 is our 18,893 with the "8" dropped. No boundary/Inalum story needed. |
| Banda Aceh 2016 (1) | Dropped-digit entry error | Panel 12,725→13,480→13,937 bn (2015–2017), smooth; same ≈9.98 signature. |
| Halmahera Barat 2020 (1) | ÷10 at end-of-series | Panel 2019–2021: 1,522→1,530→1,548 bn, seamless (confirmed across the 2020–2022 and 2021–2023 publications). DAPOER's 153 bn is exactly panel÷10 at the last year of its SNA-2008 series (dropped trailing digit / stale tail). |
| Morowali 2018–2019 (2) | Stale vintage | Panel 13,364→28,358→34,103→43,902 bn (2017–2020), the genuine nickel boom; DAPOER rejoins our value at 43,902 in 2020, so its own 2019→2020 step would be +155%, impossible. |
| Malang Kota 2013 (1); sub-20% tail 2014/2016/2017 | Reversed block | Panel smooth; DAPOER's 2013 value is exactly our 2017 — the full 2013–2017 block is reversed end-for-end. |

The real/2010 cross-check is complete: 3,311 of 3,358 comparisons agree within 1%, and all 15 residual flags are defects in DAPOER, not the panel. The 32 comparisons in the 1–20% band are also fully explained: three are the Malang Kota reversal tail; Kampar 2018–2019 and Bengkulu Kota 2015/2017 carry the same DAPOER block-defect signature; twenty-one fall in DAPOER's provisional 2018–2020 window and reconverge by series end; four are isolated single-year noise. No panel value is suspect. Per-case detail is in the research log.

**Circularity caveat.** "DAPOER-side" attribution rests on evidence, not an independent source. We never verify DAPOER against a third database, so for those cases the evidence is "consistent with our panel, inconsistent with DAPOER." The first two groups are stronger because they rest on DAPOER's own internal contradictions.

### Province-sum audit notes

Two separate province-sum audits were run. `validate_panel.py` (Stage 6, Check 4) sums district-level data rows within each province-year in the standardized files and compares them to the published province total, producing 21 flags in the final build. All are structural: sparse oil-excluded coverage (only 1–2 districts per province report tanpa-migas figures, so comparisons against the oil-excluded province total are uninformative), Irian Jaya 1996–1999 large negative gaps from the Fakfak nulling (§7.3), and a few provisional-coverage cases (Gorontalo, Bangka-Belitung, Aceh). In Kalimantan Timur, district sums exceed the province total by 5–10% — a genuine BPS accounting convention where district-level oil/gas attribution sums to more than the reconciled province headline.

A broader pre-deduplication audit (`scripts/validate_province_sums.py`, 2026-08-12) flags 842 conditions in the pre-dedup files; every flag traces to a structural artifact — dual-section row duplication, migas-reconciliation conventions, or sparse oil-excluded coverage — and the published panels are unaffected. Province-cluster breakdown is in the research log.

**Overlap revisions.** Check 5 confirmed that the 2020–2022 and 2021–2023 publications printed identical values for the 2021–2022 overlap years: all 2,094 district-year comparison records show revision_pct = 0.0. BPS did not revise any district figures between the two editions. The panel's source-priority rule (§4, Stage 5) uses the 2021–2023 file at those years; because the values are identical, there is no vintage ambiguity at this seam.

---

## 9. Corrections and Provenance

### Tracing any value to its source

Every observation carries `source_file` and `source_priority`. To see what a publication printed before harmonization aggregated child districts, read the corresponding `_native` panel, or the parsed CSV in `parsed_csvs/` (replication package). The parsed CSVs are verbatim transcriptions of the PDF pages and can be diffed directly against `raw/pdf/`. Corrections are applied in Stage 2 to produce `corrected_csvs/` (regenerated at runtime); the sidecar records exactly which cells were modified.

### The correction sidecar

`scripts/apply_corrections.py` (Stage 2) applies the corrections and logs them in `corrections/corrections_applied.csv`. The sidecar records one row per source cell each correction touched, with columns `source_file`, `fix_id` (= `correction_id`), `region_name`, `year`, `table_type`, and `raw_text_hash`, a stable content hash identifying the exact parsed row the fix modified. The sidecar is the authoritative record of what was changed and why.

**How `correction_id` reaches the panel.** The `raw_text_hash` is assigned at parse time and survives into the panel-input files, so `build_panel.py` attaches `correction_id` by joining the sidecar on `(source_file, raw_text_hash)` rather than on district name and year, which would mistag sibling rows that share a name and year but were not corrected. A build-time gate verifies that tagging is exact; some fixes tag zero panel rows (values nulled or superseded by a later publication). Implementation details are in the research log.

`correction_id` is carried on the `_native` panels and the chained panel but not on the aggregated `_2000bounds` panels (Section 5); for those, use the sidecar directly. External source CSVs used for recoveries (W2c, W2/W2b) are in the full project repository (`pipeline_out/full_runs/correction_sources/`), not the replication package.

### Major correction categories

Fix identifiers are stable labels; most follow a mnemonic: `W`-prefixed families correct wrong values (`W2*` for wrong population denominators, `W3*` for digit-level garbles), `P`-prefixed families correct parse- or page-level errors or recover values the parser missed, and the remainder carry descriptive names (`OCR_garble`, `KALTARA_shift`, `FAKFAK_err`). The numbers and letter suffixes distinguish families only; the prefix does not indicate whether an error is BPS-side or pipeline-side; that attribution is stated in each family's description. The list below covers the major families; the authoritative definition of every fix is the correction table in `scripts/apply_corrections.py`, where each entry records the fix identifier, the exact cell, and the bad and corrected values.

- **P7: Kota Bogor nominal 2002–2004.** OCR garbled; values read directly from `PDRB_2002-2004.pdf` p. 71.
- **W2c: Sumatera Barat per-capita 2000–2001.** BPS used a uniform wrong population denominator for all 15 districts; corrected from the BPS Query Builder Seri 2000 export.
- **W2/W2b: Lampung per-capita 2017–2019.** Five districts used wrong population denominators; corrected from the BPS Lampung provincial website (`W2b`). The same source file's 2020–2021 cells for Bandar Lampung and Metro were corrected too (`W2`) but are superseded by later publications and tag zero panel rows.
- **W3 series: digit garbles.** Banjarmasin 1997 real (scan-shadow artifact); Kampar real (BPS source error, nulled); Sambas per-capita 1996–1999 (÷10 denominator error); Sumenep real/1993 1996 (dropped period); Mamuju real/1993 1999 (spike, nulled).
- **OCR garbles.** Eight additional corrections for stray characters producing non-parseable values.
- **BPS source errors (nulled).** Barru 1998 nominal/per-capita and Mamuju 1999 real: confirmed BPS source errors, not pipeline artifacts.
- **KALTARA_shift: Kalimantan Utara per-capita 2011–2013, four districts (25 corrections).** The PDF parser merged BPS Tabel 160 (Kalimantan Utara) into the preceding Tabel 159 (Kalimantan Timur) and shifted the Kaltara rows one year-column left. Content-keyed corrections restore Bulungan, Malinau, Nunukan, and Tarakan per-capita values to their printed year columns (verified against the source PDF).

143 corrections (22 fix families across 9 source files) produce 166 sidecar rows in `corrections_applied.csv`; corrections touching both nominal and real cells for the same district-year produce multiple rows, so 143 is the logical-fix count and 166 the cell count.

### Scope of the correction pass

The 143 corrections address errors that were identified and verified during construction. The correction pass does not guarantee the absence of undetected errors: BPS source errors that were never flagged (dropped digits, transposed values, wrong denominators in provinces not cross-checked) will appear in the panel without a `correction_id`. For cell-sensitive analyses, verify in `parsed_csvs/` and, if needed, the source PDF.

---

## Errata and contact

We welcome inquiries, extensions, corrections, and additional evidence, especially from users with access to BPS regional publications. Attributions of source anomalies (Fakfak 1996–1999, DAPOER-side classifications in Section 8) rest on available evidence. The project repository is at <https://github.com/nayfajo/indonesia-subnational-gdp>.

---

*End of codebook.*
