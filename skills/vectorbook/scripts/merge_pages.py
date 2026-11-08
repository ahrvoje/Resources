"""Merge DIR*/page.pdf into one PDF and verify it. Usage: py merge_pages.py OUT.pdf DIR1 [DIR2 ...]"""
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import config


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_pages.py OUT.pdf DIR1 [DIR2 ...]", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    dirs = [Path(x) for x in sys.argv[2:]]
    pdfs = [d / "page.pdf" for d in dirs]
    missing = [str(p) for p in pdfs if not p.exists()]
    if missing:
        print("error: missing " + ", ".join(missing), file=sys.stderr)
        return 2

    printed = []
    for d in dirs:
        try:
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            printed.append(str(m["printed_page"]))
        except Exception:
            printed.append("?")

    merged = pymupdf.open()
    for p in pdfs:
        with pymupdf.open(p) as src:
            merged.insert_pdf(src)
    merged.set_metadata({
        "title": config()["title"] + " — modern re-setting",
        "subject": "Printed pages: " + ", ".join(printed),
        "creator": "vectorbook skill",
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.save(out, garbage=3, deflate=True)
    merged.close()

    doc = pymupdf.open(out)
    problems = []
    if doc.page_count != len(pdfs):
        problems.append(f"page count {doc.page_count} != {len(pdfs)}")
    for i, page in enumerate(doc, 1):
        if page.get_images():
            problems.append(f"page {i} has images")
        for f in page.get_fonts():
            try:
                content = doc.extract_font(f[0])[3]
            except Exception:
                content = b""
            if not content:
                problems.append(f"page {i} font {f[3]} not embedded")
    n = doc.page_count
    doc.close()
    print(f"{'OK' if not problems else 'FAIL'}: {out} pages={n} "
          f"printed={', '.join(printed)}")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
