# scripts/build_split_concordance.py
"""
Builds crosswalks/split_concordance.csv from pemekaran reference sources.

Logic:
- Primary source: pemekaran docx (most complete, 2001-2014 kabupaten/kota)
- Filters to post-2000 splits only (2000-vintage boundary target)
- Normalizes names to region_name_base format (strip KAB./KOTA prefix, uppercase)
- Resolves multi-generation splits transitively to 2000-vintage parent
- Cross-checks child names against region_name_base values in standardized files
"""

from pathlib import Path
from docx import Document
import pandas as pd
import re

CROSSWALK_DIR = Path("crosswalks")
STANDARDIZED_DIR = Path("standardized")
OUT_FILE = CROSSWALK_DIR / "split_concordance.csv"

PROVINCE_HEADERS = {
    'ACEH','SUMATERA UTARA','SUMATERA BARAT','RIAU','KEPULAUAN RIAU','JAMBI',
    'SUMATERA SELATAN','KEPULAUAN BANGKA BELITUNG','BENGKULU','LAMPUNG',
    'DKI JAKARTA','JAWA BARAT','BANTEN','JAWA TENGAH','DI YOGYAKARTA','JAWA TIMUR',
    'BALI','NUSA TENGGARA BARAT','NUSA TENGGARA TIMUR','KALIMANTAN BARAT',
    'KALIMANTAN TENGAH','KALIMANTAN SELATAN','KALIMANTAN TIMUR','KALIMANTAN UTARA',
    'SULAWESI UTARA','GORONTALO','SULAWESI TENGAH','SULAWESI BARAT','SULAWESI SELATAN',
    'SULAWESI TENGGARA','MALUKU','MALUKU UTARA','PAPUA','PAPUA BARAT',
    'PAPUA PEGUNUNGAN','PAPUA SELATAN','PAPUA TENGAH','PAPUA BARAT DAYA',
}


# Corrections: docx name (normalized) → standardized region_name_base
# Reasons: space formatting, docx typos, abbreviation differences, name changes
NAME_CORRECTIONS = {
    # space formatting
    'LABUHANBATU':               'LABUHAN BATU',
    'LABUHANBATU SELATAN':       'LABUHAN BATU SELATAN',
    'LABUHANBATU UTARA':         'LABUHAN BATU UTARA',
    'TULANGBAWANG':              'TULANG BAWANG',
    'TULANGBAWANG BARAT':        'TULANG BAWANG BARAT',
    # docx typos
    'BOLAANG MONGODOW':          'BOLAANG MONGONDOW',
    'HALMEHERA TENGAH':          'HALMAHERA TENGAH',
    # punctuation
    'FAK FAK':                   'FAK-FAK',
    'BAU BAU':                   'BAUBAU',
    # spelling variants
    'PADANGSIDIMPUAN':           'PADANG SIDEMPUAN',
    # abbreviation: KEPULAUAN → KEP.
    'KEPULAUAN ANAMBAS':         'KEP. ANAMBAS',
    'KEPULAUAN SIAU TAGULANDANG BIARO': 'KEP. SIAU TAGULANDANG BIARO',
    # name change: Pasangkayu renamed from Mamuju Utara in 2016;
    # BPS PDRB publications use MAMUJU UTARA throughout
    'PASANGKAYU':                'MAMUJU UTARA',
    # compound parent: Tambrauw split from both Sorong and Manokwari;
    # use Sorong as primary 2000-vintage parent
    'SORONG & MANOKWARI':        'SORONG',
}


def normalize_base(name):
    if pd.isna(name):
        return ''
    s = str(name).strip().upper()
    s = re.sub(r'^KABUPATEN\s+', '', s)
    s = re.sub(r'^KOTAMADYA\s+', '', s)
    s = re.sub(r'^KOTA\s+', '', s)
    s = re.sub(r'^KAB\.\s+', '', s)
    s = re.sub(r'^PROVINSI\s+', '', s)
    s = s.strip()
    return NAME_CORRECTIONS.get(s, s)


def parse_docx(path):
    doc = Document(path)
    t = doc.tables[0]
    rows = []
    current_province = None
    for row in t.rows[2:]:
        cells = [c.text.strip() for c in row.cells]
        nama = cells[1]
        if not nama:
            continue
        if nama.upper() in PROVINCE_HEADERS:
            current_province = nama.upper()
            continue
        if nama.upper().startswith('PROVINSI '):
            current_province = nama.upper().replace('PROVINSI ', '')
            continue
        year_match = re.search(r'(\d{4})', cells[5])
        year = int(year_match.group(1)) if year_match else None
        rows.append({
            'province':        current_province,
            'child_name_raw':  nama,
            'parent_name_raw': cells[2],
            'law_number':      cells[4],
            'date_raw':        cells[5],
            'year':            year,
        })
    return pd.DataFrame(rows)


def resolve_2000_parents(df):
    """
    Transitively resolve multi-generation splits.
    Any unit whose 2000-vintage parent was itself a post-2000 split
    gets traced back to the original 2000-vintage ancestor.
    """
    # Build direct child→parent map (base names, year)
    direct = {}
    for _, row in df.iterrows():
        direct[row['child_base']] = (row['parent_base'], row['year'])

    def trace(name, year_created):
        """Follow parent chain until we reach a unit that existed in 2000."""
        visited = set()
        current = name
        current_year = year_created
        while current in direct:
            if current in visited:
                break
            visited.add(current)
            parent, parent_year = direct[current]
            if parent_year is None or parent_year <= 2000:
                return parent
            current = parent
            current_year = parent_year
        return current

    df = df.copy()
    df['parent_base_2000'] = df.apply(
        lambda r: trace(r['child_base'], r['year']), axis=1
    )
    return df


def load_standardized_bases():
    """Collect all region_name_base values from standardized files."""
    bases = set()
    for fp in STANDARDIZED_DIR.glob("*.csv"):
        df = pd.read_csv(fp, usecols=['region_name_base', 'is_data_row'])
        bases.update(
            df.loc[df['is_data_row'] == True, 'region_name_base']
            .dropna()
            .unique()
        )
    return bases


def main():
    print("=" * 70)
    print("BUILDING SPLIT CONCORDANCE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Parse docx
    # ------------------------------------------------------------------
    docx_path = next(CROSSWALK_DIR.glob("*Pemekaran wilayah*.docx"))
    raw = parse_docx(docx_path)
    print(f"Docx rows parsed: {len(raw)}")

    # Exclude province-level splits (2022 Papua splits)
    raw = raw[~raw['child_name_raw'].str.upper().str.startswith('PROVINSI')]
    print(f"After excluding province-level splits: {len(raw)}")

    # Normalize names
    raw['child_base']  = raw['child_name_raw'].apply(normalize_base)
    raw['parent_base'] = raw['parent_name_raw'].apply(normalize_base)

    # Filter to post-2000 only
    post2000 = raw[raw['year'] >= 2001].copy()
    print(f"Post-2000 kabupaten/kota splits: {len(post2000)}")

    # ------------------------------------------------------------------
    # Resolve multi-generation splits
    # ------------------------------------------------------------------
    # Use full dataset (including pre-2001) to trace parent chains
    raw_all = raw.copy()
    raw_all['child_base']  = raw_all['child_name_raw'].apply(normalize_base)
    raw_all['parent_base'] = raw_all['parent_name_raw'].apply(normalize_base)

    post2000 = resolve_2000_parents(post2000)

    multi_gen = post2000[
        post2000['parent_base_2000'] != post2000['parent_base']
    ]
    print(f"Multi-generation splits resolved: {len(multi_gen)}")
    if len(multi_gen):
        print(multi_gen[['child_base','parent_base','parent_base_2000']].to_string(index=False))

    # ------------------------------------------------------------------
    # Cross-check against standardized files
    # ------------------------------------------------------------------
    std_bases = load_standardized_bases()

    post2000['in_standardized'] = post2000['child_base'].isin(std_bases)
    post2000['parent_in_standardized'] = post2000['parent_base_2000'].isin(std_bases)

    not_found = post2000[~post2000['in_standardized']]
    print(f"\nChild names not found in standardized files: {len(not_found)}")
    if len(not_found):
        print(not_found[['child_base','parent_base_2000','year']].to_string(index=False))

    parent_not_found = post2000[~post2000['parent_in_standardized']]
    print(f"Parent (2000-vintage) names not found in standardized: {len(parent_not_found)}")
    if len(parent_not_found):
        print(parent_not_found[['child_base','parent_base_2000','year']].to_string(index=False))

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    out = post2000[[
        'child_name_raw',
        'child_base',
        'parent_name_raw',
        'parent_base',
        'parent_base_2000',
        'province',
        'year',
        'law_number',
        'date_raw',
        'in_standardized',
        'parent_in_standardized',
    ]].sort_values(['province', 'year', 'child_base']).reset_index(drop=True)

    out.to_csv(OUT_FILE, index=False)
    print(f"\nSaved: {OUT_FILE}")
    print(f"Rows: {len(out)}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total post-2000 splits recorded:      {len(out)}")
    print(f"Children found in standardized files: {out['in_standardized'].sum()}")
    print(f"Children NOT found:                   {(~out['in_standardized']).sum()}")
    print(f"Parents found in standardized files:  {out['parent_in_standardized'].sum()}")
    print(f"Parents NOT found:                    {(~out['parent_in_standardized']).sum()}")
    print(f"\nYear distribution:")
    print(out['year'].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
