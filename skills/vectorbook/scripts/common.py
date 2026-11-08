"""Shared helpers for the vectorbook scripts.

One project folder per book or paper. Its root holds `vectorbook.json`; every script finds
the root from the current directory upwards, so all paths come from one config.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TEX_TOOLS = {"xelatex", "dvisvgm", "lualatex"}
DEFAULTS = {
    "title": "Modern re-setting",
    "style": "design/book-style.sty",
    "contract": "design/contract.md",
    "local_model": {"url": "http://127.0.0.1:8081/v1", "eur_per_hour": 0.10},
    "usd_per_eur": 1.08,
    "baseline_usd_per_page": 0.05,
    "figure": {"max_width_pt": 296, "scale_large": 0.85, "scale_small": 0.92,
               "small_below_px600": 1000},
}


def project_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        if (d / "vectorbook.json").is_file():
            return d
    raise FileNotFoundError("vectorbook.json not found in this folder or its parents; "
                            "run scripts/init_project.py first")


def config() -> dict:
    cfg = json.loads((project_root() / "vectorbook.json").read_text(encoding="utf-8"))
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in cfg.items():
        out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def path(key: str) -> Path:
    """Project file named in the config (source, style, contract)."""
    return project_root() / config()[key]


def work_dir() -> Path:
    d = project_root() / "work"
    d.mkdir(exist_ok=True)
    return d


def find_book() -> Path:
    return path("source")


def paper_size_pt() -> tuple[float, float]:
    """Paper size declared in the project style (the single source of truth)."""
    sty = path("style").read_text(encoding="utf-8")
    unit = {"in": 72.0, "pt": 72 / 72.27, "mm": 72 / 25.4, "bp": 1.0, "cm": 720 / 25.4}
    dims = []
    for k in ("width", "height"):
        m = re.search(rf"paper{k}=([\d.]+)(in|pt|mm|bp|cm)", sty)
        if not m:
            raise ValueError(f"paper{k} not found in {path('style')}")
        dims.append(float(m[1]) * unit[m[2]])
    return dims[0], dims[1]


def _in_dir(name, folder):
    if not folder:
        return None
    for cand in (Path(folder) / f"{name}.exe", Path(folder) / name):
        if cand.is_file():
            return str(cand)
    return None


def find_tool(name: str) -> str:
    if name in TEX_TOOLS:
        found = shutil.which(name) or _in_dir(name, os.environ.get("MIKTEX_BIN"))
    else:
        found = (_in_dir(name, os.environ.get("DJVULIBRE_DIR"))
                 or _in_dir(name, SKILL / "tools" / "djvulibre") or shutil.which(name))
    if not found:
        raise FileNotFoundError(f"tool '{name}' not found")
    return found


def run(cmd, cwd, log_path):
    """Run cmd (list) with closed stdin; log it; raise on a non-zero exit code."""
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"$ {' '.join(cmd)}\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}\n"
                f"--- return code: {p.returncode} ---\n\n")
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {cmd[0]}; see {log_path}")
    return p


def render_page_gray(page: int, dpi: int, log: Path):
    """Render one source page (DjVu or PDF) as an 8-bit grey PIL image."""
    from PIL import Image
    book = find_book()
    if book.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(book) as doc:
            pix = doc[page - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    tmp = log.parent / f"_render_{page}_{dpi}.pgm"
    try:
        run([find_tool("ddjvu"), "-format=pgm", f"-scale={dpi}", f"-page={page}", book, tmp],
            log.parent, log)
        import io  # read into memory: Pillow memory-maps PGM files, which blocks deletion on Windows
        return Image.open(io.BytesIO(tmp.read_bytes())).convert("L")
    finally:
        tmp.unlink(missing_ok=True)


def page_count(log: Path) -> int:
    book = find_book()
    if book.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(book) as doc:
            return doc.page_count
    return int(run([find_tool("djvused"), book, "-e", "n"], log.parent, log).stdout.strip())


def page_text(page: int, log: Path) -> str:
    book = find_book()
    if book.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(book) as doc:
            return doc[page - 1].get_text()
    return run([find_tool("djvutxt"), f"--page={page}", book], log.parent, log).stdout


def word_boxes(page: int, dpi: int, log: Path) -> list[tuple[float, float, float, float]]:
    """OCR/text word boxes (x0, y0, x1, y1), y down, in pixels at `dpi`."""
    book = find_book()
    if book.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(book) as doc:
            s = dpi / 72
            return [(w[0] * s, w[1] * s, w[2] * s, w[3] * s) for w in doc[page - 1].get_text("words")]
    out = run([find_tool("djvutxt"), f"--page={page}", "--detail=word", book], log.parent, log).stdout
    head = re.search(r"\(page (\d+) (\d+) (\d+) (\d+)", out)
    if not head:
        return []
    size = run([find_tool("djvused"), book, "-e", f"select {page}; size"], log.parent, log).stdout
    native_h = int(re.search(r"height=(\d+)", size)[1])
    # DjVu text coordinates are native pixels with y measured from the bottom.
    s = dpi / _native_dpi(page, log)
    return [(float(a) * s, (native_h - float(d)) * s, float(c) * s, (native_h - float(b)) * s)
            for a, b, c, d in re.findall(r"\(word (\d+) (\d+) (\d+) (\d+)", out)]


def _native_dpi(page: int, log: Path) -> float:
    """Native resolution: compare the native height with a 100 dpi render."""
    book = find_book()
    size = run([find_tool("djvused"), book, "-e", f"select {page}; size"], log.parent, log).stdout
    native_h = int(re.search(r"height=(\d+)", size)[1])
    return native_h * 100 / render_page_gray(page, 100, log).height
