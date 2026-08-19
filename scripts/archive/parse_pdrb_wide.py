"""
parse_pdrb_wide.py — Wide-format variant of parse_pdrb.py.

Claude outputs one row per district (years as columns), which matches the source
PDF layout and cuts output tokens ~85%. Python melts back to long format so the
final CSV is identical in structure to parse_pdrb.py output.

Usage:
    python scripts/parse_pdrb_wide.py --input raw/pdf/PDRB_2018-2022.pdf --output pipeline_out/trial_wide/

Env:
    ANTHROPIC_API_KEY  required unless passed via --api-key
"""

import argparse
import base64
import hashlib
import io
import os
import re
import sys
import time
from pathlib import Path

import anthropic
import pandas as pd
import pdfplumber
from pypdf import PdfReader, PdfWriter


# ── constants ────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 32000

TEXT_DENSITY_THRESHOLD = 100
SAMPLE_PAGES = 5

PAGES_PER_TEXT_CHUNK = 10   # wide format is token-light; back to 10 pages
PAGES_PER_VISION_CHUNK = 5

# Final long-format columns (same as parse_pdrb.py — pipeline compatibility)
REQUIRED_COLUMNS = [
    "province_name",
    "regency_code",
    "region_name_raw",
    "name_flag",
    "year",
    "year_flag",
    "value",
    "value_flag",
    "table_header_raw",
    "table_header_english",
    "page_number",
    "table_number",
    "raw_text_hash",
]


PARSE_PROMPT = """\
Parse all PDRB tables from the content below. Output three sections in order.

─────────────────────────────────────────
SECTION 1 — HEADERS (one row per table)
─────────────────────────────────────────
Output a line containing exactly: ## HEADERS
Then a CSV with these columns:
table_number,page_number,table_header_raw,table_header_english

Rules:
- table_number: sequential integer within this chunk, starting at 1
- page_number: bare integer ONLY — the N from the === PAGE N === marker (e.g. 3); no text
- table_header_raw: verbatim full Indonesian table title as printed
- table_header_english: verbatim full English table title as printed; empty if none

─────────────────────────────────────────
SECTION 2 — DATA (one row per district)
─────────────────────────────────────────
Output a line containing exactly: ## DATA
Then a CSV with these columns:
province_name,regency_code,region_name_raw,name_flag,<year_1>,<year_2>,...,table_number

Rules:
- province_name: verbatim province name as printed
- regency_code: numeric BPS prefix; empty for Jumlah/province-total rows
- region_name_raw: full region name verbatim
- name_flag: verbatim footnote marker on region name (e.g. "*"); empty if none
- year columns: use the exact year headers from the PDF including footnote markers
  (e.g. 2018, 2019, 2020, 2021*, 2022**); one column per year in the table
- values: exactly as printed, including any corruption artifacts (stray characters,
  double periods, extra spaces); do not interpret, clean, or correct — capture verbatim
  even if the value looks wrong; empty if cell is blank
- table_number: matches the table_number in HEADERS
- Include Jumlah/province-total rows; leave regency_code empty for these

─────────────────────────────────────────
SECTION 3 — ANOMALIES
─────────────────────────────────────────
Output a line containing exactly: ## ANOMALIES
List each anomaly as: page <n>, table <n>: <description>
Flag: missing/ambiguous units, unparseable values, unexpected structure

General rules:
- No preamble, no markdown fences, no text outside the three sections
- Missing values → empty string (never NULL, NaN, or NA)
- Capture everything verbatim — do not interpret, classify, or correct
"""


# ── PDF helpers (identical to parse_pdrb.py) ─────────────────────────────────

def is_text_pdf(pdf_path: Path) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        sample = pdf.pages[:SAMPLE_PAGES]
        total_chars = sum(len(p.extract_text() or "") for p in sample)
        avg = total_chars / max(len(sample), 1)
    return avg >= TEXT_DENSITY_THRESHOLD


def is_doubled_text(text: str) -> bool:
    """Detect the double-printing artifact where every char is printed twice.

    In affected PDFs, pdfplumber extracts both copies: 'PDRB' → 'PPDDRRBBB'.
    Heuristic: if >40% of adjacent alpha char pairs are identical, it's doubled.
    """
    alpha_pairs = [(a, b) for a, b in zip(text, text[1:]) if a.isalpha() and b.isalpha()]
    if len(alpha_pairs) < 20:
        return False
    doubled = sum(1 for a, b in alpha_pairs if a == b)
    return doubled / len(alpha_pairs) > 0.40


def deduplicate_chars(text: str) -> str:
    """Collapse consecutive identical characters: 'PPDDRRBBB' → 'PDRB'."""
    return re.sub(r'(.)\1', r'\1', text)


def has_doubled_text(pdf_path: Path) -> bool:
    """Return True if this PDF has the double-printing artifact (auto-switch to vision)."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:SAMPLE_PAGES]:
            text = page.extract_text() or ""
            if len(text) > 100 and is_doubled_text(text):
                return True
    return False


def text_chunks(pdf_path: Path) -> list[dict]:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages
        for i in range(0, len(pages), PAGES_PER_TEXT_CHUNK):
            batch = pages[i : i + PAGES_PER_TEXT_CHUNK]
            page_nums = list(range(i + 1, i + 1 + len(batch)))
            parts = []
            for num, page in zip(page_nums, batch):
                text = page.extract_text() or ""
                parts.append(f"=== PAGE {num} ===\n{text}")
            chunks.append({"pages": page_nums, "text": "\n\n".join(parts)})
    return chunks


def pdf_page_range_b64(pdf_path: Path, start: int, end: int) -> str:
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for i in range(start - 1, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return base64.standard_b64encode(buf.getvalue()).decode()


def page_count(pdf_path: Path) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


# ── API calls (identical to parse_pdrb.py) ───────────────────────────────────

def call_api(client: anthropic.Anthropic, content: list) -> str:
    for attempt in range(3):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                text = stream.get_final_text()
                if stream.get_final_message().stop_reason == "max_tokens":
                    print("    WARNING: response truncated (hit max_tokens)")
            return text
        except anthropic.APIConnectionError as e:
            wait = 30 * (attempt + 1)
            print(f"    Connection error — waiting {wait}s… ({e})")
            time.sleep(wait)
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"    Rate limited — waiting {wait}s…")
            time.sleep(wait)
        except anthropic.APIError as e:
            print(f"    API error: {e}")
            time.sleep(10)
    raise RuntimeError("API call failed after 3 attempts")


def call_text(client: anthropic.Anthropic, text: str) -> str:
    return call_api(client, [{"type": "text", "text": PARSE_PROMPT + "\n\n" + text}])


def call_vision(client: anthropic.Anthropic, pdf_b64: str) -> str:
    return call_api(client, [
        {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
        },
        {"type": "text", "text": PARSE_PROMPT},
    ])


# ── response parsing ──────────────────────────────────────────────────────────

def parse_response(raw: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    sections = {"HEADERS": [], "DATA": [], "ANOMALIES": []}
    current = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "## HEADERS":
            current = "HEADERS"
        elif stripped == "## DATA":
            current = "DATA"
        elif stripped == "## ANOMALIES":
            current = "ANOMALIES"
        elif current and stripped:
            # strip markdown fences if model added them
            if not stripped.startswith("```"):
                sections[current].append(line)

    def read_csv(lines):
        if not lines:
            return pd.DataFrame()
        try:
            return pd.read_csv(io.StringIO("\n".join(lines)), dtype=str).fillna("")
        except Exception:
            return pd.DataFrame()

    headers_df = read_csv(sections["HEADERS"])
    data_df = read_csv(sections["DATA"])
    anomalies = [l.strip() for l in sections["ANOMALIES"] if l.strip()]
    return headers_df, data_df, anomalies


def melt_to_long(headers_df: pd.DataFrame, data_df: pd.DataFrame) -> list[dict]:
    if data_df.empty:
        return []

    year_pattern = re.compile(r"^\d{4}")
    year_cols = [c for c in data_df.columns if year_pattern.match(str(c).strip())]
    id_cols = [c for c in data_df.columns if c not in year_cols]

    if not year_cols:
        return []

    melted = data_df.melt(id_vars=id_cols, value_vars=year_cols,
                          var_name="year_raw", value_name="value")

    melted["year"] = melted["year_raw"].str.extract(r"^(\d{4})")
    melted["year_flag"] = melted["year_raw"].str.extract(r"^\d{4}(.+)$").fillna("")
    melted["value_flag"] = ""
    melted = melted.drop(columns=["year_raw"])

    # recover table_number for short rows (Claude omits trailing pipe on rows with empty trailing fields)
    if "table_number" in melted.columns:
        melted["table_number"] = melted["table_number"].replace("", pd.NA).ffill()

    # join table headers
    if not headers_df.empty and "table_number" in melted.columns:
        melted = melted.merge(headers_df, on="table_number", how="left")

    # normalize to REQUIRED_COLUMNS
    rows = []
    for _, row in melted.iterrows():
        clean = {col: str(row.get(col, "") or "").strip() for col in REQUIRED_COLUMNS if col != "raw_text_hash"}
        content = "|".join(clean.get(c, "") for c in REQUIRED_COLUMNS if c != "raw_text_hash")
        clean["raw_text_hash"] = hashlib.md5(content.encode()).hexdigest()[:12]
        rows.append(clean)

    return rows


# ── resume helpers (identical to parse_pdrb.py) ───────────────────────────────

def completed_pages(csv_path: Path) -> set[int]:
    if not csv_path.exists():
        return set()
    try:
        df = pd.read_csv(csv_path)
        pages = pd.to_numeric(df["page_number"], errors="coerce").dropna().astype(int)
        result = set(pages.unique())
        if not result:
            print("  WARNING: existing CSV has no valid integer page_numbers — treating as fresh run")
        return result
    except Exception:
        return set()


def next_csv_path(csv_dir: Path, stem: str) -> Path:
    base = csv_dir / f"{stem}_wide.csv"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = csv_dir / f"{stem}_wide_{n}.csv"
        if not candidate.exists():
            return candidate
        n += 1


# ── main parse loop ───────────────────────────────────────────────────────────

def parse_pdf(pdf_path: Path, client: anthropic.Anthropic,
              csv_out: Path, done_pages: set[int],
              max_pages: int | None = None,
              force_vision: bool = False) -> tuple[int, list[str]]:
    all_anomalies: list[str] = []
    total_rows = 0
    write_header = not csv_out.exists()

    text_based = is_text_pdf(pdf_path) and not force_vision and not has_doubled_text(pdf_path)
    print(f"  Mode: {'text' if text_based else 'vision (image-scanned)'}")

    if text_based:
        chunks = text_chunks(pdf_path)
        if max_pages:
            chunks = [c for c in chunks if c["pages"][0] <= max_pages]
        iterator = enumerate(chunks, 1)
        def get_raw(chunk): return call_text(client, chunk["text"])
        def chunk_pages(chunk): return set(chunk["pages"])
        def label(i, chunk):
            p0, p1 = chunk["pages"][0], chunk["pages"][-1]
            return f"pages {p0}–{p1}", len(chunks)
    else:
        n = page_count(pdf_path)
        if max_pages:
            n = min(n, max_pages)
        chunks = list(range(1, n + 1, PAGES_PER_VISION_CHUNK))
        iterator = enumerate(chunks, 1)
        def get_raw(start):
            end = min(start + PAGES_PER_VISION_CHUNK - 1, n)
            return call_vision(client, pdf_page_range_b64(pdf_path, start, end))
        def chunk_pages(start): return set(range(start, min(start + PAGES_PER_VISION_CHUNK, n + 1)))
        def label(i, start):
            end = min(start + PAGES_PER_VISION_CHUNK - 1, n)
            return f"pages {start}–{end} of {n}", len(chunks)

    for i, chunk in iterator:
        lbl, total = label(i, chunk)
        if chunk_pages(chunk).issubset(done_pages):
            print(f"  Chunk {i}/{total} ({lbl}) — skipped (already done)")
            continue
        print(f"  Chunk {i}/{total} ({lbl})…")
        raw = get_raw(chunk)
        headers_df, data_df, anomalies = parse_response(raw)
        all_anomalies.extend(anomalies)
        rows = melt_to_long(headers_df, data_df)
        if rows:
            df_chunk = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
            df_chunk.to_csv(csv_out, mode="a", index=False, header=write_header)
            write_header = False
            total_rows += len(df_chunk)
            print(f"    {len(df_chunk)} rows → saved (total so far: {total_rows})")
        else:
            print(f"    no rows parsed")

    return total_rows, all_anomalies


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parse PDRB PDFs — wide format variant.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="pipeline_out")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Stop after this many pages (for spot-checks)")
    parser.add_argument("--force-vision", action="store_true",
                        help="Force vision (PDF image) mode even for text-based PDFs")
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("ANTHROPIC_API_KEY not set.")

    input_path = Path(args.input)
    pdfs = sorted(input_path.glob("*.pdf")) if input_path.is_dir() else [input_path]
    if not pdfs:
        sys.exit(f"No PDFs found at {input_path}")

    out = Path(args.output)
    csv_dir = out / "csvs"
    log_dir = out / "logs"
    csv_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic(api_key=args.api_key, timeout=600)

    for pdf_path in pdfs:
        print(f"\n── {pdf_path.name} ──")
        stem = pdf_path.stem
        log_out = log_dir / f"{stem}_anomalies.txt"
        err_path = log_dir / f"{stem}_error.txt"

        if args.resume:
            csv_out = csv_dir / f"{stem}_wide.csv"
            done = completed_pages(csv_out)
            if done:
                print(f"  Resuming — {len(done)} pages already done")
        else:
            csv_out = next_csv_path(csv_dir, stem)
            done = set()

        try:
            total_rows, anomalies = parse_pdf(pdf_path, client, csv_out, done, args.max_pages, args.force_vision)
            log_out.write_text("\n".join(anomalies) if anomalies else "No anomalies.")
            print(f"  → {csv_out} ({total_rows} rows, {len(anomalies)} anomalies logged)")
        except Exception as e:
            err_path.write_text(str(e))
            print(f"  ERROR: {e} (logged to {err_path})")


if __name__ == "__main__":
    main()
