"""Page-size optimisation on sample pages (run once per book, before production).

Usage: py pagesize.py pages/pAAA pages/pBBB ... [--extra WxH ...] [--headroom 0.97]
Sample pages: about 10 transcribed pages with the densest text, the widest tables and displays,
the largest figures. For each candidate trim the project style is copied with a new geometry
(same type size and leading, margins and measure in the same proportions as the current style,
text height a whole number of lines). Every sample page is built (ragged bottom) and recorded:
fits on one page, fill, overfull lines in text (figure overfulls are counted apart: figures are
rescaled to the chosen measure). Candidates come from standard book trims near the source trim.
Writes work/pagesize.json and prints a ranked table. Rank: all pages fit, no text overfull,
max fill <= headroom, then the smallest page area (the owner prefers the smaller side), then
the highest mean fill. The design worker decides with this table (prompts/design-style.txt).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import find_tool, path, work_dir

TRIMS_IN = {"5x8in": (5, 8), "5.25x8in": (5.25, 8), "Demy 138x216mm": (5.433, 8.504),
            "5.5x8.5in": (5.5, 8.5), "A5 148x210mm": (5.827, 8.268), "6x9in": (6, 9),
            "Royal 156x234mm": (6.142, 9.213), "6.69x9.61in": (6.69, 9.61),
            "B5 176x250mm": (6.929, 9.843), "7x10in": (7, 10)}
KEYS = ("paperwidth", "paperheight", "textwidth", "inner", "textheight", "top")
UNIT = {"in": 72.27, "pt": 1.0, "mm": 72.27 / 25.4, "pc": 12.0, "bp": 72.27 / 72}


def geometry(sty: str) -> dict:
    g = {}
    for k in KEYS:
        m = re.search(rf"\b{k}=([\d.]+)(in|pt|mm|pc|bp)", sty)
        assert m, f"{k} missing in the style geometry"
        g[k] = float(m[1]) * UNIT[m[2]]
    m = re.search(r"\\@setfontsize\\normalsize\{([\d.]+)\}\{([\d.]+)\}", sty)
    g["size"], g["leading"] = (float(m[1]), float(m[2])) if m else (10.0, 12.0)
    m = re.search(r"\\setlength\\topskip\{([\d.]+)pt\}", sty)
    g["topskip"] = float(m[1]) if m else g["size"]
    return g


def variant(sty: str, g: dict, w: float, h: float) -> tuple[str, dict]:
    """Same proportions as the current geometry, whole number of lines (all in TeX pt)."""
    tw = round(g["textwidth"] / g["paperwidth"] * w / 6) * 6           # measure on a 6 pt grid
    lines = int((g["textheight"] / g["paperheight"] * h - g["topskip"]) // g["leading"]) + 1
    th = g["leading"] * (lines - 1) + g["topskip"]
    inner = (w - tw) * g["inner"] / (g["paperwidth"] - g["textwidth"])
    top = (h - th) * g["top"] / (g["paperheight"] - g["textheight"])
    new = {"paperwidth": w, "paperheight": h, "textwidth": tw, "inner": inner, "textheight": th, "top": top}
    for k, v in new.items():
        sty = re.sub(rf"\b{k}=[\d.]+(in|pt|mm|pc|bp)", f"{k}={v:.2f}pt", sty, count=1)
    return sty, {"measure_pt": tw, "lines": lines, **{k: round(v, 1) for k, v in new.items()}}


def overfulls(log: str, body: list[str]) -> tuple[int, int, float]:
    text = fig = 0
    worst = 0.0
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\) (?:in paragraph at lines (\d+)--(\d+)|"
                         r"detected at line (\d+))", log):
        a = int(m[2] or m[4]); b = int(m[3] or m[4])
        span = "\n".join(body[max(0, a - 3):b])
        if "\\mfigure" in span or "\\input{fig" in span:
            fig += 1
        else:
            text += 1
            worst = max(worst, float(m[1]))
    return text, fig, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--extra", nargs="*", default=[], help="more trims, e.g. 5.6x8.6 (inches)")
    ap.add_argument("--headroom", type=float, default=0.97)
    a = ap.parse_args()
    dirs = [Path(p).resolve() for p in a.pages]
    sty = path("style").read_text(encoding="utf-8")
    g = geometry(sty)
    sw, sh = Image.open(dirs[0] / "src300.png").size
    src_area = (sw / 300) * (sh / 300)
    trims = {k: v for k, v in TRIMS_IN.items() if 0.6 <= v[0] * v[1] / src_area <= 1.15}
    trims.update({f"{e}in": tuple(map(float, e.split("x"))) for e in a.extra})
    trims[f"current {g['paperwidth'] / 72.27:.2f}x{g['paperheight'] / 72.27:.2f}in"] = (
        g["paperwidth"] / 72.27, g["paperheight"] / 72.27)
    results = []
    for name, (wi, hi) in sorted(trims.items(), key=lambda kv: kv[1][0] * kv[1][1]):
        s2, geo = variant(sty, g, wi * 72.27, hi * 72.27)
        rows = []
        for d in dirs:
            e = work_dir() / "pagesize" / name.replace(" ", "_") / d.name
            e.mkdir(parents=True, exist_ok=True)
            for f in d.glob("*.tex"):
                if f.name != "page.tex":
                    shutil.copy(f, e / f.name)
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            (e / "page.tex").write_text(
                "\\documentclass[10pt]{article}\n" f"\\usepackage{{{path('style').stem}}}\n"
                "\\begin{document}\n" f"\\vbhead{{{meta['printed_page']}}}{{{meta['head_text']}}}\n"
                "\\input{body}\n\\vbendpage{fill}\n\\end{document}\n", encoding="utf-8")
            (e / path("style").name).write_text(s2, encoding="utf-8")
            subprocess.run([find_tool("xelatex"), "-interaction=nonstopmode", "page.tex"], cwd=e,
                           capture_output=True, stdin=subprocess.DEVNULL)
            log = (e / "page.log").read_text(encoding="utf-8", errors="replace")
            body = (e / "body.tex").read_text(encoding="utf-8").splitlines()
            t, f_, worst = overfulls(log, body)
            vb = re.findall(r"VBPAGE:\d+:([\d.]+)pt:[\d.]+pt:([\d.]+)pt", log)
            with pymupdf.open(e / "page.pdf") as doc:
                n = doc.page_count
            fill = round(float(vb[-1][0]) / float(vb[-1][1]), 3) if vb and n == 1 else None
            rows.append({"page": d.name, "pages": n, "fill": fill, "text_overfull": t,
                         "figure_overfull": f_, "worst_text_overfull_pt": worst})
        fills = [r["fill"] for r in rows if r["fill"] is not None]
        res = {"trim": name, "in": [wi, hi], "mm": [round(wi * 25.4, 1), round(hi * 25.4, 1)], **geo,
               "fit": sum(r["pages"] == 1 for r in rows), "n": len(rows),
               "fill_min": min(fills, default=None), "fill_mean": round(sum(fills) / len(fills), 3) if fills else None,
               "fill_max": max(fills, default=None), "text_overfull_pages": sum(r["text_overfull"] > 0 for r in rows),
               "figure_overfull_pages": sum(r["figure_overfull"] > 0 for r in rows), "pages": rows}
        res["feasible"] = (res["fit"] == res["n"] and res["text_overfull_pages"] == 0
                           and (res["fill_max"] or 9) <= a.headroom)
        results.append(res)
    results.sort(key=lambda r: (not r["feasible"], r["in"][0] * r["in"][1], -(r["fill_mean"] or 0)))
    (work_dir() / "pagesize.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"{'trim':24s} {'measure':>7s} {'lines':>5s} {'fit':>5s} {'fill min/mean/max':>20s} {'text ovf':>8s} feasible")
    for r in results:
        print(f"{r['trim']:24s} {r['measure_pt'] / 12:6.1f}pc {r['lines']:5d} {r['fit']:2d}/{r['n']:<2d} "
              f"{r['fill_min']}/{r['fill_mean']}/{r['fill_max']:>5} {r['text_overfull_pages']:8d} {r['feasible']}")
    best = next((r for r in results if r["feasible"]), None)
    print("recommended:", best["trim"] if best else "none feasible: widen the candidates or change type size")


if __name__ == "__main__":
    main()
