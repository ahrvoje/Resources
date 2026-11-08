"""Build DIR/page.pdf from body.tex and run quality checks."""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import pymupdf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import find_tool, paper_size_pt, path, run

BENIGN = re.compile(r"unicode-math|mathtools", re.I)


def check_pdf(pdf: Path, res: dict, hard: dict):
    doc = pymupdf.open(pdf)
    hard["one_page"] = doc.page_count == 1
    if doc.page_count < 1:
        return
    page = doc[0]
    pw, ph = paper_size_pt()
    hard["paper_size"] = (abs(page.rect.width - pw) <= 0.5
                          and abs(page.rect.height - ph) <= 0.5)
    hard["no_images"] = not page.get_images()
    fonts, embedded = [], True
    for f in page.get_fonts():
        xref = f[0]
        fonts.append(f[3])
        try:
            content = doc.extract_font(xref)[3]
        except Exception:
            content = b""
        if not content:
            embedded = False
    hard["fonts_embedded"] = embedded
    res["fonts"] = fonts
    blocks = page.get_text("blocks")
    res["text_bottom"] = (round(max(b[3] for b in blocks) / page.rect.height, 3)
                          if blocks else 0)
    for dpi in (150, 300):
        page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).save(
            pdf.parent / f"render{dpi}.png")


def compare(d: Path):
    src, ren = d / "src150.png", d / "render150.png"
    if not (src.exists() and ren.exists()):
        return
    a, b = Image.open(src).convert("L"), Image.open(ren).convert("L")
    h = min(a.height, b.height)
    a = a.resize((round(a.width * h / a.height), h))
    b = b.resize((round(b.width * h / b.height), h))
    out = Image.new("L", (a.width + b.width + 4, h), 128)
    out.paste(a, (0, 0))
    out.paste(b, (a.width + 4, 0))
    out.save(d / "compare150.png")


def svg_checks(d: Path, log: Path, hard: dict):
    xe = find_tool("xelatex")
    dv = find_tool("dvisvgm")
    run([xe, "-no-pdf", "-interaction=nonstopmode", "-halt-on-error", "page.tex"],
        d, log)
    run([dv, "--bbox=papersize", "--font-format=woff2", "page.xdv", "-o", "page.svg"],
        d, log)
    run([dv, "--bbox=papersize", "--no-fonts", "page.xdv", "-o", "page-outlined.svg"],
        d, log)
    s = (d / "page.svg").read_text(encoding="utf-8", errors="replace")
    o = (d / "page-outlined.svg").read_text(encoding="utf-8", errors="replace")
    hard["svg_no_image"] = "<image" not in s and "<image" not in o
    hard["outlined_no_text"] = "<text" not in o


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--svg", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    log = d / "build.log"
    log.unlink(missing_ok=True)

    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    (d / "page.tex").write_text(
        "\\documentclass[10pt]{article}\n"
        f"\\usepackage{{{path('style').stem}}}\n"
        "\\begin{document}\n"
        f"\\vbhead{{{meta['printed_page']}}}{{{meta['head_text']}}}\n"
        "\\input{body}\n"
        # bottom stretch from vertical.py; 'fill' = ragged (natural layout, used for measuring)
        f"\\vbendpage{{{meta.get('vstretch', 'fill')}}}\n"
        "\\end{document}\n", encoding="utf-8")
    # per-page copy of the project style; change the design only in the project style
    shutil.copyfile(path("style"), d / path("style").name)

    hard, soft, res = {}, {}, {}
    try:
        run([find_tool("xelatex"), "-interaction=nonstopmode", "-halt-on-error",
             "page.tex"], d, log)
        hard["xelatex_rc0"] = True
    except RuntimeError as e:
        hard["xelatex_rc0"] = False
        res["error"] = str(e)

    tex_log = d / "page.log"
    lines = (tex_log.read_text(encoding="utf-8", errors="replace").splitlines()
             if tex_log.exists() else [])
    hard["no_missing_char"] = not any("Missing character" in l for l in lines)
    hard["no_tex_errors"] = not any(l.startswith("! ") for l in lines)
    hard["no_overfull"] = not any(re.search(r"Overfull \\[hv]box", l) for l in lines)
    soft["underfull"] = sum("Underfull" in l for l in lines)
    vb = [re.match(r"VBPAGE:\d+:([\d.]+)pt:([\d.]+)pt:([\d.]+)pt", l) for l in lines]
    vb = [m for m in vb if m]
    if vb:  # natural content height, total finite stretch, page goal (pt)
        res["vertical"] = {"natural_pt": float(vb[-1][1]), "stretch_pt": float(vb[-1][2]),
                           "goal_pt": float(vb[-1][3]), "vstretch": meta.get("vstretch", "fill")}
    soft["warnings"] = [l for l in lines if "Warning" in l
                        and not BENIGN.search(l)][:20]

    pdf = d / "page.pdf"
    if hard["xelatex_rc0"] and pdf.exists():
        check_pdf(pdf, res, hard)
        compare(d)
        if a.svg:
            try:
                svg_checks(d, log, hard)
            except (RuntimeError, FileNotFoundError) as e:
                hard["svg_built"] = False
                res["svg_error"] = str(e)

    ok = all(hard.values()) and bool(hard)
    (d / "checks.json").write_text(
        json.dumps({"ok": ok, "hard": hard, "soft": soft, **res}, indent=2,
                   ensure_ascii=False), encoding="utf-8")
    failed = [k for k, v in hard.items() if not v]
    print(f"{'OK' if ok else 'FAIL'}: page {meta['printed_page']} "
          f"fill={res.get('text_bottom')} underfull={soft['underfull']} "
          f"failed={failed or 'none'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
