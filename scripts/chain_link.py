#!/usr/bin/env python3
"""
chain_link.py — Produce a chain-linked real PDRB series from the full panel.

Run after build_panel.py. Reads panel_pdrb_total_native.csv and emits
panel_pdrb_chained_2000bounds.csv.

There is no per-capita chained panel: BPS per-capita publications carry no
real series, so chain-linking does not apply (see the PAIRS list below). To
obtain real per-capita levels in 2010 prices, divide the chain-linked total
panel by district population.

Algorithm
---------
Link year: 2011 (first year where both real/2000 and real/2010 overlap).

  link_ratio[district] = real_2010[2011] / real_2000[2011]

  chain_linked[year < 2011] = real_2000[year] * link_ratio  (is_backcast=True)
  chain_linked[year >= 2011] = real_2010[year]               (is_backcast=False)

Scope
-----
- oil_excluded=False only (real/2010 has no oil_excluded rows)
- Non-null district_id only (post-2000 split children with null id excluded)
- table_type="real_chained", base_year="2010.0"
- Extra columns: link_year, link_ratio, is_backcast, ratio_drift_flag

Caveats (document in data guide)
-------------------------------
- Pre-2011 values are synthetic: they preserve real/2000 growth rates but
  levels do not correspond to any BPS publication.
- District values do not sum to provincial or national aggregates.
- The link_ratio (median ~3.3, range ~1.9-9.3) primarily reflects price
  rebasing from 2000 to 2010 prices; SNA1993→SNA2008 scope change is a
  second-order component absorbed into the ratio.
- ratio_drift_flag=True means the 2012 implied ratio deviates >5% from the
  2011 link ratio — the two series disagree on 2011-2012 growth.
- Districts present in only one series carry link_ratio="" (no backcast or
  no forward segment respectively).
- Boundary changes within the real/2000 window are inherited by the
  chain-linked series.
"""

from pathlib import Path

import pandas as pd

LINK_YEAR = 2011
VALIDATE_YEAR = 2012
DRIFT_THRESHOLD = 0.05

PAIRS = [
    (
        Path("outputs/panel_pdrb_total_native.csv"),
        Path("outputs/panel_pdrb_chained_2000bounds.csv"),
        "total",
    ),
    # Capita panel is nominal only — BPS per-capita publications do not carry a
    # real series. Chain-linking does not apply. To get real per-capita in 2010
    # prices, divide the chain-linked total panel by district population.
]


def _pivot_year(df: pd.DataFrame, year: int) -> pd.Series:
    """Return Series[district_id → float value] for a given year."""
    rows = df[df["year"] == str(year)]
    if rows.empty:
        return pd.Series(dtype=float)
    dupes = rows["district_id"].duplicated()
    if dupes.any():
        print(
            f"  WARNING: {dupes.sum()} duplicate district_id at year {year}; "
            "keeping first occurrence"
        )
        rows = rows[~dupes]
    return pd.to_numeric(rows.set_index("district_id")["value_standardized"], errors="coerce")


def compute_chain(panel: pd.DataFrame) -> pd.DataFrame:
    """Chain-link the panel and return the chained DataFrame."""
    is_real2000 = (
        (panel["table_type"] == "real")
        & (panel["base_year"] == "2000.0")
        & (panel["oil_excluded"] == "False")
        & panel["district_id"].ne("")
    )
    is_real2010 = (
        (panel["table_type"] == "real")
        & (panel["base_year"] == "2010.0")
        & (panel["oil_excluded"] == "False")
        & panel["district_id"].ne("")
    )

    r2000 = panel[is_real2000].copy()
    r2010 = panel[is_real2010].copy()

    # --- Compute link ratios ---
    link2000 = _pivot_year(r2000, LINK_YEAR)
    link2010 = _pivot_year(r2010, LINK_YEAR)
    link_ratio = (link2010 / link2000).rename("link_ratio")

    # --- Compute drift flag (validation year) ---
    val2000 = _pivot_year(r2000, VALIDATE_YEAR)
    val2010 = _pivot_year(r2010, VALIDATE_YEAR)
    val_ratio = val2010 / val2000
    raw_drift = (val_ratio / link_ratio - 1).abs()
    ratio_drift_flag = (raw_drift > DRIFT_THRESHOLD).where(
        link_ratio.notna() & val2000.notna() & val2010.notna()
    ).rename("ratio_drift_flag")

    valid_ids = link_ratio.dropna().index

    ratio_map = link_ratio.to_dict()
    drift_map = ratio_drift_flag.to_dict()

    def fmt_ratio(did: str) -> str:
        v = ratio_map.get(did)
        return "" if v is None or pd.isna(v) else str(round(v, 6))

    def fmt_drift(did: str) -> str:
        v = drift_map.get(did)
        return "" if v is None or pd.isna(v) else str(v)

    # --- Backcast: pre-LINK_YEAR real/2000 rows scaled by link_ratio ---
    backcast_mask = r2000["district_id"].isin(valid_ids) & (
        pd.to_numeric(r2000["year"], errors="coerce") < LINK_YEAR
    )
    backcast = r2000[backcast_mask].copy()

    raw_vals = pd.to_numeric(backcast["value_standardized"], errors="coerce")
    scaled = raw_vals * backcast["district_id"].map(ratio_map)
    backcast["value_standardized"] = scaled.apply(
        lambda x: "" if pd.isna(x) else f"{x:.2f}"
    )
    backcast["table_type"] = "real_chained"
    backcast["base_year"] = "2010.0"
    backcast["is_backcast"] = "True"
    backcast["link_year"] = str(LINK_YEAR)
    backcast["link_ratio"] = backcast["district_id"].map(fmt_ratio)
    backcast["ratio_drift_flag"] = backcast["district_id"].map(fmt_drift)

    # --- Forward: real/2010 rows for year >= LINK_YEAR ---
    forward_mask = pd.to_numeric(r2010["year"], errors="coerce") >= LINK_YEAR
    forward = r2010[forward_mask].copy()
    forward["table_type"] = "real_chained"
    forward["is_backcast"] = "False"
    forward["link_year"] = str(LINK_YEAR)
    forward["link_ratio"] = forward["district_id"].map(fmt_ratio)
    forward["ratio_drift_flag"] = forward["district_id"].map(fmt_drift)

    chained = pd.concat([backcast, forward], ignore_index=True)
    chained = chained.sort_values(
        ["district_id", "year", "table_type"], na_position="last"
    ).reset_index(drop=True)
    return chained


def main() -> None:
    for in_path, out_path, label in PAIRS:
        print(f"\n=== {label} ===")
        panel = pd.read_csv(in_path, dtype=str, keep_default_na=False)
        chained = compute_chain(panel)

        n_districts = chained["district_id"].nunique()
        n_backcast = (chained["is_backcast"] == "True").sum()
        n_forward = (chained["is_backcast"] == "False").sum()
        n_drift = (chained["ratio_drift_flag"] == "True").sum()
        ratios = pd.to_numeric(chained["link_ratio"], errors="coerce").dropna()

        print(f"  Districts:        {n_districts}")
        print(f"  Backcast rows:    {n_backcast}")
        print(f"  Forward rows:     {n_forward}")
        print(
            f"  Link ratio — median: {ratios.median():.3f}, "
            f"range: {ratios.min():.2f}–{ratios.max():.2f}"
        )
        print(f"  Drift-flagged rows (>{DRIFT_THRESHOLD*100:.0f}%): {n_drift}")

        # Districts only in real/2000 (no forward)
        only_2000 = set(
            panel.loc[
                (panel["table_type"] == "real")
                & (panel["base_year"] == "2000.0")
                & panel["district_id"].ne(""),
                "district_id",
            ].unique()
        ) - set(
            panel.loc[
                (panel["table_type"] == "real")
                & (panel["base_year"] == "2010.0")
                & panel["district_id"].ne(""),
                "district_id",
            ].unique()
        )
        # Districts only in real/2010 (no backcast)
        only_2010 = set(
            panel.loc[
                (panel["table_type"] == "real")
                & (panel["base_year"] == "2010.0")
                & panel["district_id"].ne(""),
                "district_id",
            ].unique()
        ) - set(
            panel.loc[
                (panel["table_type"] == "real")
                & (panel["base_year"] == "2000.0")
                & panel["district_id"].ne(""),
                "district_id",
            ].unique()
        )
        if only_2000:
            print(f"  Only real/2000 (no forward segment): {sorted(only_2000)}")
        if only_2010:
            print(f"  Only real/2010 (no backcast):        {sorted(only_2010)}")

        chained.to_csv(out_path, index=False)
        print(f"  → {out_path}")


if __name__ == "__main__":
    main()
