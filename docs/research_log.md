# Research Log — Indonesian District PDRB Panel (1996–2025)

This file is an internal record of design decisions, key findings, and non-obvious choices made
during construction of the panel. It is not a user guide; the user-facing reference is
`docs/data_guide.md`. It replaces several large raw session logs that have been archived to
`archive/superseded_docs/`. Dates are formatted YYYY-MM-DD and refer to the working session in
which a decision was made or a finding was confirmed.

---

## 1. Parsing Methodology

### PDF groups and parser variants

The 21 BPS source PDFs fall into three structural groups that required different parsing
strategies.

Group C covers the 2008–2022 publications. These are digitally produced, with inline text and
no comma-decimal collision. `parse_pdfs_text.py` handles all of them using pdfplumber text
extraction feeding a Claude Sonnet API call at temperature=0, then Python-side wide-to-long
melting. This is the baseline parser. All design decisions (pipe delimiter, province name in the
HEADERS section, temperature=0, verbatim value capture) were validated by running 20-page
spot-checks against 2018–2022 and 2013–2017 before the full run was committed. The 2008–2012
spot-check returned only three of the five year columns in 20 pages, which was expected because
the 20-page limit does not cover the full year range; the full run captured all years correctly.

Group B covers the 2000–2003 and 2003–2007 publications. Initial spot-checks showed "numeric"
values in the province_name column (e.g. `138.801`, `3.016`). These are digitally produced PDFs,
not scanned, despite the visual resemblance of the column misassignment to scan artifacts. The
root cause is that both PDFs use the comma as the decimal separator: `138.801,52` (meaning
138,801.52 rupiah). Claude's comma-delimited CSV output split that value at the comma, placing
`138.801` in the province_name column and `52` in the regency_code column, shifting every
subsequent column right. The fix was to switch to pipe-delimited output and to extract
province_name from the table header, which is where these publications place it rather than in
each district row. The group B handling (originally in `parse_pdrb_wide_b.py`) was merged into
`parse_pdfs_text.py`, which is now the single production parser for all non-Group-A files.

Group A covers the 1996–1999 publication, a physically scanned document that had BPS's OCR
watermarking process run twice. The effect is that every character appears doubled in the PDF
encoding (`PPDDRRBBB` for `PDRB`). pdfplumber extracts the doubled bytes regardless of how the
doubling occurred; any text extractor would see the same thing. Additionally, the scan tilt
causes pdfplumber to extract district names on one line and their year values staggered on lines
below, making column assignment unreliable. Text-mode deduplication of the doubled characters did not fix the staggered layout problem (Run 2b, 2026-07-13); vision mode was the correct approach.

`parse_pdfs_scan.py` forces vision mode (sending rendered page images to the Claude API) and
adds one prompt instruction: district names appear on one visual line and their year values are
staggered below; treat these as a single row. This script was validated by comparing output
against the original web-chat-parsed CSV in `raw/parsed/claude/`, which served as ground truth.
The comparison found zero rows in the web-chat CSV that the new script missed. Banda Aceh
nominal 1996 = 526,832.87 in both sources.

A fourth parsing path, vision mode triggered by the `is_text_pdf()` density check, handles the
2005–2007 publication. That file is a pure-image PDF with no embedded text except the BPS
watermark URL, averaging 41 characters per page in pdfplumber extraction against the 100-char
threshold. No additional script was needed; the unified mode-detection logic in
`parse_pdfs_text.py` routes it automatically.

### Faithful-snapshot principle

On 2026-07-13 the parsing stage was prohibited from any numeric interpretation or
cleaning. An earlier "Group C clean" variant (`parse_pdrb_wide_clean.py`)
had Claude correct corruption artifacts before output. That was rejected because Claude's
correction logic is non-deterministic across runs and produces no auditable record of which rows
were touched; a Python regex acting on the preserved verbatim string produces a flag whenever
`original != cleaned`, making every correction auditable and re-runnable.

BPS PDFs contain two systematic sources of numeric corruption. First, BPS's diagonal watermark
URL (`bps.go.id`) injects individual letters into numeric strings during extraction; pdfplumber
faithfully reports what the PDF's font ToUnicode table maps those bytes to, which in practice
produces stray `d`, `i`, `o`, `g`, `b`, `w`, `/`, `:`, `t`, `h` characters within number
strings (e.g. `652.48d0` for `652.480`). Second, the PDF sometimes stores large numbers as
separate text spans (`57` and `.507`) which pdfplumber joins with a space (`5 7.507`). The
`clean_value()` function in `standardize_pipeline.py` handles both by stripping alphabetic
characters, collapsing spaces, and stripping trailing periods.

### Temperature=0 and the sparse-row misassignment trade-off

`temperature=0` makes Claude's output near-deterministic for identical input. Before
this was applied, the same PDF produced `2002*)` in one run and `2002»)` (a font-encoding
artifact) in another for the same year column header, requiring the year-pattern regex to be
robust to both. Temperature=0 makes the artifact consistent across runs.

The trade-off is that for newly-split districts with data in only one year column, Claude at
`temperature=0` mechanically places the value in the first year column rather than using
contextual reasoning to identify the correct column. At `temperature=1` Claude sometimes used
document context to place sparse values correctly; at `temperature=0` it does not. The scale
is approximately 0.1% of rows (2 in 736 in a 10-page Sumatra spot-check). The decision was to
accept this and flag misassigned years in standardization using `split_concordance.csv`: if a
district has a value in year X but the concordance says it was created in year Y > X, the
value at year X is nulled with `year_misassigned=True`. The correct value arrives from the
publication that actually covers year Y.

Pre-publication audits of name-matching and roster completeness: `harmonize_regions.py` assigns `match_status = unmatched` to any district name without an exact match and writes such rows to `pipeline_out/audits/harmonize_unmatched.csv`. A pre-publication audit found exactly two cases — `DAM` (OCR garble of DAIRI, Sumatera Utara) and `LUBUK UNGGAU` (LUBUK LINGGAU, Sumatera Selatan) — both resolved via `name_corrections.csv`; the harmonizer now reports zero unmatched rows.

`harmonize_presplit_mismatch.csv` enumerates all 46 pre-split `#)` aggregate rows flagged for manual review. A within-source duplicate-detection audit surfaced two genuine collisions (kabupaten and kota Kendari merging into a single series; four Kalimantan Utara districts duplicated by a parser column shift), both corrected (Sections 2 and 4). A roster-completeness audit (Check 11 in `validate_panel.py`) confirmed no sandwich-missing districts: across the ten total-PDRB publications, district counts rise monotonically from 284 to 488 exactly as pemekaran predicts, and no district present in both the preceding and following publication is absent from the one between.

### Two-pass architecture and the debug files

Stage 1 (Claude API): pdfplumber extracts raw text or page images, sent to Claude with the
parsing prompt. Claude writes back `## HEADERS / ## DATA / ## ANOMALIES` sections. These raw
responses are saved as `_chunk<n>.txt` debug files in `pipeline_out/<run>/logs/`.

Stage 2 (Python): `parse_response()` splits sections; `read_csv()` parses pipe-delimited rows
using `on_bad_lines="skip"` and `quotechar="\x00"` (the null byte) to handle rows that are one
field short and region names containing double-quote characters; `melt_to_long()` converts wide
to long format, extracting year and year-flag from column names and joining HEADERS onto DATA on
`table_number`.

The debug files were critical for diagnosing Stage 2 failures without additional API calls. When
the Group B parser returned "no rows parsed," the debug file showed Claude's output was correct
and well-formed; the failures were all in Stage 2: trailing empty pipe omission (rows one field
short), stray `"` in region names, and a silent `except Exception` clause that hid both errors.

The `--replay` flag reads from saved chunk files, enabling Stage 2 re-runs without any API calls.

### Wide format rationale

BPS PDF tables are already wide (one row per district, five year columns). Asking Claude to emit
long format requires it to repeat each district row five times; at approximately 200 characters
per row, five years, and 35 districts per province, a 3-page chunk in long format needs about
26,000 output tokens. The same chunk in wide format needs about 4,000 tokens. The early long-
format runs were truncated at MAX_TOKENS=8,192 (Run 1b, 2026-07-11) and again at MAX_TOKENS=
32,000 (Run 1d) because the estimate was revised upward. The wide format made truncation a
non-issue and allowed returning to 5-page chunks.

### Year column header robustness

BPS provisional markers appear in year column headers (`2021*`, `2022**`). The PDF's font
encoding maps the asterisk codepoint inconsistently; pdfplumber produces both `*` and `»`
(U+00BB, RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK) for the same character across runs and
files. A hardcoded character-class fix was tried and superseded. The final pattern: any column
name starting with four digits is a year column (`^\d{4}`). The year integer is the first four
digits; the year_flag is everything after them, verbatim. This pattern captures all observed
variants (`2002*)`, `2006**)`, `2021*`, `2022**`, `2002»)`) without code changes as new
variants are encountered.

### Script registry and the freeze rule

Each validated parser is frozen. No modifications are made after validation. Any change
requires a new script with a new name and a new row in the registry table maintained in
`archive/superseded_docs/parse_experiment.md`. This prevents silent regression where a fix for
one PDF group breaks another. The rule was established after the year-pattern fix (which was
legitimately backward-compatible) prompted a discussion about when modification vs. copying is
appropriate. The conclusion: backward-compatible robustness fixes before any full run are
acceptable; anything else requires a new script.

---

## 2. Correction Pass Design

### Why corrections live in a script, not a config file

`scripts/apply_corrections.py` (Stage 2, designed 2026-08-09) encodes all manual cell
corrections as ordered Python functions rather than reading from a config CSV. The corrections
log (`pipeline_out/full_runs/corrections_log.csv`) is an append-only audit trail, but its
schema drifted across fix generations and rationale fields contain unquoted commas, making it
unsuitable as a machine-readable spec. The Python script is idempotent.

### Three-state idempotency logic

When a correction runs, it checks the target cell against two expected strings. State 1: the
bad value is present, the correction is applied and a sidecar row is written. State 2: the
expected good value is already present (a prior apply pass already ran), the correction is
silently skipped. State 3: neither the bad nor the good value is present, meaning a re-parse
produced a different garble. State 3 raises a hard error with a detailed report rather than
silently proceeding. State 3 is the signal that the correction set needs human review before
the pipeline continues.

The `--dry-run` flag prints a summary of what would be applied, skipped, or failed without
modifying any CSV. The end-of-run summary prints counts of applied / skipped / failed
corrections, enabling quick verification that a re-run reached State 2 (all skipped, none
failed) on previously corrected files.

### Content-keyed matching

All row matching uses content keys (province, district, year, and the current cell value
string) rather than row indices. Row order in the parsed CSVs is not guaranteed stable across
re-parses; index-based matching would silently apply corrections to the wrong rows after any
re-parse that rearranges output order.

The `bad` value serves as the discriminator when two rows share province, district, and year:
the critical design choice for the KALTARA_shift correction (see below), where the
Kalimantan Timur section and the Kalimantan Utara section of the same file both contained rows
for the same district names in the same year, distinguished only by the value present.

### Old fix scripts must not be replayed

Earlier ad-hoc fix scripts are not idempotent. `fix_p3_digit_garbles.py`'s W3c function
multiplies Sambas' capita values by 10 unconditionally, producing a factor-of-100 error on a
second run. `fix_banjarmasin_1997.py` asserts on the bad value being present and crashes on
already-fixed data. `apply_corrections.py` encodes the net current truth only, collapsing dead
pairs: B2 (the Bogor swap) and B2-revert together net to nothing, so neither is encoded; only
P7_recover's final corrected values are encoded.

### Notable corrections

**FAKFAK_err**: The 1996–1999 PDRB for Fakfak (then in Irian Jaya) is 10–25× the 2000+
values, which DAPOER corroborates. The Third Fable Review (2026-08-11) established via the
DAPOER crosscheck that the 2000+ values are correct and the pre-2000 values are the anomaly.
The boundary change at 2000 (the old Fakfak included Sorong and Manokwari territory) could
explain approximately a 1.3× reduction, not 10–25×. These values are nulled and
absent from all panels.

**W3 (Banjarmasin 1997 real)**: A scan shadow artifact on page 45 of PDRB_1996-1999.pdf
doubled a character, rendering the leading "1" in `1.421.607,59` as "L". The corrected
trajectory is 1.331T (1996) → 1.422T (1997) → 1.244T (1998) → 1.243T (1999), which is
economically coherent with the Asian financial crisis dip. This correction established the
diagnostic template for digit-garble fixes: a single-year spike or collapse that reverts in
the adjacent year, combined with a digit-plausible garble, is a strong signal for a source
scanning or typesetting error.

**W3a (Kampar real/1993 2000–2003)**: Series drops from 1.83T (1999) to 11.1B (2000) and
stays at 11–13B through 2003, a ~×150 understatement. The 1999 pemekaran (Pelalawan and Rokan
Hulu split out) explains a drop but not a 99.4% collapse. PDF inspection confirmed a BPS
source error in both the 2000–2001 and the 2003–2007 publications for these rows. All eight
values are nulled.

**W3c (Sambas capita 1996–1999)**: All four years sit at 0.20–0.40M rupiah per capita, below
the plausibility floor for even the poorest rural districts, then jump exactly ×10 to 3.98M in
2000. Every other Kalimantan Barat district has a boundary ratio near 1.0 at 2000. The
1996–1999 capita file used a ÷10 denominator for Sambas only; a ×10 correction was applied
and logged.

**KALTARA_shift**: The capita 2011–2013 file merged the Kalimantan Utara per-capita table
(Tabel 160) into the Kalimantan Timur table (Tabel 159). Parser output assigned Kaltara rows
to province "KALIMANTAN TIMUR" and shifted all year columns one position left: the 2013 PDF
value appeared under 2012, 2014's under 2013, 2015's under 2014. The 2015 column in the
Kaltim section received junk ("3") where the PDF prints a dash. This was confirmed by
cross-checking implied population: dividing total PDRB by per-capita gives an implied
population series; under the shifted reading Tarakan's population runs 211k → 219k → 227k →
236k (plausible); under the unshifted reading it implies 211k → 195k → 227k (implausible dip).
The total-panel file's Kaltara section was on its own page with correct labeling and no overlap,
providing an independent clean reference. Fix: 25 content-keyed cell corrections (fix_id
KALTARA_shift). The mislabeled province_name on the Kaltara section rows was left as parsed;
`province_crosswalk.csv` maps KALIMANTAN UTARA to KALIMANTAN TIMUR, so routing is unaffected.

**B2-revert and P7_recover (Kota Bogor nominal 2002–2004)**: An earlier fix (B2) had swapped
Kab. Bogor and Kota Bogor nominal values in PDRB_2002-2004 based on a plausibility argument
(Kab. Bogor should be larger). A subsequent read of PDF page 12 showed that the parser had the
original layout correct: the printed values matched the parser output, not the swapped values.
B2 was immediately reverted. Reversing a previously applied fix when PDF evidence contradicts
a plausibility argument, and logging both the wrong fix and the revert with full before/after
values, is the correct process. After the revert, Kota Bogor nominal
2002–2004 was unreadable; those three years were recovered by direct visual read from the same
PDF page (fix_id P7_recover): 3,459,398.26 / 3,915,569.13 / 4,515,746.82 juta. Garbled 2005
and 2006 values (approximately 47M and 65M juta, larger than Kab. Bogor) were also corrected
(fix_id P7_garble), though the 2005–2007 publication carries higher-priority values for those
years and the panel takes those.

**W2/W2b (Lampung capita 2017–2019)**: The PDRB-capita_2017–2019 publication used wrong
population denominators for 5 of 15 Lampung districts. Confirmation: 10 of the 15 Lampung
districts in that table match lampung.bps.go.id exactly, while the 5 bad districts show
per-capita values 5–10× implausible (Kota Bandar Lampung at 328 million rupiah per capita in
2017, equivalent to roughly USD 22,000, is not plausible for a mid-tier Indonesian city). The
majority-agreement validation (10/15 exact match) makes the correction defensible;
without it, "online disagrees" could merely reflect revision-vintage differences. This method
was promoted from an ad-hoc fix to a documented correction protocol.

**W2c (Sumatera Barat capita 2000–2001 recovery)**: The 2000–2001 per-capita publication used
approximately 62,000 as the population denominator for every Sumatera Barat district regardless
of actual population. Padang, with an actual population around 743,000, showed 116M rupiah per
capita in 2000 as a result. All 15 district-years were nulled and then recovered from BPS Query
Builder (Seri 2000 HB, per-capita export in juta rupiah). Conversion: juta × 1,000,000 =
rupiah. Two pre-split `#)` rows (Kota Pariaman) were left null as they do not represent
district-level data. The source CSV is stored in
`pipeline_out/full_runs/correction_sources/`.

**W3e (Mamuju 1999 real spike, nulled)**: The flagged value is a 232% single-year spike in the
*real* (constant-price) series, which reverts the following year — a classic OCR/transcription
signature, not a plausible output pattern. Considered and rejected: a genuine economic driver.
The 1997–99 Asian Financial Crisis did produce a real "cocoa boom" in export-commodity regions
like Mamuju — as the Rupiah collapsed against the USD, cocoa and palm-oil prices spiked in
Rupiah terms, and rural producing areas saw incomes multiply while urban Java suffered
industrial collapse. This is a well-documented mechanism, but it operates on *nominal* prices,
not real output. Real series are constructed specifically to strip out price effects; a genuine
232% real-terms spike would require Mamuju to roughly triple its actual physical cocoa/palm-oil
production in a single year, which planting and harvest cycles do not allow even under a strong
price incentive. The nominal series plausibly did jump that year for real economic reasons; the
real series should not have, which is consistent with treating the flagged value as a source
error rather than genuine growth.

### Boundary between corrections and standardization

A mechanical test distinguishes work that belongs in `apply_corrections.py` from work that
belongs in `standardize_pipeline.py`. Apply_corrections handles edits to columns that exist in
the parsed CSV: raw BPS value strings, names, row structure, specific value overrides confirmed
by PDF or BPS online sources, nulling of confirmed errors, and external-source recoveries.
Standardize handles everything else: generic rules requiring no case-specific knowledge, number
format conversion, unit derivation, metadata derivation (oil_excluded, table_type, base_year,
admin_type, row_type), and character-class garbles like space-for-period and stray letters
(`clean_value()` already handles these).

BUG A (the Aceh capita unit override) stays in standardize because correcting the
interpretation of a unit label ("miliar rupiah" → "ribu rupiah") is unit-derivation work.
Moving it upstream would require editing `table_header_raw` in the parsed CSV, which would
falsify the verbatim-PDF property of Stage 1 output.

### bps_code addition (2026-08-19)

`bps_code` (BPS 4-digit Kode Wilayah) was added to all five panel outputs as the third column, after `district_id` and `district_num`. Source: the `bps_code` column in `crosswalks/district_reference.csv`, which was populated during construction via `fill_bps_codes.py` (no longer retained) — 405 rows auto-matched against `crosswalks/bps_code_reference.csv`, 17 filled manually. The column is read with `dtype=str` to preserve formatting; `bps_code` is not a unique key for ~14–15 parent/successor pairs. See data guide §5 (`bps_code`).

### Sidecar and correction_id provenance

`apply_corrections.py` writes `corrections/corrections_applied.csv` at run time. Each row
records the source_file, fix_id, region_name, year, table_type, and the
`raw_text_hash` of the row actually modified. The `raw_text_hash` column (MD5 of all
Claude-output fields pipe-joined) survives unchanged through standardize and harmonize into
the panel inputs. The panel joins `correction_id` onto rows using `(source_file, raw_text_hash)`
rather than on names or year values.

This design replaced an earlier name-based join that was silently failing for all but
5 of the 99 sidecar entries. The Fourth Fable Review (2026-08-12) identified the root cause:
`pd.read_csv` without `keep_default_na=False` converts empty strings in the `table_type`
column to NaN, causing the typed/untyped split logic to classify all 99 sidecar rows as
"typed." Only the 5 genuinely typed rows (P7_recover and P7_garble) could then match, because
the untyped bucket was empty and the typed 4-key join requires `table_type == NaN` to equal the
panel's actual "nominal" or "real" strings, which never fires. The diagnosis contradicted the
initial hypothesis (case normalization mismatch); harmonize preserves `region_name_raw` verbatim
and sidecar names match it exactly. Data values were confirmed correct in all cases; this was a
tag-only defect. The durable repair was the hash-based join, which also resolved a secondary
over-tagging problem where Kab. Bogor and Kota Bogor share `region_name_raw="Bogor"` in the
2002–2004 file and a name-based join cannot distinguish them.

---

## 3. Standardization Decisions

### Unit normalization

`standardize_pipeline.py` converts all parsed values to bare rupiah. Multipliers are derived
from the table header text: ribu × 1,000, juta × 1,000,000, miliar × 1,000,000,000. The
Indonesian number format (period as thousands separator, comma as decimal) is consistent across
all 1996–2025 publications and is never changed. The BPS number format note in Schema.txt reads
"period (.) = thousands separator. Comma (,) = decimal separator. Consistent across ALL
publication eras 1996–2023. pdfplumber preserves this."

The 2000–2003 publication uses "Jutaan Rupiah" (millions); the 2003–2007 and later publications
use "Milyar Rupiah" (billions). Standardization detects the unit from the table header and
applies the correct multiplier.

The BERUKU alias handles an OCR dropout pattern: "BERLAKU" (meaning "current prices" in table
headers identifying nominal series) sometimes drops the "L" characters, producing "BERUKU."
Standardize maps BERUKU to BERLAKU in table_header_raw parsing, reclassifying 1,288 rows that
had been assigned to the wrong table_type.

### SNA vintage and base year assignment

Three real-price series appear in the panel, assigned from the source file's publication era.
The `real/1993` series covers the 1996–1999 and 2000–2003 publications (SNA 1993). The
`real/2000` series covers the 2003–2007 and 2008–2012 publications (SNA 1993, rebased). The
`real/2010` series covers 2011 onward (SNA 2008). These are not directly comparable across the
2010 base-year break; the nominal series is usable across the full period without adjustment.

The Fable Design Review (2026-08-08) raised a concern about whether the 2000–2001 publication's
real tables labeled "base year 1993" for some provinces (DIY, Purwakarta, Sumbawa) are actually
mislabeled as 2000-base during standardization, given +110–176% jumps inside a single
base_year=1993 keyed series. PDF inspection (P4b, 2026-08-09) confirmed cross-publication
statistical revisions as the correct explanation for Purwakarta and Sumbawa: the printed values
match the panel exactly, and the jumps are legitimate BPS revisions between publication series,
not pipeline errors.

### oil_excluded flag logic

Oil-exclusion sub-rows (BPS "tanpa migas bumi", without oil and gas) are paired rows immediately
below the total row for oil-producing districts. Standardize normalizes all marker variants to
`"1)"` and sets `oil_excluded=True`. The critical bug B1, fixed 2026-08-08, affected the 2008–
2010 publication: in 36 districts, the `1)` marker had been concatenated into the district name
string during PDF extraction (e.g. "Kab. Indragiri Hulu1)"), captured as `footnote_marker`
rather than `name_flag`, and bypassed the detection logic. The fix: if `footnote_marker == "1)"`
AND `name_flag` is NaN, set `oil_excluded=True`.

This bug caused severe panel corruption in the most-affected districts. RIAU_SIAK for 2008–2012
alternated between 3.3T (oil-excluded sub-row, mislabeled as total) and 15.0T (true total) in
alternating years, creating apparent year-over-year swings of -78% to +355%. For
BENGKALIS, the oil-excluded and total values have a 7:1 ratio; mislabeling produced values off
by 85%. Fixing B1 reduced Check 3 growth anomalies from 81 to 59 and Check 8 within-file
duplicates from 566 to 210.

Oil-excluded sub-rows exist only through the 2008–2010 publication; BPS stopped printing them
in the 2010-base SNA 2008 era.

### admin_type from regency code (Q3 rule)

Pre-2008 BPS publications do not label districts as kabupaten or kota. Standardize derives
admin_type from the BPS numeric regency code, which carries a consistent convention across all
publication eras: `kota` if `(regency_code mod 100) >= 71`, else `kabupaten`. (The mod 100
guards against any 4-digit BPS codes; code 70 is unused.) Jawa Barat 2003 illustrates the
pattern: code 1 → Kab. Bogor, code 71 → Kota Bogor, code 73 → Kota Bandung, code 77 → Kota
Cimahi. This rule resolved approximately 1,800 previously ambiguous kab/kota rows, reducing
`ambiguous_kab_kota` to zero. For oil-exclusion sub-rows and other rows with empty codes,
admin_type is inherited from the immediately preceding total row of the same district.

### Provisional year handling

Rows with a non-empty `year_flag` (BPS provisional markers, which appear in various OCR-garbled
forms including `*)`, `**)`, `»)`, and `**`) are kept in the panel with `is_provisional=True`
rather than dropped. Dropping provisional rows would eliminate 2022–2025 data entirely, since
those years are only available as provisional estimates in the 2021–2023 publication. Source-
priority dedup promotes non-provisional over provisional where both exist for the same
district-year-series combination.

The D3 decision (2026-08-06): "Rows with year_flag are kept, tagged is_provisional=True.
Dropping provisional would lose 2022–2023 entirely. Source-priority dedup promotes non-
provisional over provisional where both exist."

---

## 4. Harmonization and Boundary Decisions

### The pemekaran problem

Indonesia's post-decentralization district proliferation (the "pemekaran" wave) created 172 new
kabupaten and kota between 2001 and 2014, primarily by splitting existing districts. The panel
must decide how to handle these for cross-time comparability. The central question is whether to report each district in its native boundaries (a
discontinuous series at each split) or to aggregate children back to a consistent set of
2000-vintage parents (a continuous series at the cost of geographic granularity).

### Why 2000 was chosen as the boundary vintage

The primary panel (`_2000bounds`) aggregates all districts created after 2000 to their 2000-
vintage parent boundaries using the split concordance. The binding constraint was Kota Cimahi,
one of the five SCM donor districts: Cimahi was created from Kab. Bandung in 2000 and only has
its own BPS data from that year onward. Per-capita data for Banda Aceh and Ambon also begins in
2000. The 2000 boundary vintage is the earliest that keeps all five SCM units as standalone
series. The `_native` panels report each district in the years it appears in BPS publications,
without aggregation.

### How district_reference.csv was built

The canonical district registry carries 421 unique district IDs (422 rows total, with one
intentional alias row for the KENDARI/KONAWE case discussed below). The split concordance
carries 172 post-2000 pemekaran entries, each with a UU law number and promulgation date.
The batch date structure (many districts sharing exact promulgation dates) confirms the source
is primary Indonesian legal records (Kemendagri/BPS or similar), not Wikipedia.
172 entries for 2001–2014 is near-complete for the pemekaran wave; coverage was verified by
comparing the year distribution against the known legislative history of the moratorium on new
districts after 2014.

The D1 carve-out rule: a concordance child is treated as its own 2000-vintage unit if and only
if it appears as a standalone, non-`#)` data row in the early files (1996–1999 or 2000–2001),
regardless of whether it has non-null values. A district with its own BPS number and no pre-
split marker is BPS asserting it is an independent unit. Requiring a non-null value was rejected: it would be inconsistent with how the pipeline treats
missing data in later years (standalone districts with NaN values are kept, not demoted). The problematic `#)` child rows
identified in the Fable Design Output (districts like KAUR and SELUMA appearing with dashes
in 2000–2001 and values only in provisional 2002–2003 columns) are excluded by the `#)` check
rather than by a value check.

### KENDARI/KONAWE: the alias row

Kabupaten Kendari (renamed Konawe by UU 6/2003) and Kota Kendari both appear in the 1996–2003
publications under the base name "Kendari," distinguished only by regency code (3 for the
kabupaten, 71 for the kota). Both had been routing to `SULAWESI_TENGGARA_KENDARI`, producing
chimeric per-capita series with fake ~2.4× jumps in years where the two entities alternated in
dedup selection, and losing the kabupaten's 1996–2003 history entirely.

A name-corrections-only fix was impossible. In the 1996–1999 total and capita files, both
entities print as bare "Kendari" with no prefix, separated only by regency code. The OCR garble
"KENDAN" maps to the kabupaten in the capita 2000–2001 file but to the kota in the total 2000–
2001 file; any name-based routing would need to be file-specific, which name_corrections.csv
does not support.

The fix, applied 2026-08-15: KENDARI is now a kab/kota pair in district_reference.csv.
`SULAWESI_TENGGARA_KENDARI` carries `admin_type=kota` (BPS code 7471). An alias row carries
`district_name_2000=KENDARI, admin_type=kabupaten` and points to
`district_id=SULAWESI_TENGGARA_KONAWE` (district_num 376, BPS code 7402). The alias row is
placed before the canonical KONAWE row because the panel build's reference map is last-wins:
the canonical KONAWE row is the one that supplies `district_name_2000=KONAWE` in the final
panel. The reference now has 422 rows for 421 unique district IDs, and the data guide states this
exception explicitly.

After the fix: kabupaten rows 1996–2003 route to SULAWESI_TENGGARA_KONAWE via
`matched_with_admin_type`; kota rows route to SULAWESI_TENGGARA_KENDARI. The capita series for
KENDARI now runs clean (2.14M in 1996 → 9.73M in 2006, no oscillation). KONAWE gains its
1996–2003 series (0.94M → 4.06M) connecting to its existing 2004+ rows.

### match_status values and their confidence tiers

`matched`: exact join on (province_canonical, region_name_base, admin_type). Highest
confidence. `matched_with_admin_type`: admin_type was derived from the regency code (Q3 rule)
before the join; the underlying name match is exact. `matched_province_fallback`: name matches
district_reference but only after relaxing the province constraint (231 total rows, 54 capita).
Used for districts that appear under the wrong province in some publications due to OCR or
printing artifacts; lower confidence than `matched`. `child`: post-2000 child district assigned
to its parent via split_concordance (native panel only; 7,295 rows). `child_aggregate`: 7 rows
in `total_2000bounds` where a child's contribution was summed onto a parent that has no direct
row from that source file.

### Banten and Jawa Barat supplementary volume

Banten was carved from Jawa Barat in 2000. The main 2000–2001 BPS publication's nominal tables
did not cover Banten or post-split Jawa Barat (its constant-price 1993-base tables did, as did
the separate per-capita publication), leaving approximately 28 nominal district-year gaps. These
are filled from a supplementary BPS volume, `PDRB_1998-2001_jabar_banten`, a nominal-only
publication covering 1998–2001 for these two provinces. It was ingested as a 21st source file
with source priority 0 (lowest). Banten 2000–2001 is present in the `_2000bounds` panel as 24
rows: 12 nominal from the supplementary volume and 12 real from the main 2000–2001 publication.

The volume's unused 1998–1999 columns double as a transcription cross-check against the 1996–1999 publication: of 52 comparable district-years, 38 agree within 5% (23 to within 0.1%). This is the only external validation available for the pre-2000 parse, an era DAPOER does not cover. The divergences are BPS's own doing: Serang printed with and without Cilegon (an exact ×0.5), and retrospective revisions of crisis-era 1998–1999 figures reaching ×2 (Purwakarta). These revised 1998–1999 values are deliberately not ingested: the later-publication-wins principle would prefer them, but ingesting them would give Jawa Barat revised crisis-era figures while every other province kept unrevised ones, introducing a new inconsistency.

### Aceh 2000–2001 conflict-period data issue

All Aceh district values for 2000–2001 derive from the 2000–2001 BPS publication, produced
during the military emergency period. DAPOER, which uses a later retrospective revision, reports
systematically higher values for the same district-years, typically 40–80% higher for non-oil
districts, and consistent with the same revised series that begins with the 2002–2004
publication (DAPOER agrees with the panel to ~1 part per million from 2002 onward).

The 2000-to-2001 → 2001-to-2002 publication-boundary step is province-wide, affecting all 13
Aceh districts: Aceh Barat +81%, Banda Aceh +75%, Aceh Selatan +47%, Singkil +40%, Besar +36%.
The conflict-period publication reported lower values than the later revision; this is not a
parse error. The canonical panel preserves publication-vintage values for this period.

The recommendation from the Second Fable Review (2026-08-11) was to splice DAPOER 2000–2001
values for Aceh districts in the SCM analysis layer with a dedicated correction_id. The Third
Fable Review (2026-08-11) generalized this finding: the 2000–2001 vintage seam is nationwide,
not Aceh-specific. Of approximately 600 nominal district-years in 2000–2001, only 78 match
DAPOER within 1%; the median gap is about +5%, with oil districts and Aceh up to +80%.

---

## 5. Chaining Methodology

### Why chain-linking was added

The three real series (real/1993, real/2000, real/2010) cannot be naively stacked: they use
different base-year price levels and different SNA vintages. Cross-regime real growth analysis for the Banda Aceh SCM application (1996–2004 pre-treatment,
2005–2025 post-treatment) requires a single coherent series. Chain-linking was added as Stage 7 (`scripts/chain_link.py`), producing
`panel_pdrb_chained_2000bounds.csv`.

### Link year 2011 and backcast construction

The pivot year is 2011. Both real/2000 and real/2010 have observations in 2011 and 2012 from
their overlapping publication windows, providing the link ratio. For each district, the link
ratio is `real/2010(2011) / real/2000(2011)`. Post-2011 values are the BPS-published real/2010
figures unchanged, with `is_backcast=False`. Pre-2011 values are backcast:
`real_chained = real/2000 × link_ratio` for 2002–2010, with `is_backcast=True`. Extending
further to pre-2002 years via a second link at the 2003 overlap (real/1993 to real/2000) is
possible but not implemented; the chained panel spans 2002–2025 (8,315 rows, 348 districts).

### Non-additivity of chained levels

Chained levels are synthetic constant-2010-price figures and are not additive across districts.
Different districts have different link ratios, so the sum of district chained levels does not
equal the chained level of a province aggregate. This is a fundamental property of chain-linking,
not a pipeline error. The chained panel must not be used to sum districts to province totals or
to compare absolute levels across districts — growth-rate analysis only.

### The 10 drift-flagged districts

`ratio_drift_flag=True` marks 10 districts whose real/2000 and real/2010 growth rates disagree
by more than 5% at the 2012 validation year (one year past the pivot). Disagreement at 2012
suggests one of the two series has a structural discontinuity at the link point, making the
backcast less reliable for those districts. Users should treat drift-flagged backcasts with
extra caution or exclude them from pre-2011 real growth analysis.

---

## 6. External Review Findings (Fable Rounds)

"Fable" refers to Claude Fable 5, an LLM agent (Anthropic) used as an independent reviewer
throughout the construction of this dataset. It was invoked via the Claude Code CLI with access
to the full project directory. Five rounds of Fable design review ran between 2026-08-05 and
2026-08-16. Findings that led to code or documentation changes are recorded below.

### is_pre_split_aggregate coverage check (First Fable Review, 2026-08-05)

The Fable Design Output verified empirically that `#)` and `x)` flagged rows are additive to
the province total, not double-counts. Earlier documentation stated that child data was "also
rolled into its parent," implying these rows should be excluded to avoid double-counting.
Direct inspection of the 2002–2004 and 2000–2003 publications showed the opposite: province
Jumlah rows equal the sum of district rows including `#)` children. Excluding them would lose
real data.

The first Fable round also proposed the `is_pre_split_aggregate` flag as a cross-check
audit: after harmonization, any row with `is_pre_split_aggregate=True` whose match_status is
not `child` or `matched` indicates either an OCR name garble or a missing concordance entry.
Running this audit produced the list of approximately 78 distinct (province, base name) pairs
that needed `name_corrections.csv` entries, mostly concentrated in the vision-parsed 2005–2007
file (e.g. MORAWALI → MOROWALI, TEMATE → TERNATE, KENDAN → KENDARI, ACEH TAINIANG → ACEH
TAMIANG, RAJA /VMPAT → RAJA AMPAT).

### KENDARI routing investigation (2026-08-15)

The routing problem was identified during routine pre-publication verification. The capita panels
showed 2.4× jumps for KENDARI in years where the kabupaten and kota alternated in dedup
selection; tracing through harmonized files showed both entities resolving to the same
district_id. A name-corrections-only fix was impossible because the OCR garble "KENDAN" maps to
different physical entities in different files depending on whether the file is from the total or
capita series. The solution, described fully in Section 4,
was a kab/kota pair with an alias row in district_reference. Verification after the fix: kab
rows 1996–2003 route to SULAWESI_TENGGARA_KONAWE; kota rows route to
SULAWESI_TENGGARA_KENDARI; ambiguous_kab_kota stayed at 0; unmatched stayed at 0.

### Sorong Kab vs Kota documentation error (Final Pre-Publication Review, 2026-08-16)

The Third Fable Review (2026-08-11) identified that DAPOER reports values exactly 100× the
panel for PAPUA_BARAT_SORONG_KAB in 2013–2016 and SULAWESI_SELATAN_TAKALAR in 2013–2015
(ratio 99.98–100.01, confirmed by smooth surrounding panel trajectories). These are DAPOER-side
data-entry errors; the panel is correct in both cases.

The Final Pre-Publication Review (2026-08-16) found that the data guide §8 twice described these
as "Sorong Kota" rather than "Sorong Kab." The district in question is the kabupaten; both Kota
Sorong and Kab. Sorong exist as district IDs in the panel. This was finding E2 in that review's
three-error list (all documentation; no data or pipeline errors were found). The data guide was
corrected before the PURR deposit.

### webchat_parser_1996-1999.txt and archiving

The original 1996–1999 data came from a web-chat parsing session before the scripted pipeline
existed. The raw Claude web-chat output was saved as `webchat_parser_1996-1999.txt` and
initially committed to the repository. Before publication, a review identified it as intermediate parsing output, not a formal pipeline artifact. The
file was archived to `archive/` to keep the top-level structure consistent. The `raw/parsed/claude/PDRB_1996-1999_long.csv`, a clean CSV
derived from that session and used as validation ground truth, remains in the repository.

### Sidecar provenance join fix (Fourth Fable Review, 2026-08-12)

Discussed in detail in Section 2. The broader methodological significance: the
`feedback_pandas_null_string` principle (never use `"null"` as a CSV categorical label; pandas
`read_csv` silently converts it to NaN on read-back) generalizes to empty strings in any column
when `keep_default_na=True` (the default). The NaN-vs-empty-string misclassification appeared
in a context that is not immediately obvious: `sidecar["table_type"].ne("")` returns True for
NaN values because NaN is not equal to the empty string. The assertion machinery correctly
fired a signal; the process error was padding the exclusion list (adding W3c and W2b) to
silence the check rather than chasing it. The Fourth Review named this as the only process
concern.

---

## 7. Validation Snapshot

### DAPOER real-series crosscheck

A full crosscheck against the World Bank DAPOER real-series extract ran across the Third and
Fourth Fable Reviews (2026-08-11, 2026-08-12). The comparison covered five indicator series
across 13,172 district-year observations matched using province-consistent exact
(normalized-name) matching with no suffix fallback.

The real/2010 series (DAPOER series NA.GDP.INC.OG.SNA08.KR) is the most direct comparison:
both sources use SNA 2008 vintage and the same BPS publications for 2011 onward. Of 3,358
matched district-year observations, 3,311 agree within 1% (98.6%). Of the 47 disagreements, 15 exceed 20%; all are
DAPOER-side defects: seven rows carry a ×100 data-entry error for Sorong Kab 2013–2016 and
Takalar 2013–2015; two are dropout values for Malinau 2018–2019 (DAPOER: 49 and 52 billion,
panel: 7,374 and 7,849 billion, DAPOER rejoins 2020); the remaining flags are dropped-digit
entries (Asahan 2013: DAPOER's 1,893 is the panel's 18,893 with the second digit "8" dropped;
Banda Aceh 2016: dropped digit; Halmahera Barat 2020: ÷10 at end of DAPOER series), a
reversed data-entry block (Malang Kota 2013–2017: DAPOER's 2013 value is our 2017 value, 2014
is our 2016, and so on), and a stale-vintage pair (Morowali 2018–2019: DAPOER rejoins 2020,
its own implied 2019-to-2020 change would be +155% in the COVID year, confirming DAPOER carries
pre-revision figures while the panel carries the final nickel-boom vintage).

**1–20% band (32 cases, investigated 2026-08-19).** A subsequent investigation examined all 32 district-year pairs in the 1–20% discrepancy band. All are DAPOER-side; no panel value is suspect.

- **Malang Kota reversal tail (3):** 2014 (+11.5%), 2016 (−10.3%), 2017 (−19.8%). Same reversed block documented for 2013. DAPOER 2013–2017: 46,825→44,304→41,952→39,725→37,548 bn (descending); panel: 37,548→39,725→41,952→44,304→46,825 bn (ascending). DAPOER's 2013 = panel's 2017 exactly.
- **Kampar stale re-emit (2):** 2018 (−4.7%), 2019 (−10.7%). DAPOER's 2018 value (47,610) equals its own 2016 value; its 2019 value (46,314) equals its own 2015 value exactly. Panel continues ascending: 49,959→51,889 bn. DAPOER stopped updating after 2017 and re-emitted stale values.
- **Bengkulu Kota transposition (2):** 2015 (+12.2%), 2017 (−10.7%). DAPOER 2015–2017: 13,825→13,087→12,327 bn (descending); panel: 12,327→13,082→13,797 bn (ascending). DAPOER's 2017 = panel's 2015 exactly — two years transposed.
- **DAPOER provisional 2018–2020 window (21):** Minor divergence (1–5%) in DAPOER's final 2–3 years, reconverging at 2020. Three districts have both 2018 and 2019 pairs (Konawe, Banggai Kepulauan, Buol); six have 2019 only (Banggai, Donggala, Kolaka, Pandeglang, Tangerang Kota, Pontianak Kota); Manokwari spans 2019–2020; seven have 2020 only (Halmahera Tengah, Jayapura Kab, Jayapura Kota, Madiun Kota, Madiun Kab, Kupang Kab, Jambi Kota). DAPOER carries a slightly different provisional vintage for these years.
- **Isolated single-year noise (4):** Mimika 2016 (−1.9%), Muara Enim 2016 (−1.4%), Wonosobo 2017 (−1.2%), Semarang Kota 2017 (−1.0%) — all show exact agreement (<0.1%) on both neighboring years; single-cell DAPOER rounding or revision.

The nominal series (60% within-1% agreement) is a vintage artifact. Four buckets account for
all 1,168 flags after matcher corrections: 65% are the SNA 2008 vintage difference for 2011–
2013 (panel uses the revised publication, DAPOER carries pre-revision); 23% are boundary
backdating (DAPOER retro-applies post-split boundaries); 11% are the nationwide 2000–2001
early-publication vintage seam; and under 1% are boundary-switch timing differences. After
removing these structural buckets, the nominal crosscheck contains zero previously-unknown panel
value errors.

The crosscheck matcher design: exact normalized-name matching within province only; no suffix
fallback. An earlier version with suffix matching produced three spurious cross-matches:
`Lingga, Kab.` (Kepulauan Riau, a 2003 child) to JAWA_TENGAH_PURBALINGGA ("LINGGA" is a
suffix of "PURBALINGGA"), `Lebong, Kab.` (Bengkulu) to BENGKULU_REJANG_LEBONG, and
`Samosir, Kab.` to SUMATERA_UTARA_TOBA_SAMOSIR. These generated 101 artifact flag rows that
disappeared after the suffix fallback was removed.

### validate_panel.py check suite

The pipeline runs eleven automated checks after each full build.

Check 1 (no duplicate panel keys) passes in the final build.

Check 2 (year gaps) reports 3 series with gaps in the final build. The largest resolved gap was
the apparent 7-year Batanghari gap (2004–2010), a pipeline artifact: the 2005–2010
publications spell the district "Batang Hari" while 1996–2003 and 2011+ spell it "Batanghari,"
causing the harmonizer to mint two district IDs. The Second Fable Review (2026-08-11) identified
this by collapsing underscores over all district IDs and finding the two fragmented identities.
Merging via name_corrections.csv resolved the gap and removed two spurious growth anomalies.
Four other P1 spelling-variant pairs were resolved simultaneously: BATANGHARI → BATANG_HARI,
BUKIT_TINGGI → BUKITTINGGI, SAWAHLUNTO → SAWAH_LUNTO (disentangled from SAWAHLUNTOSIJUNJUNG,
the kabupaten), and BANJARBARU → BANJAR_BARU. The Bulungan and Kutai Kartanegara 2004–2007 gaps
(previously deferred as OCR misses) are also resolved in the final build. The 3 remaining gaps
are Mamuju real/1993 1999 and Barru nominal 1998 (both panels), which are the deliberate nulls
for confirmed BPS source errors (data guide §9) rather than pipeline artifacts.

Check 3 (growth anomalies) reports 28 anomalies in the final build, down from 81 before B1 and
W3 corrections. The three largest jumps — +316% to +353% nominal at 2011 for Pasuruan Kab,
Ternate, and Bulungan — are genuine SNA1993→2008 accounting-regime revisions (verified against
DAPOER), not pipeline errors. All remaining anomalies are structural base-year transitions or
cross-publication revision steps.

Check 4 (province-sum discrepancies) reports 21 flags in the final build, all structural. The
largest category is oil-excluded coverage mismatches (only 1–2 districts per province publish
oil-excluded figures, making the comparison against the oil-excluded province total meaningless).
The province-sum validation script (2026-08-12) confirmed that in Kalimantan Timur, district sums
exceed the province total by 5–10% due to BPS's migas reconciliation methodology (district-level
oil/gas attribution sums to more than the province-level figure after provincial reconciliation).

Check 5 (overlap revisions, 2021–2022) passes: the panel correctly uses PDRB_2021-2023 over
PDRB_2020-2022 at the 2021–2022 overlap. All 2,094 overlap records show revision_pct = 0.0 — BPS
reprinted the 2021–2022 values unrevised in the 2021–2023 edition, confirmed at the raw parse
level. There is no vintage ambiguity at this overlap.

Check 6 (null-parent rows) passes in the final build. An earlier build reported 48 total and 23
capita rows for MAMASA only — MAMASA split from POLEWALI MAMASA in 2002, before SULAWESI BARAT
split from SULAWESI SELATAN in 2004, so the harmonizer looked for the parent in the wrong
province. This was resolved; the check now reports zero.

Check 7 (asymmetric coverage) lists 8 districts: 3 Jambi total-only and 5 Papua Barat capita-
only. All are confirmed genuine source asymmetries, not parsing artifacts.

Check 8 (within-file duplicates) reports 140 rows in the 2000–2001 file only in the final build:
the exact-value duplicates from the dual-section artifact (harmless, resolved by dedup). The
capita 2008–2010 oil pairs for Indragiri Hulu and Pelalawan — previously 16 duplicate rows across
years 2008–2012 — were resolved by extending BUG_E to all five years. All years 2008–2012 now
carry unambiguous tanpa-migas values identified by the consistent tanpa/dengan ratio (~0.96–0.97)
anchored to the 2010 reference case.

Check 9 (implied population) reports 137 flags; 116 are at known split parents (expected rump-
territory drops, data guide §7.14). Of the 21 not at a known split, most sit at the year-2000 seam
(Census-2000 denominator revisions) and Banda Aceh 2005 (tsunami). Two annotation misses inflate
the count: SANGIHE TALAUD does not string-match parent "KEPULAUAN SANGIHE," and Kepulauan Riau
similarly, so they appear unexplained but are not genuine anomalies.

An external version of this check compares implied population against DAPOER's district population
series: 77% of ~7,300 comparable district-years agree within 10%, and the large disagreements are
concentrated exactly where predicted — split parents after their split year, and 1999-split
districts at the year-2000 seam. No isolated order-of-magnitude discrepancies (the signature of
transcription error) appear.

Check 10 (implied deflator) reports 54 flags. Forty-two fall in 2021–2023, concentrated in the
Kaltim/Kalsel/Kalteng/Riau/Jambi/Sumsel coal-oil belt: 2022 spikes (+22% to +46%) and 2023
corrections (−19% to −26%) mirror the HBA coal price boom/bust. All are commodity economics, not
pipeline errors.

Check 11 (roster completeness) passes: no sandwich-missing districts across the 10 publications.

### Province-sum validation

`scripts/validate_province_sums.py` (2026-08-12) reads all standardized files pre-dedup and
flags 842 conditions. All trace to five known structural causes: the 2000–2001 nominal dual-
section row duplication; genuine geographic/resource concentration (Aceh Utara/Arun LNG,
Kutai pre-pemekaran, Bengkalis, Mimika/Freeport, Batam, Bangka, Teluk Bintuni LNG); pre-
full-districting provincial aggregates (Maluku Utara in 2000–2001, where the territory not yet
organized into reporting kabupaten was carried as one "Maluku Utara" aggregate row); Kab/Kota
name collisions before harmonization (Banten Tangerang, resolved by dedup); and BPS migas
reconciliation. No new panel errors were found. The `district_dominates` threshold of 55% was retained because
the check was designed to catch the Fakfak source error (Fakfak was 62% of Irian Jaya before
the null correction); raising the threshold would blind it to the exact error class it was built
to surface.

### split_concordance.csv reliability assessment (2026-08-13)

Known issues confirmed: SUMBA_TENGAH had a self-referential parent (parent_name_raw was "Kabupaten
Sumba Tengah" pointing to itself instead of "Kabupaten Sumba Barat"); this was corrected.
TAMBRAUW split from both Sorong and Manokwari (UU 56/2008), but the single-parent schema assigns
it to SORONG only; aggregation to MANOKWARI will understate by Tambrauw's share; this cannot be
cleanly fixed without a schema change and is documented in the concordance's notes column. Overall reliability for year-based harmonization: MODERATE-TO-HIGH; structural issues are
localized and non-systemic.

### Final replication run (2026-08-15)

The replication package was assembled by `scripts/make_package.py`. All five panels pass SHA-256
integrity verification in `outputs/checksums.sha256`; the shipped outputs are byte-identical to
the verified 2026-08-15 pipeline run. The Final Pre-Publication Fable Review (2026-08-16)
verified all quantitative claims in both documentation files against the shipped panels. Three
documentation errors were found (E1: wrong source publication stated for Aceh 2000–2001, E2:
"Sorong Kota" should be "Sorong Kab" in §8 twice, E3: capita_native year range stated as
2000–2025, actual span 1996–2025) and no data or pipeline errors. The correction inventory has 166 sidecar rows, 22 fix families, 9 source files (144 corrections total, as documented in data guide §9).
The zero-tag fix set is exactly {W3a, W3e, P5a, P6, FAKFAK_err} (nulled, rows dropped before
panel) plus {P7_garble, W2} (superseded by higher-priority publications). Five SCM units are
confirmed gap-free 2000–2023 in both the total and capita panels.
