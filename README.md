# Subnational GDP for Indonesia: A District-Level Panel, 1996–2025

*Nayfa Johan and Russell Hillberry — Purdue University*

Built from 21 archival BPS publications and harmonized to 2000-vintage administrative boundaries, the panel covers 350+ consistently-defined districts across three decades of administrative splits (*pemekaran*). All source files, crosswalks, scripts, and outputs are included for full replication.

INDO-DAPOER (World Bank) covers only 2000–2020 with no per-capita series; this dataset extends to 1996 with per-capita and a fully reproducible pipeline from archival BPS PDFs.

## Panels

| File | Series | Rows | Districts | Years |
| --- | --- | --- | --- | --- |
| `outputs/panel_pdrb_total_2000bounds.csv` | total PDRB, harmonized | 23,743 | 361 | 1996–2025 |
| `outputs/panel_pdrb_capita_2000bounds.csv` | per-capita PDRB, harmonized | 10,400 | 363 | 1996–2025 |
| `outputs/panel_pdrb_chained_2000bounds.csv` | chain-linked real (2010 base) | 8,315 | 348 | 2002–2025 |
| `outputs/panel_pdrb_total_native.csv` | total PDRB, unharmonized | 31,035 | all incl. post-2000 children | 1996–2025 |
| `outputs/panel_pdrb_capita_native.csv` | per-capita PDRB, unharmonized | 13,894 | all incl. post-2000 children | 1996–2025 |

See `docs/codebook.md` for panel selection and column definitions. (2024–25 provisional as of deposit, Aug 2026.)

## Quick start

```python
import pandas as pd
df = pd.read_csv("outputs/panel_pdrb_total_2000bounds.csv")

# Nominal PDRB, confirmed figures only
# is_pre_split_aggregate rows repeat a child district's value inside its
# pre-split parent — drop them before any aggregation to avoid double-counting
nom = df[
    (df.table_type == "nominal") &
    (df.is_provisional == False) &
    (df.is_pre_split_aggregate == False)
]
```

Values in `value_standardized` are in bare IDR. Divide by `1e6` to match the DAPOER convention (IDR million).

## Documentation

- `docs/codebook.md` — column definitions, pipeline stages, limitations, and DAPOER validation
- `docs/research_log.md` — internal methodology log: design decisions, key findings, and pipeline development history (GitHub only; not in the PURR deposit)

## Reproducing the panels

```bash
pip install -r requirements.txt
bash run_all.sh
```

This runs the pipeline and writes SHA-256 checksums of the five output files. PDF parsing (requires a paid vision API) does not re-run; the 21 parsed stage-1 CSVs are shipped in `parsed_csvs/`. See `CONTRIBUTING.md`.

## Citation

> Johan, Nayfa and Russell Hillberry (2026). *Subnational GDP for Indonesia: A District-Level Panel, 1996–2025.* Purdue University Research Repository (PURR). DOI: [to be assigned on deposit]

## License

Data and documentation: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Code: MIT. See `LICENSE`.
