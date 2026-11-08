"""Final output: one self-contained TeX document with all pages, and its PDF.

Usage: py make_book.py NAME [pages/pAAA ...]        (default: all pages/p* with page.pdf, in order)
Writes output/NAME.tex and output/NAME.pdf.
- The project style is embedded with filecontents; page bodies and traced figures are inlined
  (text resources inside, binary resources such as fonts stay external).
- Each page keeps its head, folio and vertical setting (\vbendpage from meta.json).
Checks: the book has one page per source page; each book page has the same text as the
validated single page (so the book is exactly the checked pages); paper size; fonts embedded;
no raster images.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import config, find_tool, paper_size_pt, path, project_root


def inline_figures(body: str, d: Path) -> str:
    def rep(m):
        f = d / f"{m.group(1)}.tex"
        return "%\n" + f.read_text(encoding="utf-8").strip() + "%\n"
    return re.sub(r"\\input\{(fig\d+)\}", rep, body)


def norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def main() -> int:
    name = sys.argv[1]
    root = project_root()
    dirs = [Path(p).resolve() for p in sys.argv[2:]] or sorted(p.parent for p in (root / "pages").glob("p*/page.pdf"))
    style = path("style")
    parts = [r"\begin{filecontents*}[overwrite]{" + style.name + "}",
             style.read_text(encoding="utf-8").rstrip(), r"\end{filecontents*}",
             r"\documentclass[10pt]{article}", r"\usepackage{" + style.stem + "}",
             f"% {config()['title']} - modern re-setting, {len(dirs)} pages", r"\begin{document}"]
    for d in dirs:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        body = inline_figures((d / "body.tex").read_text(encoding="utf-8").strip(), d)
        parts += [f"% ===== source page {d.name}, printed page {meta['printed_page']}",
                  f"\\vbhead{{{meta['printed_page']}}}{{{meta['head_text']}}}", body,
                  f"\\vbendpage{{{meta.get('vstretch', 'fill')}}}"]
    parts.append(r"\end{document}")
    out = root / "output"
    out.mkdir(exist_ok=True)
    (out / f"{name}.tex").write_text("\n".join(parts) + "\n", encoding="utf-8")
    p = subprocess.run([find_tool("xelatex"), "-interaction=nonstopmode", "-halt-on-error", f"{name}.tex"],
                       cwd=out, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
    problems = [] if p.returncode == 0 else [f"xelatex failed, see output/{name}.log"]
    if not problems:
        pw, ph = paper_size_pt()
        with pymupdf.open(out / f"{name}.pdf") as book:
            if book.page_count != len(dirs):
                problems.append(f"{book.page_count} pages, expected {len(dirs)}")
            for i, d in enumerate(dirs[:book.page_count]):
                pg = book[i]
                with pymupdf.open(d / "page.pdf") as single:
                    if norm(pg.get_text()) != norm(single[0].get_text()):
                        problems.append(f"page {i + 1} ({d.name}) text differs from the validated page")
                if abs(pg.rect.width - pw) > 0.5 or abs(pg.rect.height - ph) > 0.5:
                    problems.append(f"page {i + 1} size {pg.rect.width:.1f}x{pg.rect.height:.1f}")
                if pg.get_images():
                    problems.append(f"page {i + 1} has raster images")
                for f in pg.get_fonts():
                    try:
                        ok = bool(book.extract_font(f[0])[3])
                    except Exception:
                        ok = False
                    if not ok:
                        problems.append(f"page {i + 1} font {f[3]} not embedded")
        log = (out / f"{name}.log").read_text(encoding="utf-8", errors="replace")
        if re.search(r"Overfull \\[hv]box", log):
            problems.append("overfull boxes in the book log")
    print(("OK" if not problems else "FAIL") + f": output/{name}.tex, output/{name}.pdf, {len(dirs)} pages")
    for x in sorted(set(problems)):
        print("  -", x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
