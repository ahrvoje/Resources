"""Create a vectorbook project in the current folder.

Usage: py init_project.py --source BOOK.djvu|BOOK.pdf --title "Short title"
Writes vectorbook.json, design/book-style.sty and design/contract.md (copies of the skill
templates; edit them for this book), and the folders pages/, figs/, work/, output/.
Existing files are never overwritten.
"""
import argparse
import json
import shutil
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--title", required=True)
    a = ap.parse_args()
    root = Path.cwd()
    src = Path(a.source)
    assert (root / src).is_file(), f"source not found: {src}"
    cfg = root / "vectorbook.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({
            "source": src.as_posix(), "title": a.title,
            "style": "design/book-style.sty", "contract": "design/contract.md",
            "local_model": {"url": "http://127.0.0.1:8081/v1", "eur_per_hour": 0.10},
            "usd_per_eur": 1.08, "baseline_usd_per_page": 0.05}, indent=1), encoding="utf-8")
    for d in ("design", "pages", "figs", "work", "output"):
        (root / d).mkdir(exist_ok=True)
    for s, t in (("assets/style-template.sty", "design/book-style.sty"),
                 ("references/contract-template.md", "design/contract.md")):
        if not (root / t).exists():
            shutil.copy(SKILL / s, root / t)
    print(f"project ready in {root}")


if __name__ == "__main__":
    main()
