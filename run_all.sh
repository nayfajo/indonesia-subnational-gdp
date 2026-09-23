#!/usr/bin/env bash
#
# run_all.sh — reproduce the PDRB panel from the parsed stage-1 CSVs.
#
# This chains the post-parse pipeline stages in order and, on success,
# writes SHA-256 checksums of the five canonical output panels.
#
# It does NOT re-run the PDF parsing stage (parse_pdfs_text.py, parse_pdfs_scan.py). Those
# scripts require a paid vision API and their output — the 21 CSVs in
# pipeline_out/full_runs/csvs/ — is shipped as the reproducibility anchor.
# See docs/data_guide.md for the parsing methodology.
#
# Usage:
#   bash run_all.sh
#
# Exits non-zero if any stage fails.

set -euo pipefail

# --- locate project root (directory of this script) ---
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- pick a Python interpreter ---
if [[ -x ".venv/bin/python3.14" ]]; then
  PY=".venv/bin/python3.14"
elif [[ -x ".venv/bin/python3" ]]; then
  PY=".venv/bin/python3"
else
  PY="python3"
fi
echo "Using interpreter: $PY"
echo "Project root:      $ROOT"

# --- helper: announce and run a stage ---
stage() {
  local name="$1"; shift
  echo ""
  echo "=================================================================="
  echo "  STAGE: $name"
  echo "=================================================================="
  "$@"
}

# --- pipeline stages, in order ---------------------------------------------
# Flow: parsed_csvs/ -> apply_corrections -> corrected_csvs/ -> standardize -> ...
#
# Stage 2. Apply hand-verified corrections to the parsed stage-1 CSVs, reading from
#    csvs/ and writing corrected copies to corrected_csvs/ (originals left
#    untouched), plus a sidecar log of what was changed.
stage "2  apply_corrections   (csvs/ -> corrected_csvs/ + sidecar)" \
  "$PY" scripts/apply_corrections.py

# Stage 3. Standardize all 21 corrected CSVs from corrected_csvs/ (wide -> long, clean values).
stage "3  standardize_pipeline (corrected_csvs/ -> pipeline_out/standardized/)" \
  "$PY" scripts/standardize_pipeline.py

# Stage 4. Harmonize region names / codes against the crosswalks.
stage "4  harmonize_regions    (-> pipeline_out/harmonized/)" \
  "$PY" scripts/harmonize_regions.py

# Stage 5. Build the panels (writes total_2000bounds, total_native, capita_2000bounds, capita_native).
stage "5  build_panel          (-> outputs/panel_pdrb_*_2000bounds.csv, *_native.csv)" \
  "$PY" scripts/build_panel.py

# Stage 6. Chain-link the real total series (-> panel_pdrb_chained_2000bounds.csv).
stage "6  chain_link           (-> outputs/panel_pdrb_chained_2000bounds.csv)" \
  "$PY" scripts/chain_link.py

# Stage 7. Validate the panels (QA reports -> pipeline_out/audits/).
stage "7  validate_panel       (QA; non-zero exit on FAIL checks)" \
  "$PY" scripts/validate_panel.py

# --- checksums of the five canonical outputs -------------------------------
echo ""
echo "=================================================================="
echo "  CHECKSUMS: outputs/checksums.sha256"
echo "=================================================================="

CANONICAL=(
  "outputs/panel_pdrb_total_2000bounds.csv"
  "outputs/panel_pdrb_capita_2000bounds.csv"
  "outputs/panel_pdrb_chained_2000bounds.csv"
  "outputs/panel_pdrb_total_native.csv"
  "outputs/panel_pdrb_capita_native.csv"
)

# Prefer sha256sum; fall back to shasum -a 256 (macOS default).
if command -v sha256sum >/dev/null 2>&1; then
  SHA_CMD=(sha256sum)
else
  SHA_CMD=(shasum -a 256)
fi

"${SHA_CMD[@]}" "${CANONICAL[@]}" > outputs/checksums.sha256
cat outputs/checksums.sha256

echo ""
echo "=================================================================="
echo "  DONE — all stages completed successfully."
echo "=================================================================="
