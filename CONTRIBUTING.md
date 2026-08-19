# Contributing and Maintenance Guide

This guide covers how the repository is organized, how to reproduce or extend the dataset, and the conventions used for corrections and crosswalk updates. It is written for a future maintainer — someone who wants to add a new BPS publication, fix a data error, or understand what each script does.

## Repository layout

```
indonesia-subnational-gdp/
  outputs/                — five canonical panel CSVs (the deliverables)
  docs/                   — codebook.md, research_log.md
  crosswalks/             — district_reference.csv, province_crosswalk.csv,
                            split_concordance.csv, name_corrections.csv
  scripts/                — the full pipeline
  pipeline_out/           — generated intermediate outputs (gitignored)
    full_runs/
      csvs/               — the 21 parsed stage-1 CSVs (tracked; reproducibility anchor)
      corrected_csvs/     — after apply_corrections.py (generated)
      corrections_applied.csv — sidecar log of applied corrections
  raw/                    — source PDFs (gitignored; live in the PURR deposit)
  corrections/            — symlink / copy of corrections_applied.csv for the package
  archive/                — superseded drafts and one-off audit tools (gitignored)
  replication/            — generated replication package (gitignored)
```

The 21 parsed CSVs in `pipeline_out/full_runs/csvs/` are the reproducibility anchor: they represent the verbatim parse output (paid vision API) and are tracked in git. Everything downstream is regenerable by running `bash run_all.sh`.

## Environment

Python 3.11+ with pandas, numpy, scipy, and openpyxl. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas numpy scipy openpyxl
```

## Pipeline run order

Running `bash run_all.sh` chains all post-parse stages in order:

| Stage | Script | Input → Output |
|---|---|---|
| 2 | `apply_corrections.py` | `csvs/` → `corrected_csvs/` + sidecar |
| 3 | `standardize_pipeline.py` | `corrected_csvs/` → `pipeline_out/standardized/` |
| 4 | `harmonize_regions.py` | `standardized/` → `pipeline_out/harmonized/` |
| 5 | `build_panel.py` | `harmonized/` → `outputs/panel_pdrb_*.csv` |
| 6 | `chain_link.py` | total panel → `outputs/panel_pdrb_chained_2000bounds.csv` |
| 7 | `validate_panel.py` | all outputs → `pipeline_out/audits/` (QA reports) |

Stage 1 (PDF parse: `parse_pdfs_text.py`, `parse_pdfs_scan.py`, `reparse_pages_vision.py`) is not included in `run_all.sh` because it requires a paid vision API. The parsed CSVs are pre-shipped.

## Adding a new BPS publication

When BPS releases a new rolling window (e.g., a 2023–2025 volume that supersedes the current provisional data), the steps are:

1. **Parse the PDF.** Run `parse_pdfs_text.py` on the new PDF (or `reparse_pages_vision.py` for image-only pages). Place the output CSV in `pipeline_out/full_runs/csvs/`. Follow the existing naming convention: `PDRB_YYYY-YYYY.csv` (total) or `PDRB-capita_YYYY-YYYY.csv` (per-capita).

2. **Register the file in `build_panel.py`.** Add the filename to `SOURCE_PRIORITY` (assign the next integer priority; higher = later publication wins) and to either `TOTAL_FILES` or `CAPITA_FILES`.

3. **Add crosswalk entries for new districts.** If new districts appear (new *pemekaran* splits), add them to `crosswalks/district_reference.csv` with a stable `district_id`, and update `crosswalks/split_concordance.csv` to map child → parent. If BPS introduced new provinces, update `crosswalks/province_crosswalk.csv`.

4. **Run the pipeline.** `bash run_all.sh`. Check `pipeline_out/audits/` for QA flags. Expect the validate stage to flag any unmatched districts.

5. **Update documentation.** In `docs/codebook.md`, extend the source table (Table 1 or 2) to include the new publication and update the year ranges in Table 3.

## Adding or correcting a correction

Corrections are defined inline in `scripts/apply_corrections.py` in the `CORRECTIONS_BY_FILE` dict. Each entry specifies:

- `fix_id` — a stable mnemonic shared by all cells of the same fix family (e.g., `FAKFAK_err`, `KALTARA_shift`)
- `province`, `district`, `year` — the address of the cell in the parsed CSV
- `bad` — the exact raw string to match (content-keyed; the fix is skipped if the cell no longer contains this string)
- `good` — the corrected value, or `None` to suppress (drop) the cell

To add a new correction: identify the fix type (`fix_cell` for a value replacement, `fix_flag` for a boolean flag), add an entry under the correct source filename in `CORRECTIONS_BY_FILE`, and run `python scripts/apply_corrections.py --dry-run` first to confirm it matches. After a real run, inspect the sidecar (`pipeline_out/full_runs/corrections_applied.csv`) to confirm the fix was applied.

Corrections that delete rows (`good=None`) are appropriate for values confirmed to be BPS print errors. Corrections that substitute a recovered value should cite the recovery source in a comment on the entry (e.g., `# from BPS Query Builder export, 2025-08`).

## Known deferred items

These are issues that were identified but not resolved as of the initial deposit. A future maintainer should be aware of them:

- **`_2000bounds` correction attribution.** The `correction_id` column is carried through the `_native` and chained panels but not the aggregated `_2000bounds` panels (aggregation disrupts one-to-one mapping). To trace whether a `_2000bounds` cell was affected by a correction, cross-reference the sidecar (`corrections/corrections_applied.csv`) by source file, district, and year.

- **`is_pre_split_aggregate` coverage.** The flag marks BPS "pre-split aggregate" sub-rows (marked `#)` in BPS publications) that double-count into their parent. These have been identified for known cases, but coverage may be incomplete for later publications where the sub-row convention is inconsistently applied.

- **Chain-linking drift flags.** `ratio_drift_flag == True` marks 10 districts whose 2000-to-2010-price backcasts have drifted ratios. These are logged in `pipeline_out/audits/` after a run. No action was taken; users should treat those districts' chained levels with extra caution.

- **Per-capita `_2000bounds` conceptual limitation.** The 2000-vintage aggregation applies to the total panel but not the per-capita panel (per-capita values are not additive). After a district split, the per-capita `_2000bounds` series reflects the rump territory only. For a boundary-consistent per-capita series, divide total-panel PDRB by an external population series.

- **Provisional data.** The `PDRB_2021-2023` and `PDRB-capita_2021-2023` publications extend to 2025 via BPS's *angka sementara* (preliminary) figures. These should be revisited when BPS releases a revised or finalized publication.
