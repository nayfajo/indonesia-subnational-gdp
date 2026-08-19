"""
DAPOER real-series crosscheck.

Compares the full DAPOER download against panel_pdrb_total_native.csv across five
GDP series: SNA1993 real incl/excl oil, SNA1993 nominal incl/excl oil, SNA2008 real.

Key fix over dapoer_crosscheck3.py: province-consistent matching — each DAPOER district
row carries a province code prefix (e.g. ID.BA from ID.BA.BD) which maps to our
province_canonical, so the matcher only searches candidates in that province.
This eliminates the 4 cross-province bad joins from v3.
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

DAPOER_CSV  = Path("dapoer_extract/dee68668-cee8-410a-9807-d375830e6e72_Data.csv")
PANEL_TOTAL = Path("outputs/panel_pdrb_total_native.csv")
DIST_REF    = Path("crosswalks/district_reference.csv")
OUT_CSV     = Path("pipeline_out/audits/dapoer_vs_panel_real.csv")

# DAPOER province code prefix → our panel's province_canonical
# ID.KU (Kalimantan Utara, split 2012) → KALIMANTAN TIMUR: 2000-vintage panel uses KalTim for all KalUt districts
PROV_CODE_MAP = {
    "ID.AC": "ACEH",
    "ID.BA": "BALI",
    "ID.BB": "KEPULAUAN BANGKA BELITUNG",
    "ID.BE": "BENGKULU",
    "ID.BT": "BANTEN",
    "ID.GO": "GORONTALO",
    "ID.IB": "PAPUA BARAT",
    "ID.JA": "JAMBI",
    "ID.JI": "JAWA TIMUR",
    "ID.JK": "DKI JAKARTA",
    "ID.JR": "JAWA BARAT",
    "ID.JT": "JAWA TENGAH",
    "ID.KB": "KALIMANTAN BARAT",
    "ID.KI": "KALIMANTAN TIMUR",
    "ID.KR": "KEPULAUAN RIAU",
    "ID.KS": "KALIMANTAN SELATAN",
    "ID.KT": "KALIMANTAN TENGAH",
    "ID.KU": "KALIMANTAN TIMUR",
    "ID.LA": "LAMPUNG",
    "ID.MA": "MALUKU",
    "ID.MU": "MALUKU UTARA",
    "ID.NB": "NUSA TENGGARA BARAT",
    "ID.NT": "NUSA TENGGARA TIMUR",
    "ID.PA": "PAPUA",
    "ID.RI": "RIAU",
    "ID.SB": "SUMATERA BARAT",
    "ID.SE": "SULAWESI SELATAN",
    "ID.SG": "SULAWESI TENGGARA",
    "ID.SL": "SUMATERA SELATAN",
    "ID.SR": "SULAWESI BARAT",
    "ID.ST": "SULAWESI TENGAH",
    "ID.SU": "SUMATERA UTARA",
    "ID.SW": "SULAWESI UTARA",
    "ID.YO": "DI YOGYAKARTA",
}

# DAPOER series code → (panel table_type, panel base_year str, panel oil_excluded str)
SERIES_MAP = {
    "NA.GDP.INC.OG.KR":       ("real",    "2000.0", "False"),
    "NA.GDP.EXC.OG.KR":       ("real",    "2000.0", "True"),
    "NA.GDP.INC.OG.CR":       ("nominal", "",       "False"),
    "NA.GDP.EXC.OG.CR":       ("nominal", "",       "True"),
    "NA.GDP.INC.OG.SNA08.KR": ("real",    "2010.0", "False"),
}

SERIES_LABEL = {
    "NA.GDP.INC.OG.KR":       "real_2000_incl_oil",
    "NA.GDP.EXC.OG.KR":       "real_2000_excl_oil",
    "NA.GDP.INC.OG.CR":       "nominal_incl_oil",
    "NA.GDP.EXC.OG.CR":       "nominal_excl_oil",
    "NA.GDP.INC.OG.SNA08.KR": "real_2010_incl_oil",
}

# ── 1. Build province-aware district reference ────────────────────────────────

# ref_by_province: province_canonical → [(atype, district_name_2000, district_id), ...]
# Uses district_name_2000 directly — avoids did_to_key province-prefix pollution.
# Skips post-2000 children (province_canonical='') — they live in child_ref below.
ref_by_province = defaultdict(list)
parent_province = {}  # district_id → province_canonical, for child lookup
with open(DIST_REF, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        did  = row["district_id"]
        prov = row["province_canonical"]
        raw  = row["admin_type"].lower()
        atype = "KAB" if raw == "kabupaten" else ("KOTA" if raw == "kota" else None)
        if prov:
            parent_province[did] = prov
            ref_by_province[prov].append((atype, row["district_name_2000"], did))

# ── 2. DAPOER location name parser ───────────────────────────────────────────

_COMMA_ADM = re.compile(r',\s*(Kab\.|Kota\.?)\s*$', re.I)
_PUNC      = re.compile(r'[^A-Z0-9 ]')

def parse_dapoer_loc(loc):
    m = _COMMA_ADM.search(loc)
    if not m:
        return None, None
    suffix = m.group(1).upper().rstrip(".")
    atype = "KOTA" if "KOTA" in suffix else "KAB"
    base = _PUNC.sub(" ", loc[:m.start()].strip().upper())
    base = re.sub(r"\s+", " ", base).strip()
    return atype, base

def best_match(atype, base, province):
    """Exact normalized-name match within province. No suffix fallback."""
    candidates = ref_by_province.get(province, [])
    base_ns = base.replace(" ", "")
    # Pass 1: same admin type
    for r_atype, r_name, did in candidates:
        if r_atype == atype and r_name.replace(" ", "") == base_ns:
            return did
    # Pass 2: any admin type (handles entries where admin_type is blank in reference)
    for r_atype, r_name, did in candidates:
        if r_name.replace(" ", "") == base_ns:
            return did
    return None

# ── 3. Parse DAPOER wide → long, build per-series location lookup ─────────────

_YR_COL = re.compile(r'^(\d{4}) \[YR\d{4}\]$')

# dapoer_data[(series_code, location_name, year)] = value_idr_rupiah
dapoer_data = {}
# loc_info[location_name] = (province_code_prefix, province_canonical)
loc_info    = {}

unmatched_locs = set()

with open(DAPOER_CSV, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    year_cols = {col: _YR_COL.match(col).group(1)
                 for col in reader.fieldnames if _YR_COL.match(col)}

    for row in reader:
        series = row["Series Code"]
        if series not in SERIES_MAP:
            continue
        loc  = row["Provinces Name"]
        code = row["Provinces Code"]

        # district rows only
        atype, base = parse_dapoer_loc(loc)
        if atype is None:
            continue

        # derive province
        prov_prefix = ".".join(code.split(".")[:2])  # e.g. ID.BA.BD → ID.BA
        province    = PROV_CODE_MAP.get(prov_prefix)
        if province is None:
            unmatched_locs.add(loc)
            continue

        loc_info[loc] = (prov_prefix, province)

        for col, year in year_cols.items():
            val_str = row[col].strip()
            if val_str in ("", "..", "NA"):
                continue
            try:
                val_idr = float(val_str) * 1e6  # IDR million → rupiah
            except ValueError:
                continue
            dapoer_data[(series, loc, year)] = val_idr

print(f"DAPOER data points loaded: {len(dapoer_data)}")

# ── 3b. Build child reference (first panel pass, post-2000 children only) ─────

child_ref_by_province = defaultdict(list)  # province → [(name_ns, district_id), ...]
seen_children = set()
with open(PANEL_TOTAL, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["is_post2000_child"] != "True":
            continue
        did = row["district_id"]
        if not did:  # post-2000 children have no district_id in 2000-vintage panel
            continue
        if did in seen_children:
            continue
        seen_children.add(did)
        prov = parent_province.get(row["parent_district_id"], "")
        if not prov:
            continue
        nm = row["region_name_corrected"]
        child_ref_by_province[prov].append((nm.replace(" ", ""), did))

print(f"Post-2000 child districts in child reference: {sum(len(v) for v in child_ref_by_province.values())}")

def best_match_child(base, province):
    """Exact normalized match against post-2000 children in full panel."""
    base_ns = base.replace(" ", "")
    for nm_ns, did in child_ref_by_province.get(province, []):
        if nm_ns == base_ns:
            return did
    return None

# ── 4. Match each location to a district_id ───────────────────────────────────

loc_to_did = {}

child_matched_locs = {}   # loc → child district_id (post-2000 children found in panel)
truly_unmatched    = []   # loc that matched neither reference nor child panel

for loc, (prov_prefix, province) in loc_info.items():
    atype, base = parse_dapoer_loc(loc)
    did = best_match(atype, base, province)
    if did:
        loc_to_did[loc] = did
    else:
        child_did = best_match_child(base, province)
        if child_did:
            child_matched_locs[loc] = child_did
        else:
            truly_unmatched.append((loc, province, base))

n_district_locs = len(loc_info)
print(f"District locations: {n_district_locs}")
print(f"Matched (2000-vintage): {len(loc_to_did)}")
print(f"Child-matched:          {len(child_matched_locs)}")
print(f"Truly unmatched:        {len(truly_unmatched)}")
if truly_unmatched:
    print("  (truly unmatched — e.g. Lingga, Togean Islands, etc.)")
    for loc, prov, base in truly_unmatched[:20]:
        print(f"    [{prov}] {loc!r}")
    if len(truly_unmatched) > 20:
        print(f"    ... and {len(truly_unmatched) - 20} more")

# spot-check the 4 formerly bad joins
print("\nSpot-check (formerly bad joins — should now be unmatched or correctly matched):")
for check in ["Lingga, Kab.", "Pariaman, Kota", "Banjar, Kota", "Samosir, Kab."]:
    print(f"  {check!r:30s} → {loc_to_did.get(check, 'UNMATCHED (correct)')}")

# spot-check known good matches
print("\nSpot-check (should match):")
for check in ["Banda Aceh, Kota", "Medan, Kota", "Bogor, Kab.", "Siak, Kab.",
              "Batang Hari, Kab.", "Banjarmasin, Kota", "Kota Baru, Kab."]:
    print(f"  {check!r:30s} → {loc_to_did.get(check, 'UNMATCHED')}")

# ── 5. Load panel ─────────────────────────────────────────────────────────────

# panel[(district_id, year, table_type, base_year, oil_excluded)] = value_standardized
panel = {}
with open(PANEL_TOTAL, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        did = row["district_id"]
        if not did:
            continue
        val = row["value_standardized"]
        if not val:
            continue
        key = (did, row["year"], row["table_type"], row["base_year"], row["oil_excluded"])
        panel[key] = float(val)

print(f"\nPanel rows loaded: {len(panel)}")

# ── 6. Compare ────────────────────────────────────────────────────────────────

results = []

for (series, loc, year), dval in dapoer_data.items():
    did = loc_to_did.get(loc)
    if not did:
        continue
    table_type, base_year, oil_excluded = SERIES_MAP[series]
    pval = panel.get((did, year, table_type, base_year, oil_excluded))
    if pval is None:
        continue

    pct = (dval / pval - 1) * 100
    prov_prefix, province = loc_info[loc]
    results.append({
        "dapoer_series":    series,
        "series_label":     SERIES_LABEL[series],
        "district_id":      did,
        "location_name":    loc,
        "province":         province,
        "year":             year,
        "dapoer_idr":       dval,
        "panel_idr":        pval,
        "pct_diff":         round(pct, 2),
        "abs_diff_gt20":    abs(pct) > 20,
    })

print(f"\nComparable district-year-series observations: {len(results)}")

# ── 7. Summary by series ──────────────────────────────────────────────────────

by_series = defaultdict(list)
for r in results:
    by_series[r["dapoer_series"]].append(r)

print()
print(f"{'Series':<28} {'label':<22} {'n':>6} {'agree≤1%':>9} {'>20%':>6} {'>50%':>6} {'>100%':>7}")
print("-" * 90)
for series in SERIES_MAP:
    rows = by_series[series]
    if not rows:
        print(f"  {series:<26} {SERIES_LABEL[series]:<22} {'—':>6}")
        continue
    n        = len(rows)
    agree    = sum(1 for r in rows if abs(r["pct_diff"]) <= 1)
    gt20     = sum(1 for r in rows if abs(r["pct_diff"]) > 20)
    gt50     = sum(1 for r in rows if abs(r["pct_diff"]) > 50)
    gt100    = sum(1 for r in rows if abs(r["pct_diff"]) > 100)
    print(f"  {series:<26} {SERIES_LABEL[series]:<22} {n:>6} {agree:>9} {gt20:>6} {gt50:>6} {gt100:>7}")

# ── 8. Top discrepancies per series ───────────────────────────────────────────

for series in SERIES_MAP:
    flags = sorted(
        [r for r in by_series[series] if abs(r["pct_diff"]) > 20],
        key=lambda r: abs(r["pct_diff"]), reverse=True
    )
    if not flags:
        continue
    print(f"\n  {SERIES_LABEL[series]}  — top discrepancies (>{20}%):")
    print(f"    {'district_id':<45} {'yr':>4}  {'dapoer_bn':>10}  {'panel_bn':>10}  {'diff%':>8}")
    print("    " + "-" * 80)
    for r in flags[:30]:
        print("    %-45s %4s  %10.1f  %10.1f  %+8.1f%%" % (
            r["district_id"], r["year"],
            r["dapoer_idr"] / 1e9, r["panel_idr"] / 1e9, r["pct_diff"]))

# ── 8b. Child comparison section ─────────────────────────────────────────────
# DAPOER locations that matched a post-2000 panel child (not in 2000-vintage ref)

child_results = []
for (series, loc, year), dval in dapoer_data.items():
    child_did = child_matched_locs.get(loc)
    if not child_did:
        continue
    table_type, base_year, oil_excluded = SERIES_MAP[series]
    pval = panel.get((child_did, year, table_type, base_year, oil_excluded))
    if pval is None:
        continue
    pct = (dval / pval - 1) * 100
    prov_prefix, province = loc_info[loc]
    child_results.append({
        "district_id":   child_did,
        "location_name": loc,
        "series_label":  SERIES_LABEL[series],
        "year":          year,
        "dapoer_bn":     round(dval / 1e9, 1),
        "panel_bn":      round(pval / 1e9, 1),
        "pct_diff":      round(pct, 2),
    })

if child_results:
    print(f"\nChild comparison ({len(child_results)} obs across {len(child_matched_locs)} child districts):")
    print(f"  These are post-2000 splits — DAPOER uses current boundaries, panel uses parent territory.")
    child_gt20 = [r for r in child_results if abs(r["pct_diff"]) > 20]
    print(f"  |diff|>20%: {len(child_gt20)}")
else:
    print(f"\nNo child comparisons matched.")

# ── 9. Write output ───────────────────────────────────────────────────────────

if results:
    fieldnames = list(results[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: (r["dapoer_series"], r["district_id"], r["year"])))
    print(f"\nFull comparison written: {OUT_CSV}  ({len(results)} rows)")
else:
    print("\nNo comparable rows — check paths and series mapping.")
