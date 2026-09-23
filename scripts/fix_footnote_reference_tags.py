#!/usr/bin/env python3
"""
fix_footnote_reference_tags.py — retag footnote callout markers as /Reference.

Typst's #footnote[...] construct tags the in-text footnote marker (the small
superscript number in the body paragraph) as a PDF structure element of type
/Lbl. PDF/UA and Adobe Acrobat's accessibility checker consider /Reference
the more semantically correct type for this specific role — a marker whose
purpose is to point elsewhere in the document — with /Lbl reserved for
things like list-item numbers. This is a documented gap in Typst's PDF
export (no user-facing setting controls it), so it has to be corrected as a
post-processing pass on the already-compiled PDF.

Only the in-text callout is retagged, not:
  - the ~18 ordinary numbered-list item markers elsewhere in the document
    (also tagged /Lbl, correctly — left untouched), distinguished by having
    a plain marked-content (scalar) child rather than a nested /Link
  - the /Lbl nested *inside* each /Note element itself (the footnote's own
    printed number at the bottom of the page) — arguably a defensible use
    of /Lbl in its own right, and not what Adobe/HHS guidance is about

Identification rule: a /Lbl structure element, NOT a descendant of a /Note
element, whose sole child is itself a /Link structure element.

Verified 2026-09-23: re-running veraPDF's PDF/UA-1 validation after this
fix still shows 106/106 rules and 207,156/207,156 checks passed, 0 failures
— confirming no regression. 5 elements retagged, matching the document's 5
footnotes exactly.

Usage (run after every `typst compile --pdf-standard ua-1 data_guide.typ
data_guide.pdf` — this step is NOT optional, the fix does not survive a
recompile):
    python scripts/fix_footnote_reference_tags.py docs/data_guide.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

import pikepdf


def retag(pdf_path: Path) -> int:
    pdf = pikepdf.open(pdf_path)
    changed = []

    def walk(container, under_note: bool = False) -> None:
        if isinstance(container, pikepdf.Array):
            for e in container:
                walk(e, under_note)
            return
        if not isinstance(container, pikepdf.Dictionary):
            return
        s = container.get("/S")
        if s is not None:
            sval = str(s)
            if sval == "/Note":
                if "/K" in container:
                    walk(container.K, under_note=True)
                return
            if sval == "/Lbl" and not under_note:
                k = container.get("/K")
                kids = k if isinstance(k, pikepdf.Array) else ([k] if k is not None else [])
                if (
                    len(kids) == 1
                    and isinstance(kids[0], pikepdf.Dictionary)
                    and str(kids[0].get("/S")) == "/Link"
                ):
                    container.S = pikepdf.Name("/Reference")
                    changed.append(container)
            if "/K" in container:
                walk(container.K, under_note)

    walk(pdf.Root.StructTreeRoot.K)

    tmp_path = pdf_path.with_suffix(".tmp.pdf")
    pdf.save(tmp_path)
    tmp_path.replace(pdf_path)
    return len(changed)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-pdf>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    n = retag(path)
    print(f"Retagged {n} footnote-callout element(s) from /Lbl to /Reference in {path}")
    if n == 0:
        print("WARNING: expected 5 (one per footnote) — got 0. Check the document still has footnotes.", file=sys.stderr)
