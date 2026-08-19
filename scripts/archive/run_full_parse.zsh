#!/usr/bin/env zsh
# Full parse run — all 20 PDFs.
# Usage:
#   zsh run_full_parse.zsh            # fresh run
#   zsh run_full_parse.zsh --resume   # pick up after interruption

PDF_DIR="raw/pdf/new full set"
OUT="pipeline_out/full_runs"
PY=".venv/bin/python3.14"

RESUME_FLAG=()
if [[ "$1" == "--resume" ]]; then
  RESUME_FLAG=(--resume)
fi

FAILED=()

run_pdf() {
  local script=$1 pdf=$2
  shift 2
  echo "\n=========================================="
  echo "  $pdf"
  echo "=========================================="
  $PY "scripts/$script" \
    --input "$PDF_DIR/${pdf}.pdf" \
    --output "$OUT" \
    --debug \
    "$@" "${RESUME_FLAG[@]}" || FAILED+=("$pdf")
}

# ── Group A (1996-1999, vision/scan) ──────────────────────────────────────────
# PDRB_1996-1999 was already parsed and its CSV saved before this script was
# finalized. Re-running it here would append duplicate rows to that CSV.
# Uncomment to include it in a full replication run from scratch (delete the
# existing CSV first).
# run_pdf parse_pdrb_wide_a.py  PDRB_1996-1999
run_pdf parse_pdrb_wide_a.py  PDRB-capita_1996-1999

# ── Groups B + C ──────────────────────────────────────────────────────────────
run_pdf parse_pdrb_wide_v2.py PDRB_2000-2001
run_pdf parse_pdrb_wide_v2.py PDRB_2002-2004
run_pdf parse_pdrb_wide_v2.py PDRB_2005-2007
run_pdf parse_pdrb_wide_v2.py PDRB_2008-2010
run_pdf parse_pdrb_wide_v2.py PDRB_2011-2013
run_pdf parse_pdrb_wide_v2.py PDRB_2014-2016
run_pdf parse_pdrb_wide_v2.py PDRB_2017-2019
run_pdf parse_pdrb_wide_v2.py PDRB_2020-2022
run_pdf parse_pdrb_wide_v2.py PDRB_2021-2023
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2000-2001
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2002-2004
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2005-2007
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2008-2010
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2011-2013
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2014-2016
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2017-2019
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2020-2022
run_pdf parse_pdrb_wide_v2.py PDRB-capita_2021-2023

# ── Summary ───────────────────────────────────────────────────────────────────
echo "\n=========================================="
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo "  All 20 PDFs completed."
else
  echo "  Completed with ${#FAILED[@]} failure(s):"
  for f in "${FAILED[@]}"; do echo "    - $f"; done
  echo "  Re-run with --resume to retry failed PDFs."
fi
echo "=========================================="
