#!/usr/bin/env python3
"""
make_package.py — assemble a self-contained replication/ folder.

Collects everything a third party needs to reproduce the PDRB panel from the
parsed stage-1 CSVs: the final panels, the data guide, the crosswalks, the
correction sidecar, the 21 parsed CSVs (reproducibility anchor), the active
scripts, the raw PDFs, run_all.sh, and a generated README with run order.

Package layout (flattened from the working tree):
    replication/
      outputs/        — the five canonical panels (+ checksums after a run)
      docs/           — data_guide.md + data_guide.pdf (full reference, includes Quick Start)
      crosswalks/     — reference / concordance tables
      corrections/    — corrections_applied.csv sidecar
      parsed_csvs/    — the 21 parsed stage-1 CSVs (reproducibility anchor)
      raw/pdf/
        originals/    — 11 original BPS publications
        split/        — 21 manually extracted pipeline-input PDFs
      scripts/        — the pipeline and helper scripts (archive/ excluded)
      run_all.sh
      README.md

Deliberately EXCLUDES: pipeline_out/ intermediates (standardized/, harmonized/,
audits/), logs/, scripts/archive/, the docs/ xlsx audit workbooks, and the
docx copies of the notes.

Usage:
    python scripts/make_package.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Run from project root regardless of cwd.
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "replication"

# Working-tree location of the raw PDFs. Physically split into split/ and
# originals/ to mirror the package layout exactly (renamed from the old
# "new full set/" + "new full set/Raw/" 2026-09-23, which also moved the one
# national PDRB_1998-2001.pdf — previously special-cased as living outside
# Raw/ but belonging with the originals — into originals/ directly).
PDF_SRC = ROOT / "raw" / "pdf" / "sources"

# ---------------------------------------------------------------------------
# What goes in.
# ---------------------------------------------------------------------------

# (src_relative_to_ROOT, dest_relative_to_DEST)
FILES = [
    ("outputs/panel_pdrb_total_2000bounds.csv",    "outputs/panel_pdrb_total_2000bounds.csv"),
    ("outputs/panel_pdrb_capita_2000bounds.csv",   "outputs/panel_pdrb_capita_2000bounds.csv"),
    ("outputs/panel_pdrb_chained_2000bounds.csv",     "outputs/panel_pdrb_chained_2000bounds.csv"),
    ("outputs/panel_pdrb_total_native.csv",  "outputs/panel_pdrb_total_native.csv"),
    ("outputs/panel_pdrb_capita_native.csv", "outputs/panel_pdrb_capita_native.csv"),
    ("docs/data_guide.md",  "docs/data_guide.md"),
    ("docs/data_guide.pdf", "docs/data_guide.pdf"),
    ("corrections/corrections_applied.csv",
     "corrections/corrections_applied.csv"),
    # run_all.sh is handled specially (path references rewritten) below.
]

# Whole directories: (src_dir, dest_dir). Copied recursively.
DIRS = [
    ("crosswalks", "crosswalks"),
    # The 21 parsed stage-1 CSVs, flattened to the top level.
    ("pipeline_out/full_runs/csvs", "parsed_csvs"),
    # DAPOER extract used by scripts/dapoer_crosscheck.py (data guide Section 8).
    ("dapoer_extract", "dapoer_extract"),
]

# scripts/ is special: copy every top-level *.py but skip the archive/ subdir.
SCRIPTS_SRC = ROOT / "scripts"
SCRIPTS_DEST = DEST / "scripts"

# Scripts explicitly excluded from the package even if present at scripts/ top
# level. These are one-off audit/crosscheck tools that now live in
# scripts/archive/ and are not part of the reproducible pipeline.
SCRIPTS_EXCLUDE = {
    "validate_province_sums.py",
    # Post-processes docs/data_guide.pdf's accessibility tagging after a
    # `typst compile` (see CONTRIBUTING.md). Real, current, and tracked on
    # GitHub, but it's about maintaining the data guide itself, not about
    # reproducing the panel -- doesn't belong in a data-reproduction package.
    "fix_footnote_reference_tags.py",
}

# Junk we never want to carry along.
IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "~$*")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _dir_stats(path: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) under a directory (recursive)."""
    n = size = 0
    for p in path.rglob("*"):
        if p.is_file():
            n += 1
            size += p.stat().st_size
    return n, size


def _human(nbytes: int) -> str:
    val = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} GB"


def _copy_pdfs(missing: list[str]) -> tuple[int, int]:
    """Copy the raw PDFs into originals/ and split/ in the package.

    Both are physical subfolders of PDF_SRC (raw/pdf/sources/), a 1:1 mirror
    of the package's own raw/pdf/originals/ and raw/pdf/split/.

    Returns (n_originals, n_split).
    """
    orig_dest = DEST / "raw" / "pdf" / "originals"
    split_dest = DEST / "raw" / "pdf" / "split"
    orig_dest.mkdir(parents=True, exist_ok=True)
    split_dest.mkdir(parents=True, exist_ok=True)

    if not PDF_SRC.exists():
        missing.append(str(PDF_SRC.relative_to(ROOT)) + "/")
        return 0, 0

    n_orig = n_split = 0

    orig_sub = PDF_SRC / "originals"
    if orig_sub.exists():
        for pdf in sorted(orig_sub.glob("*.pdf")):
            shutil.copy2(pdf, orig_dest / pdf.name)
            n_orig += 1
    else:
        missing.append(str(orig_sub.relative_to(ROOT)) + "/")

    split_sub = PDF_SRC / "split"
    if split_sub.exists():
        for pdf in sorted(split_sub.glob("*.pdf")):
            shutil.copy2(pdf, split_dest / pdf.name)
            n_split += 1
    else:
        missing.append(str(split_sub.relative_to(ROOT)) + "/")

    return n_orig, n_split


# Working-tree -> package path rewrites applied to every copied script.
# The package ships the parsed stage-1 CSVs in parsed_csvs/ (flattened) and the
# correction sidecar in corrections/, so any script that reads/writes those
# working-tree locations must be repointed. apply_corrections.py reads
# parsed_csvs/ and writes corrected copies to corrected_csvs/ (package root);
# standardize_pipeline.py then reads corrected_csvs/.
#
# Order matters: rewrite the longer/more-specific paths first so a shorter
# prefix cannot partially match inside a longer one.
_SCRIPT_PATH_REWRITES = (
    ("pipeline_out/full_runs/corrected_csvs", "corrected_csvs"),
    ("pipeline_out/full_runs/csvs", "parsed_csvs"),
)


def _patch_script_paths(text: str) -> str:
    """Rewrite working-tree paths in a script's source for the package layout."""
    for old, new in _SCRIPT_PATH_REWRITES:
        text = text.replace(old, new)
    return text


def _copy_script(src: Path, dst: Path) -> None:
    """Copy a script into the package, rewriting working-tree paths.

    make_package.py is copied verbatim: it is a build tool, not part of the
    reproducible pipeline, and its own source/dest path table must keep
    referencing the working-tree layout.
    """
    if src.name == "make_package.py":
        shutil.copy2(src, dst)
        return
    text = _patch_script_paths(src.read_text(encoding="utf-8"))
    dst.write_text(text, encoding="utf-8")
    shutil.copystat(src, dst)


def _copy_run_all() -> None:
    """Copy run_all.sh into the package, rewriting working-tree paths.

    The shipped package stores the parsed CSVs in parsed_csvs/, so rewrite the
    references the source script makes to their working-tree locations.
    """
    src = ROOT / "run_all.sh"
    if not src.exists():
        return
    text = _patch_script_paths(src.read_text(encoding="utf-8"))
    dst = DEST / "run_all.sh"
    dst.write_text(text, encoding="utf-8")
    dst.chmod(0o755)


README = """\
# Subnational GDP for Indonesia: A District-Level Panel — Replication Package

A district-level (subnational) GDP panel for Indonesia, 1996–2025, assembled
from BPS regional GDP (PDRB) publications. This package reproduces the panel
from the parsed stage-1 CSVs.

## Requirements

Python 3.11+. See `requirements.txt` for package versions.

## Contents

- `outputs/` — the five canonical panel files:
  - `panel_pdrb_total_2000bounds.csv`    — total PDRB, main panel
  - `panel_pdrb_capita_2000bounds.csv`   — per-capita PDRB, main panel
  - `panel_pdrb_chained_2000bounds.csv`     — chain-linked real total series
  - `panel_pdrb_total_native.csv`  — total PDRB, full (all overlaps retained)
  - `panel_pdrb_capita_native.csv` — per-capita PDRB, full
  - `checksums.sha256`           — written by run_all.sh after a successful run
- `docs/data_guide.md` — the data guide: Quick Start, column definitions, all pipeline stages,
  limitations, correction categories, and the detailed DAPOER validation. Start here.
- `crosswalks/` — 8 files: `district_reference.csv` (canonical district
  list), `province_crosswalk.csv`, `name_corrections.csv`,
  `split_concordance.csv` (pemekaran parent/child map), `bps_code_reference.csv`,
  and three external cross-check references on administrative splits (a
  RISED CSV, a Kemendagri registry CSV, and a compiled .docx table).
  See the data guide's "Crosswalk file reference" for a column-by-column
  breakdown of every file.
- `dapoer_extract/` — the World Bank INDO-DAPOER extract used for the
  cross-validation in data guide Section 8 (two files: indicator values and
  indicator metadata). See the data guide's "DAPOER extract file reference".
- `corrections/corrections_applied.csv` — sidecar log of hand-verified
  corrections applied to the parsed CSVs.
- `parsed_csvs/` — the 21 parsed stage-1 CSVs (all 143 hand-verified
  corrections already applied in place). These are the
  reproducibility anchor: output of the (paid, vision-API) PDF parsing stage
  and the input to `run_all.sh`. See the data guide's "Parsed CSV schema" for
  column definitions and two known, documented data-quality notes (an inert
  header-text typo and duplicate rows from resumed parsing runs).
- `scripts/` — the pipeline and helper scripts (archive/ excluded), including
  `dapoer_crosscheck.py`, which reproduces the DAPOER cross-validation in
  data guide Section 8 from the World Bank extract shipped in `dapoer_extract/`.
- `raw/pdf/` — the source BPS PDF publications (see Provenance below).
- `run_all.sh` — chains the pipeline stages and writes output checksums.

## Citation

> Johan, Nayfa and Russell Hillberry (2026). *Subnational GDP for Indonesia:
> A District-Level Panel, 1996–2025.* Purdue University Research Repository
> (PURR). https://doi.org/10.4231/FWEQ-VE94

Licensing terms are set on the PURR deposit record.

## Provenance of the raw PDFs

### `raw/pdf/originals/` — 11 curated BPS publication extracts + 1 provenance document

Each BPS publication in this series runs to several hundred pages covering many
statistical topics; these 11 files are the PDRB-relevant pages selected out of
each one (exported page-range PDFs, not the full multi-topic volumes). Ten
cover the district/municipality PDRB series; the eleventh (`PDRB_1998-2001.pdf`)
is from the national 1998–2001 PDRB publication.

The ten series files carry a `NN-NN_` filename prefix. That prefix records the
**non-provisional year coverage** actually extracted from each publication —
i.e. the year range whose figures were used downstream — which differs from the
full nominal span printed on the publication cover. The files are:

| Prefix  | BPS publication (title span)                                                          | Years extracted |
|---------|----------------------------------------------------------------------------------------|-----------------|
| `96-99` | Produk Domestik Regional Bruto (PDRB) Kabupaten/Kota di Indonesia 1996–1999           | 1996–1999       |
| `00-01` | Produk Domestik Regional Bruto (PDRB) Kabupaten/Kota di Indonesia 2000–2003           | 2000–2001       |
| `02-04` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2002–2006                   | 2002–2004       |
| `05-07` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2005–2009                   | 2005–2007       |
| `08-10` | Gross Regional Domestic Product of Regencies/Municipalities in Indonesia 2008–2012      | 2008–2010       |
| `11-13` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2011–2015                   | 2011–2013       |
| `14-16` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2014–2018                   | 2014–2016       |
| `17-19` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2017–2021                   | 2017–2019       |
| `20-22` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2020–2024                   | 2020–2022       |
| `21-23` | Produk Domestik Regional Bruto Kabupaten/Kota di Indonesia 2021–2025                   | 2021–2023       |

Note: the `08-10` publication is the **BPS English edition**, titled
"Gross Regional Domestic Product of Regencies/Municipalities in Indonesia
2008-2012". All other originals are the Indonesian-language editions.

**Republication permission.** `originals/` also includes `Term of Use -
BPS-Statistics Indonesia.pdf`, a saved copy of BPS's Terms of Use page
(bps.go.id/en/term-of-use, accessed September 2026), kept here as dated
documentary evidence rather than a link that could change or disappear.
Clause 13 grants content "free of charge, worldwide, on a continuous and
non-exclusive basis" for, among other purposes, "using the data for both
commercial and non-commercial purposes" and "copying, distributing, and/or
transmitting the content," conditional on lawful use, proper citation (title,
access date, and a link to the original — provided in the table above and
footnote 1 of the data guide), and accepting that BPS content may change or
be withdrawn. These pages are republished on that basis for reproducibility.

**On the raw PDFs' form.** These are the extracted pages, not touched-up
copies — no re-typesetting, no OCR cleanup, no accessibility remediation.
Most were produced as page-range exports (macOS Preview's PDF export; several
carry a "Quartz PDFContext" producer tag as a result), so they are not
byte-identical copies of BPS's own files, but they are visually and textually
faithful to the pages as BPS printed them — what verifying a panel figure
against source actually requires. Accessibility and general usability live
in the derived data instead: `outputs/` and `parsed_csvs/` are plain,
machine-readable text.

### `raw/pdf/split/` — 21 manually extracted pipeline-input PDFs

These are the PDRB and PDRB-per-capita tables manually extracted from the
`originals/` above, named by their non-provisional year coverage
(e.g. `PDRB_2005-2007.pdf`, `PDRB-capita_2005-2007.pdf`). They are the direct
input to the PDF parsing stage.

### `parsed_csvs/` — parsed stage-1 outputs

The 21 CSVs in `parsed_csvs/` are the pipeline's stage-1 outputs, parsed from
the split PDFs in `raw/pdf/split/`. They are the **reproducibility anchor**: the
PDF parsing step relies on a paid vision API and is therefore **not re-run by
`run_all.sh`**. The parsed CSVs are shipped directly and are the input to the
reproducible pipeline. See `docs/data_guide.md` for the parsing methodology.

All 143 hand-verified corrections are already applied in-place to the shipped
CSVs. `apply_corrections.py` re-verifies every correction with 3-state logic —
apply if the bad value is present, skip/verify if already correct, hard-fail if
neither — and writes the result to `corrected_csvs/`, which
`standardize_pipeline.py` reads. On a fresh run against these shipped files the
expected output is **143 skipped (verified), 0 applied, 0 failed**.
`corrected_csvs/` is regenerated by `run_all.sh` and is not shipped.

## How to reproduce

From this directory:

```bash
bash run_all.sh
```

This runs, in order:

1. `apply_corrections.py`    — verify/apply hand-verified corrections; reads parsed_csvs/, writes corrected_csvs/ (expect: 143 skipped, 0 applied, 0 failed)
2. `standardize_pipeline.py` — standardize all 21 files from corrected_csvs/ (wide -> long)
3. `harmonize_regions.py`    — harmonize region names/codes vs crosswalks
4. `build_panel.py`          — build the four panels
5. `chain_link.py`           — chain-link the real total series
6. `validate_panel.py`       — QA checks

On success it writes `outputs/checksums.sha256`. Compare against the shipped
values to confirm a byte-identical reproduction.

## Extending the panel

The pipeline is designed so that a new BPS publication (typically released each July) can be added with moderate effort:

1. **Parse the new PDF.** Use `scripts/parse_pdfs_text.py` for digital PDFs (and `reparse_pages_vision.py` for image-only pages). This requires your own Claude API key — the parse step is not automated by `run_all.sh` because it calls a paid vision API.
2. **Register the new source file.** Add it to `SOURCE_PRIORITY`, `TOTAL_FILES` or `CAPITA_FILES` in `scripts/build_panel.py` with the next integer priority rank (higher = later publication wins). See `CONTRIBUTING.md` for details.
3. **Update the crosswalks.** If BPS created new districts or provinces since the last update, add rows to `crosswalks/split_concordance.csv` and `crosswalks/district_reference.csv`. This is a live issue: the 2022 Papua *pemekaran* created several new provinces not reflected in the current concordance.

Steps 2–3 require familiarity with the pipeline conventions described in `docs/data_guide.md`. Questions and contributions welcome via the project repository: https://github.com/nayfajo/indonesia-subnational-gdp.
"""


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"Project root: {ROOT}")
    print(f"Destination : {DEST}")

    # Clear/create destination.
    if DEST.exists():
        print("Clearing existing replication/ ...")
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    missing: list[str] = []

    # Individual files.
    for src_rel, dst_rel in FILES:
        src = ROOT / src_rel
        if not src.exists():
            missing.append(src_rel)
            continue
        _copy_file(src, DEST / dst_rel)

    # Directories.
    for src_rel, dst_rel in DIRS:
        src = ROOT / src_rel
        if not src.exists():
            missing.append(src_rel + "/")
            continue
        shutil.copytree(src, DEST / dst_rel, ignore=IGNORE, dirs_exist_ok=True)

    # raw/pdf/ — split into originals/ and split/.
    n_orig, n_split = _copy_pdfs(missing)
    print(f"Copied raw PDFs: {n_orig} originals, {n_split} split.")

    # run_all.sh — copy with working-tree paths rewritten for the package.
    _copy_run_all()

    # scripts/ — top-level *.py only, excluding archive/.
    SCRIPTS_DEST.mkdir(parents=True, exist_ok=True)
    n_scripts = 0
    for py in sorted(SCRIPTS_SRC.glob("*.py")):
        if py.name in SCRIPTS_EXCLUDE:
            continue
        _copy_script(py, SCRIPTS_DEST / py.name)
        n_scripts += 1
    print(f"Copied {n_scripts} active scripts (scripts/archive/ excluded).")

    # README.
    (DEST / "README.md").write_text(README, encoding="utf-8")

    # Prune any stray junk that slipped through copytree.
    for junk in DEST.rglob(".DS_Store"):
        junk.unlink()
    for pyc in DEST.rglob("__pycache__"):
        if pyc.is_dir():
            shutil.rmtree(pyc, ignore_errors=True)

    if missing:
        print("\nWARNING — the following expected sources were missing:")
        for m in missing:
            print(f"  - {m}")

    # ---- Manifest ----
    print("\n" + "=" * 66)
    print("  MANIFEST — replication/")
    print("=" * 66)
    print(f"  {'subdirectory':<34}{'files':>8}{'size':>14}")
    print("  " + "-" * 62)

    subdirs = sorted(p for p in DEST.iterdir() if p.is_dir())
    grand_n = grand_size = 0
    for d in subdirs:
        n, size = _dir_stats(d)
        grand_n += n
        grand_size += size
        print(f"  {d.name + '/':<34}{n:>8}{_human(size):>14}")

    # Top-level loose files.
    top_files = [p for p in DEST.iterdir() if p.is_file()]
    if top_files:
        tn = len(top_files)
        ts = sum(p.stat().st_size for p in top_files)
        grand_n += tn
        grand_size += ts
        print(f"  {'(top-level files)':<34}{tn:>8}{_human(ts):>14}")

    print("  " + "-" * 62)
    print(f"  {'TOTAL':<34}{grand_n:>8}{_human(grand_size):>14}")
    print("=" * 66)
    print(f"\nReplication package assembled at: {DEST}")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
