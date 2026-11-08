"""Consistent vertical layout for all pages of a book (final layout step).

Usage: py vertical.py [pages/pNNN ...] [--rmax 2.0] [--full 0.93]   (default: all pages/p*)
Rule (the same for every page):
- A page whose SOURCE text reaches the book's normal block bottom is "full"; a page that ends
  early (section or chapter end) is "short" and stays ragged, as in the source.
- Full page: the free space E is shared by the page's stretchable gaps (display, figure and
  statement skips; text lines keep the grid), proportionally to their declared stretch, so the
  spacing is balanced within the page. Each gap grows at most --rmax times its declared stretch
  (one value for the whole book, so pages look alike); the rest stays at the bottom.
Writes vstretch and a 'vertical' record into meta.json, rebuilds the pages, and writes
work/vertical-report.json. Checks: one page each, short/full as in the source, figure height
position close to the source.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import project_root, work_dir

HERE = Path(__file__).resolve().parent


def ink_bands(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bands of ink rows (gap > 8 px at 300 dpi) as (y0, y1, x0, x1)."""
    rows = np.where(img.sum(1) > 2)[0]
    if not len(rows):
        return []
    out, s, q = [], rows[0], rows[0]
    for y in list(rows[1:]) + [10 ** 9]:
        if y > q + 8:
            cols = np.where(img[s:q + 1].sum(0) > 0)[0]
            out.append((int(s), int(q), int(cols[0]), int(cols[-1])))
            s = y
        q = y
    return out


def source_body(d: Path) -> tuple[int, int, int]:
    """Body top, body bottom (excluding running head and a bottom folio), page height."""
    img = np.array(Image.open(d / "src300.png")) < 128
    h, w = img.shape
    b = ink_bands(img)
    if b and b[0][1] < 0.12 * h and len(b) > 1:          # running head line
        b = b[1:]
    if b and b[-1][0] > 0.90 * h and (b[-1][3] - b[-1][2]) < 0.15 * w and len(b) > 1:  # bottom folio
        b = b[:-1]
    return (b[0][0], b[-1][1], h) if b else (0, 0, h)


def build(d: Path) -> dict:
    subprocess.run([sys.executable, str(HERE / "build_page.py"), str(d)], capture_output=True,
                   stdin=subprocess.DEVNULL)
    return json.loads((d / "checks.json").read_text(encoding="utf-8"))


def figure_tops_render(d: Path) -> list[float]:
    with pymupdf.open(d / "page.pdf") as doc:
        p = doc[0]
        rects = sorted({(round(r["rect"].y0), round(r["rect"].y1)) for r in p.get_drawings()
                        if r["rect"].height < p.rect.height * 0.9})
        # group drawing boxes into figures (vertical overlap)
        figs, cur = [], None
        for y0, y1 in rects:
            if cur and y0 <= cur[1] + 6:
                cur[1] = max(cur[1], y1)
            else:
                cur = [y0, y1]
                figs.append(cur)
        return [f[0] / p.rect.height for f in figs if f[1] - f[0] > 20]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--rmax", type=float, default=2.0)
    ap.add_argument("--full", type=float, default=0.93)
    a = ap.parse_args()
    dirs = [Path(p).resolve() for p in a.pages] or sorted((project_root() / "pages").glob("p*"))
    dirs = [d for d in dirs if (d / "body.tex").exists()]
    src = {d.name: source_body(d) for d in dirs}
    # the book's normal block bottom: a high percentile of body bottoms (relative to page height)
    bottoms = np.array([b / h for _, b, h in src.values()])
    block_bottom = float(np.percentile(bottoms, 85))
    tops = np.array([t / h for t, _, h in src.values()])
    block_top = float(np.median(tops))
    report = []
    for d in dirs:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta["vstretch"] = "fill"
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        c = build(d)
        v = c.get("vertical")
        t, b, h = src[d.name]
        src_fill = (b / h - block_top) / max(1e-6, block_bottom - block_top)
        kind = "full" if src_fill >= a.full else "short"
        rec = {"page": d.name, "kind": kind, "source_fill": round(src_fill, 3)}
        if not (c.get("ok") and v):
            rec["error"] = "natural build failed: " + json.dumps(c.get("hard"))
            report.append(rec)
            continue
        E = max(0.0, v["goal_pt"] - v["natural_pt"])
        S = v["stretch_pt"]
        if kind == "full" and S > 0 and E > 0.5:
            share = min(E, a.rmax * S)
            reserve = 0.0 if share >= E - 0.5 else S * (E - share) / share
            meta["vstretch"] = f"{reserve:.2f}pt"
            rec.update(free_pt=round(E, 1), stretch_pt=round(S, 1), ratio=round(share / S, 2),
                       gaps_get_pt=round(share, 1), bottom_left_pt=round(E - share, 1))
        else:
            rec.update(free_pt=round(E, 1), stretch_pt=round(S, 1), ratio=0.0,
                       note="ragged (short page)" if kind == "short" else "no stretchable gaps")
        meta["vertical"] = {k: rec[k] for k in rec if k != "page"}
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        c = build(d)
        rec["ok"] = bool(c.get("ok"))
        rec["fill"] = c.get("text_bottom")
        fs = json.loads((d / "figures.json").read_text()) if (d / "figures.json").exists() else []
        st = [f["box300"][1] / h for f in fs]
        rt = figure_tops_render(d)
        if st and len(st) == len(rt):
            rec["figure_top_shift"] = round(max(abs(x - y) for x, y in zip(st, rt)), 3)
        report.append(rec)
    (work_dir() / "vertical-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"block top {block_top:.3f}, block bottom {block_bottom:.3f} (fraction of page height); rmax {a.rmax}")
    for r in report:
        flag = []
        if not r.get("ok"):
            flag.append("BUILD FAIL")
        if r.get("figure_top_shift", 0) > 0.15:
            flag.append("figure position differs from source")
        if r["kind"] == "full" and r.get("bottom_left_pt", 0) > 3 * 13:
            flag.append("full page with > 3 lines empty at bottom (consider page size)")
        print(r["page"], r["kind"], "src", r["source_fill"], "fill", r.get("fill"), "ratio", r.get("ratio"),
              "bottom left", r.get("bottom_left_pt", "-"), "fig shift", r.get("figure_top_shift", "-"),
              "; ".join(flag))


if __name__ == "__main__":
    main()
