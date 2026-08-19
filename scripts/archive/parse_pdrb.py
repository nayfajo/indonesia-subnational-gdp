"""
parse_pdrb.py — Parse PDRB PDFs to long-format CSV using Claude API.

Usage:
    python scripts/parse_pdrb.py --input /path/to/pdfs --output pipeline_out/
    python scripts/parse_pdrb.py --input single_file.pdf --output pipeline_out/

Env:
    ANTHROPIC_API_KEY  required unless passed via --api-key

Install deps:
    pip install -r requirements_parser.txt
"""

import argparse
import base64
import csv
import hashlib
import io
import os
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

# avg chars/page below this threshold → treat PDF as image-scanned
TEXT_DENSITY_THRESHOLD = 100
SAMPLE_PAGES = 5        # pages to sample for density check

PAGES_PER_TEXT_CHUNK = 3
PAGES_PER_VISION_CHUNK = 5

CLAUDE_COLUMNS = [
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
]

REQUIRED_COLUMNS = CLAUDE_COLUMNS + ["raw_text_hash"]


PARSE_PROMPT = """\
Parse all PDRB tables from the content below into CSV rows.

Required columns — all must be present in this exact order:
province_name,regency_code,region_name_raw,name_flag,year,year_flag,value,value_flag,table_header_raw,table_header_english,page_number,table_number

Column rules:
- province_name: verbatim province name as printed
- regency_code: numeric BPS prefix at row start; empty for province-level aggregate rows (Jumlah/total rows)
- region_name_raw: full region name as printed, verbatim
- name_flag: verbatim footnote marker on region name cell (e.g. "*", "**"); empty if none
- year: integer year
- year_flag: verbatim footnote marker on year cell; empty if none
- value: numeric value exactly as printed, preserving Indonesian formatting (period = thousands separator, comma = decimal); do not round or reformat
- value_flag: verbatim footnote marker on value cell; empty if none
- table_header_raw: verbatim full Indonesian table title/header as printed; repeat for every row in that table
- table_header_english: verbatim full English table title/header as printed (e.g. "GRDP of Aceh Province at Current Market Prices by Regency/Municipality (Billion Rupiahs), 2018-2022"); repeat for every row in that table; empty if no English header present
- page_number: a bare integer ONLY — the N from the === PAGE N === marker that precedes the table (e.g. 3, or 15); no text, no year range, just the number
- table_number: sequential integer within this document chunk, starting at 1
- Missing values → empty string (never NULL, NaN, or NA)
- Capture everything verbatim — do not interpret, classify, harmonize, correct, or infer
- Include province-level aggregate rows (Jumlah, province name as total); leave regency_code empty for these
- Preserve duplicate and suspicious rows; flag them in anomalies instead

Output format (follow exactly):
1. Output the CSV with header row first — no preamble, no markdown fences
2. After the last data row, output a line containing exactly: ## ANOMALIES
3. List each anomaly as: page <n>, table <n>: <description>
   Flag: missing/ambiguous units, unparseable values, unexpected row structure
"""


# ── PDF helpers ───────────────────────────────────────────────────────────────

def is_text_pdf(pdf_path: Path) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        sample = pdf.pages[:SAMPLE_PAGES]
        total_chars = sum(len(p.extract_text() or "") for p in sample)
        avg = total_chars / max(len(sample), 1)
    return avg >= TEXT_DENSITY_THRESHOLD


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
    """Return base64 of a sub-PDF containing pages start..end (1-indexed)."""
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


# ── API calls ─────────────────────────────────────────────────────────────────

def call_api(client: anthropic.Anthropic, content: list) -> str:
    for attempt in range(3):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                text = stream.get_final_text()
                if stream.get_final_message().stop_reason == "max_tokens":
                    print("    WARNING: response truncated (hit max_tokens)")
            return text
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
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        },
        {"type": "text", "text": PARSE_PROMPT},
    ])


# ── response parsing ──────────────────────────────────────────────────────────

def parse_response(raw: str) -> tuple[list[dict], list[str]]:
    if "## ANOMALIES" in raw:
        csv_part, anomaly_part = raw.split("## ANOMALIES", 1)
    else:
        csv_part, anomaly_part = raw, ""

    anomalies = [l.strip() for l in anomaly_part.strip().splitlines() if l.strip()]

    # Strip markdown fences if model wrapped output anyway
    csv_part = csv_part.strip()
    if csv_part.startswith("```"):
        csv_part = "\n".join(
            l for l in csv_part.splitlines()
            if not l.strip().startswith("```")
        )

    rows = []
    if csv_part:
        reader = csv.DictReader(io.StringIO(csv_part.strip()))
        for row in reader:
            rows.append(dict(row))

    return rows, anomalies


def normalize_row(row: dict) -> dict:
    clean = {col: (row.get(col) or "").strip() for col in CLAUDE_COLUMNS}
    content = "|".join(clean[c] for c in CLAUDE_COLUMNS)
    clean["raw_text_hash"] = hashlib.md5(content.encode()).hexdigest()[:12]
    return clean


def completed_pages(csv_path: Path) -> set[int]:
    if not csv_path.exists():
        return set()
    try:
        df = pd.read_csv(csv_path)
        pages = pd.to_numeric(df["page_number"], errors="coerce").dropna().astype(int)
        result = set(pages.unique())
        if not result:
            print("  WARNING: existing CSV has no valid integer page_numbers — resume cannot skip chunks; treating as fresh run")
        return result
    except Exception:
        return set()


def next_csv_path(csv_dir: Path, stem: str) -> Path:
    base = csv_dir / f"{stem}_long.csv"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = csv_dir / f"{stem}_long_{n}.csv"
        if not candidate.exists():
            return candidate
        n += 1


# ── main parse loop ───────────────────────────────────────────────────────────

def parse_pdf(pdf_path: Path, client: anthropic.Anthropic,
              csv_out: Path, done_pages: set[int]) -> tuple[int, list[str]]:
    all_anomalies: list[str] = []
    total_rows = 0
    write_header = not csv_out.exists()

    text_based = is_text_pdf(pdf_path)
    mode = "text" if text_based else "vision (image-scanned)"
    print(f"  Mode: {mode}")

    if text_based:
        chunks = text_chunks(pdf_path)
        iterator = enumerate(chunks, 1)
        def get_raw(chunk): return call_text(client, chunk["text"])
        def chunk_pages(chunk): return set(chunk["pages"])
        def label(i, chunk):
            p0, p1 = chunk["pages"][0], chunk["pages"][-1]
            return f"pages {p0}–{p1}", len(chunks)
    else:
        n = page_count(pdf_path)
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
        rows, anomalies = parse_response(raw)
        all_anomalies.extend(anomalies)
        if rows:
            normalized = [normalize_row(r) for r in rows]
            df_chunk = pd.DataFrame(normalized, columns=REQUIRED_COLUMNS)
            df_chunk.to_csv(csv_out, mode="a", index=False, header=write_header)
            write_header = False
            total_rows += len(df_chunk)
            print(f"    {len(df_chunk)} rows → saved (total so far: {total_rows})")

    return total_rows, all_anomalies


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parse PDRB PDFs to long-format CSV.")
    parser.add_argument("--input", required=True,
                        help="Directory of PDFs, or path to a single PDF")
    parser.add_argument("--output", default="pipeline_out",
                        help="Output directory (default: pipeline_out)")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"),
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume into existing partial CSV, skipping already-parsed pages")
    args = parser.parse_args()

    if not args.api_key:
        sys.exit("ANTHROPIC_API_KEY not set. Pass --api-key or export the env var.")

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
            csv_out = csv_dir / f"{stem}_long.csv"
            done = completed_pages(csv_out)
            if done:
                print(f"  Resuming — {len(done)} pages already done, skipping those chunks")
        else:
            csv_out = next_csv_path(csv_dir, stem)
            done = set()

        try:
            total_rows, anomalies = parse_pdf(pdf_path, client, csv_out, done)
            log_out.write_text("\n".join(anomalies) if anomalies else "No anomalies.")
            print(f"  → {csv_out} ({total_rows} rows, {len(anomalies)} anomalies logged)")
        except Exception as e:
            err_path.write_text(str(e))
            print(f"  ERROR: {e} (logged to {err_path})")


if __name__ == "__main__":
    main()
