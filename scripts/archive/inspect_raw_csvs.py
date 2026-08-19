# scripts/inspect_raw_csvs.py

from pathlib import Path
import pandas as pd

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

RAW_DIR = Path("raw/csv")
AUDIT_DIR = Path("audits")

AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------
# FIND CSV FILES
# --------------------------------------------------

csv_files = sorted(RAW_DIR.glob("*.csv"))

if not csv_files:
    raise FileNotFoundError(f"No CSV files found in {RAW_DIR}")

print("=" * 80)
print(f"FOUND {len(csv_files)} CSV FILES")
print("=" * 80)

# --------------------------------------------------
# STORAGE FOR COLUMN INVENTORY
# --------------------------------------------------

inventory_rows = []

# --------------------------------------------------
# INSPECT EACH FILE
# --------------------------------------------------

for file in csv_files:

    print("\n" + "=" * 80)
    print(f"FILE: {file.name}")
    print("=" * 80)

    try:
        df = pd.read_csv(file)

    except Exception as e:
        print(f"ERROR READING FILE: {e}")
        continue

    # --------------------------------------------------
    # BASIC INFO
    # --------------------------------------------------

    print(f"\nRows:    {len(df):,}")
    print(f"Columns: {len(df.columns)}")

    # --------------------------------------------------
    # COLUMN INFO
    # --------------------------------------------------

    print("\nCOLUMN SUMMARY")
    print("-" * 80)

    for col in df.columns:

        dtype = str(df[col].dtype)
        nulls = int(df[col].isna().sum())
        null_pct = round((nulls / len(df)) * 100, 2)

        # --------------------------------------------------
        # SAMPLE / EXAMPLE OBSERVATION
        # --------------------------------------------------

        non_null_values = df[col].dropna()

        example = (
            str(non_null_values.iloc[0])
            if len(non_null_values) > 0
            else "ALL NULL"
        )

        # truncate long values
        example = example[:77] + "..." if len(example) > 80 else example

        print(
            f"{col:<35} "
            f"dtype={dtype:<12} "
            f"nulls={nulls:<8} "
            f"({null_pct}%) "
            f"example={example}"
        )

        # --------------------------------------------------
        # REPLACE EXISTING ENTRY IF ALREADY PRESENT
        # --------------------------------------------------

        inventory_rows = [
            row for row in inventory_rows
            if not (
                row["file_name"] == file.name
                and row["column_name"] == col
            )
        ]

        inventory_rows.append({
            "file_name": file.name,
            "column_name": col,
            "dtype": dtype,
            "null_count": nulls,
            "null_pct": null_pct,
            "example_value": example
        })

    # --------------------------------------------------
    # SAMPLE ROWS
    # --------------------------------------------------

    print("\nSAMPLE ROWS")
    print("-" * 80)

    with pd.option_context(
        "display.max_columns", None,
        "display.width", 200
    ):
        print(df.head(5))

    # --------------------------------------------------
    # OPTIONAL: UNIQUE VALUE COUNTS
    # --------------------------------------------------

    print("\nLOW-CARDINALITY COLUMNS")
    print("-" * 80)

    for col in df.columns:

        nunique = df[col].nunique(dropna=True)

        if nunique <= 20:
            print(f"\n{col} ({nunique} unique values)")
            print(df[col].value_counts(dropna=False).head(20))

# --------------------------------------------------
# EXPORT COLUMN INVENTORY
# --------------------------------------------------

inventory_df = pd.DataFrame(inventory_rows)

inventory_path = AUDIT_DIR / "column_inventory.csv"

inventory_df.to_csv(inventory_path, index=False)

print("\n" + "=" * 80)
print("COLUMN INVENTORY SAVED")
print(f"{inventory_path}")
print("=" * 80)