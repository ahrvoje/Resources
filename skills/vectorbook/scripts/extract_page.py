"""Extract one source page (DjVu or PDF): src300.png, src150.png, ocr.txt, source.json.

Usage: py extract_page.py --page N      (writes pages/pNNN/ in the project)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import page_count, page_text, project_root, render_page_gray


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, required=True)
    a = ap.parse_args()
    out = project_root() / "pages" / f"p{a.page:03d}"
    out.mkdir(parents=True, exist_ok=True)
    log = out / "extract.log"
    n = page_count(log)
    if not 1 <= a.page <= n:
        print(f"error: page {a.page} out of range 1..{n}", file=sys.stderr)
        return 2
    size = None
    for dpi, name in ((300, "src300.png"), (150, "src150.png")):
        im = render_page_gray(a.page, dpi, log)
        im.save(out / name)
        size = size or list(im.size)
    text = page_text(a.page, log)
    (out / "ocr.txt").write_text(text, encoding="utf-8", errors="replace")
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    toks = first.split()
    guess = next((int(t) for t in toks[:1] + toks[-1:] if re.fullmatch(r"\d{1,4}", t)), None)
    (out / "source.json").write_text(json.dumps(
        {"page": a.page, "size_px_300": size, "ocr_first_line": first,
         "printed_page_guess": guess}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"extracted page {a.page}/{n} -> {out} (printed guess: {guess})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
