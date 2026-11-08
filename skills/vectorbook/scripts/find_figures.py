"""Find figure boxes on an extracted page from the ink, not by eye.

Usage: py find_figures.py pages/pNNN [--min-height 100] [--max-text 0.25]
A figure is a band of ink rows (gaps <= 8 px at 300 dpi) taller than --min-height whose area is
covered by OCR word boxes for less than --max-text (paragraphs with tall superscripts also form
tall bands, but they are mostly covered by words). Writes figures.json with boxes in 300 dpi
page pixels, in reading order. Look at each box before tracing: captions inside a band are
erased later via the label step; side-by-side drawings stay one figure.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import word_boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--min-height", type=int, default=100)
    ap.add_argument("--max-text", type=float, default=0.25)
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    page = int(d.name[1:])
    ink = np.array(Image.open(d / "src300.png")) < 128
    rows = np.where(ink.sum(1) > 2)[0]
    bands, s, q = [], rows[0], rows[0]
    for y in rows[1:]:
        if y > q + 8:
            bands.append((s, q))
            s = y
        q = y
    bands.append((s, q))
    words = word_boxes(page, 300, d / "extract.log")
    figs = []
    for b0, b1 in bands:
        if b1 - b0 <= a.min_height:
            continue
        cols = np.where(ink[b0:b1 + 1].sum(0) > 0)[0]
        x0, x1 = int(cols[0]), int(cols[-1])
        area = (x1 - x0 + 1) * (b1 - b0 + 1)
        covered = sum(max(0, min(w[2], x1) - max(w[0], x0)) * max(0, min(w[3], b1) - max(w[1], b0))
                      for w in words)
        frac = float(covered / area)
        rec = {"box300": [x0, int(b0), x1, int(b1)], "text_cover": round(frac, 3)}
        if frac < a.max_text:
            figs.append(rec)
        else:
            print("skip text band", rec)
    for i, f in enumerate(figs, 1):
        f["id"] = f"{d.name}-{i}"
    (d / "figures.json").write_text(json.dumps(figs, indent=1), encoding="utf-8")
    print(d.name, "figures:", [(f["id"], f["box300"], f["text_cover"]) for f in figs])


if __name__ == "__main__":
    main()
