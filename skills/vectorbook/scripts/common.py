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


# ---------------------------------------------------------------- local model (all three routes)
# Routes: direct call (local_chat), Pi (pi_route in transcribe_local.py), mini-swe-agent
# (mini_task.py). All log to work/local-runs.jsonl; costs.py turns wall time into electricity.

def local_cfg() -> dict:
    return config()["local_model"]


def local_model_id() -> str:
    cfg = local_cfg()
    if cfg.get("model"):
        return cfg["model"]
    import urllib.request
    with urllib.request.urlopen(cfg["url"].rstrip("/") + "/models", timeout=10) as r:
        return json.load(r)["data"][0]["id"]


def log_local(rec: dict) -> dict:
    import time
    rec = {**rec, "eur": round(rec.get("seconds", 0) / 3600 * local_cfg()["eur_per_hour"], 5),
           "time": time.time()}
    with open(work_dir() / "local-runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def local_chat(prompt: str, images: list[Path] = (), max_tokens: int = 8000,
               timeout: int = 900) -> tuple[str, dict, float]:
    """Direct call to the local OpenAI-compatible server: no harness, no stdin, no tools.
    Returns (text, usage, seconds). Thinking is switched off (reasoning_effort none)."""
    import base64
    import time
    import urllib.request
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                            + base64.b64encode(Path(p).read_bytes()).decode()}}
        for p in images]
    body = {"model": local_model_id(), "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "reasoning_effort": "none"}
    req = urllib.request.Request(local_cfg()["url"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with gpu_lease() as lease:                # one GPU owner at a time (other local GPU apps)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            obj = json.load(r)
    msg = obj["choices"][0]["message"]
    obj.setdefault("usage", {})["lease_wait_s"] = lease.waited
    return msg.get("content") or "", {**obj.get("usage", {}),
                                       "finish": obj["choices"][0].get("finish_reason")}, round(time.time() - t0, 1)


GPU_BUSY_PCT = 10      # utilisation that counts as "the model is generating"
POLL_S = 3
IDLE_LIMIT_S = 90      # GPU idle this long with the model loaded = stalled
HARD_LIMIT_S = 900


def gpu_busy() -> bool | None:
    """True if the GPU is computing; None if no GPU query is available (nvidia-smi)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        return max(int(x) for x in r.stdout.split()) >= GPU_BUSY_PCT
    except Exception:
        return None


def model_loaded() -> bool:
    """False while the local server reports the model unloaded or loading (idle GPU is normal then)."""
    import urllib.request
    try:
        with urllib.request.urlopen(local_cfg()["url"].rstrip("/") + "/models", timeout=5) as r:
            return all(m.get("status", {}).get("value", "loaded") == "loaded" for m in json.load(r)["data"])
    except Exception:
        return True


def kill_tree(pid: int):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass


def watch(proc, hard_limit: int = HARD_LIMIT_S, waiting_flag: Path | None = None) -> tuple[int, str, float]:
    """Wait for an agent process; kill it when the GPU stays idle while the model is loaded.
    While `waiting_flag` exists the agent waits for the GPU lease: not a stall, and the time
    does not count toward the hard limit."""
    import time
    last_busy, active, t0, waited = time.time(), 0.0, time.time(), 0.0
    while proc.poll() is None:
        time.sleep(POLL_S)
        if waiting_flag and Path(waiting_flag).exists():
            last_busy = time.time()
            waited += POLL_S
            continue
        busy = gpu_busy()
        if busy or busy is None or not model_loaded():
            last_busy = time.time()
            active += POLL_S if busy else 0.0
        stalled = time.time() - last_busy > IDLE_LIMIT_S
        if stalled or time.time() - t0 - waited > hard_limit:
            kill_tree(proc.pid)
            proc.wait()
            return proc.returncode, "stalled" if stalled else "timeout", active
    return proc.returncode, "ok", active


# ---------------------------------------------------------------- GPU lease (shared with other local apps)
# One GPU owner at a time. On Windows a named mutex; elsewhere an exclusive lock file. Use the
# same name as the machine's other local GPU apps (gpu_mutex in vectorbook.json, or the
# environment variable VECTORBOOK_GPU_MUTEX). Hold it for one model request at a time. Windows
# releases an abandoned mutex when its owner crashes or is killed; such a mutex counts as acquired.

def default_gpu_mutex() -> str:
    return os.environ.get("VECTORBOOK_GPU_MUTEX") or (
        r"Local\vectorbook-gpu" if os.name == "nt" else "vectorbook-gpu")


class GpuLease:
    def __init__(self, name: str | None = None):
        self.name = name or config().get("gpu_mutex") or default_gpu_mutex()
        self.owned = False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self._ct = ctypes
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self.api.CreateMutexW.restype = wintypes.HANDLE
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.ReleaseMutex.argtypes = [wintypes.HANDLE]
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.api.CreateMutexW(None, False, self.name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            import tempfile
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.name)
            self.handle = open(Path(tempfile.gettempdir()) / f"{safe}.lock", "a+")

    def acquire(self, milliseconds: int = 500) -> bool:
        if os.name == "nt":
            r = self.api.WaitForSingleObject(self.handle, milliseconds)
            if r in (0, 0x80):          # acquired, or abandoned by an exited owner
                self.owned = True
                return True
            if r == 0x102:              # timeout
                return False
            raise self._ct.WinError(self._ct.get_last_error())
        import fcntl
        import time
        t_end = time.time() + milliseconds / 1000
        while True:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.owned = True
                return True
            except BlockingIOError:
                if time.time() >= t_end:
                    return False
                time.sleep(0.05)

    def close(self):
        if not self.handle:
            return
        if os.name == "nt":
            if self.owned:
                self.api.ReleaseMutex(self.handle)
            self.api.CloseHandle(self.handle)
        else:
            if self.owned:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
        self.handle, self.owned = None, False


class gpu_lease:
    """Context manager: wait for the GPU lease, hold it, release it. `waiting_flag` (a path) exists
    while waiting, so a watchdog does not count the wait as a stall. `.waited` = seconds waited."""

    def __init__(self, waiting_flag: Path | None = None, quiet: bool = False):
        self.flag, self.quiet, self.waited, self.lease = waiting_flag, quiet, 0.0, None

    def __enter__(self):
        import time
        self.lease = GpuLease()
        t0 = time.time()
        if not self.lease.acquire():
            if not self.quiet:
                print("waiting for another local GPU app to release the GPU ...", flush=True)
            if self.flag:
                Path(self.flag).write_text("waiting", encoding="utf-8")
            max_wait = config().get("gpu_lease_max_wait_s", 1800)
            try:
                while not self.lease.acquire():
                    if time.time() - t0 > max_wait:
                        self.lease.close()
                        raise TimeoutError(
                            f"GPU lease '{self.lease.name}' still held by another local GPU app after "
                            f"{max_wait} s (for example an image worker that keeps it until it exits)")
            finally:
                if self.flag:
                    Path(self.flag).unlink(missing_ok=True)
        self.waited = round(time.time() - t0, 1)
        return self

    def __exit__(self, *exc):
        self.lease.close()
        return False
