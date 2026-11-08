"""Transcribe or fix one extracted page with the local Pi agent (no tools).

Usage: py pi_transcribe.py pages/pNNN --printed N [--notes TEXT]
       py pi_transcribe.py pages/pNNN --printed N --fix ISSUES_FILE
Transcribe writes meta.json and body.tex. Fix revises body.tex (old version kept as body.vK.tex).
Every run is logged in work/pi-runs.jsonl (seconds, GPU-active seconds, status) for the
electricity cost. Reliability rules (see references/local-pi-worker.md):
- Pi gets a CLOSED stdin. In -p mode Pi reads piped stdin and waits for EOF; an inherited
  open pipe makes it hang before it calls the model (GPU idle).
- A GPU watchdog kills Pi when the GPU stays idle for 90 s while the model is loaded, and
  retries once if the GPU was never active. Hard limit 15 min.
- The page goes to Pi as two overlapping halves: the local image reader downsizes big images.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILL, config, path, work_dir

GPU_BUSY_PCT = 10      # utilisation that counts as "the model is generating"
POLL_S = 3
IDLE_LIMIT_S = 90      # GPU idle this long with the model loaded = stalled
HARD_LIMIT_S = 900


def fill(name: str, values: dict) -> str:
    text = (SKILL / "prompts" / name).read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    left = re.findall(r"\{[A-Z_]{3,}\}", text)
    assert not left, f"unfilled placeholders: {left}"
    return text


def halves(d: Path) -> list[str]:
    im = Image.open(d / "src300.png")
    w, h = im.size
    names = []
    for i, (y0, y1) in enumerate([(0, h // 2 + 80), (h // 2 - 80, h)]):
        n = f"half{i + 1}.png"
        im.crop((0, y0, w, y1)).save(d / n)
        names.append(n)
    return names


def gpu_busy() -> bool | None:
    """True if the GPU is computing; None if nvidia-smi is not available."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        return max(int(x) for x in r.stdout.split()) >= GPU_BUSY_PCT
    except Exception:
        return None


def model_loaded() -> bool:
    """False while the local server reports the model unloaded or loading (idle GPU is normal then)."""
    try:
        url = config()["local_model"]["url"].rstrip("/") + "/models"
        with urllib.request.urlopen(url, timeout=5) as r:
            return all(m.get("status", {}).get("value", "loaded") == "loaded" for m in json.load(r)["data"])
    except Exception:
        return True


def watch(proc) -> tuple[int, str, float]:
    last_busy, active, t0 = time.time(), 0.0, time.time()
    while proc.poll() is None:
        time.sleep(POLL_S)
        busy = gpu_busy()
        if busy or busy is None or not model_loaded():
            last_busy = time.time()
            active += POLL_S if busy else 0.0
        stalled = time.time() - last_busy > IDLE_LIMIT_S
        if stalled or time.time() - t0 > HARD_LIMIT_S:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            proc.wait()
            return proc.returncode, "stalled" if stalled else "timeout", active
    return proc.returncode, "ok", active


def run_pi(d: Path, tag: str, prompt: str, images: list[str]) -> str:
    (d / f"pi-{tag}.prompt.txt").write_text(prompt, encoding="utf-8")
    cmd = ["pi", "--no-session", "--no-tools", "--no-context-files", "--no-skills",
           "--no-extensions", "--thinking", "off", "-p", f"@pi-{tag}.prompt.txt",
           *[f"@{n}" for n in images], "Follow the instructions in the attached prompt file exactly."]
    eur_h = config()["local_model"]["eur_per_hour"]
    for attempt in (1, 2):
        t0 = time.time()
        so, se = d / f"pi-{tag}.stdout.tmp", d / f"pi-{tag}.stderr.tmp"
        with open(so, "wb") as fo, open(se, "wb") as fe:
            proc = subprocess.Popen(cmd, cwd=d, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, shell=True)
            rc, status, active = watch(proc)
        sec = round(time.time() - t0, 1)
        out = so.read_bytes().decode("utf-8", "replace")
        err = se.read_bytes().decode("utf-8", "replace")
        so.unlink(); se.unlink()
        (d / f"pi-{tag}.out.txt").write_text(out + ("\n--- stderr ---\n" + err if err else ""), encoding="utf-8")
        rec = {"page_dir": d.name, "tag": tag, "attempt": attempt, "seconds": sec, "gpu_active_s": active,
               "rc": rc, "status": status, "eur": round(sec / 3600 * eur_h, 5), "time": time.time()}
        with open(work_dir() / "pi-runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec))
        if not (status == "stalled" and active == 0):   # never reached the model: retry once
            break
    assert status == "ok" and rc == 0, f"pi {status} (rc {rc}), see pi-{tag}.out.txt"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--printed", required=True)
    ap.add_argument("--notes", default=""); ap.add_argument("--fix")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    imgs = halves(d)
    if a.fix:
        prompt = fill("fix-body.txt", {"BODY": (d / "body.tex").read_text(encoding="utf-8"),
                                       "ISSUES": Path(a.fix).read_text(encoding="utf-8")})
        n = len(list(d.glob("pi-fix*.out.txt"))) + 1
        out = run_pi(d, f"fix{n}", prompt, imgs)
        m = re.search(r"=====BODY=====\s*\n(.*?)(?:\n=====NOTES=====|\Z)", out, re.S)
        assert m and m.group(1).strip(), f"no BODY section in Pi output (pi-fix{n}.out.txt); body.tex unchanged"
        (d / f"body.v{n}.tex").write_text((d / "body.tex").read_text(encoding="utf-8"), encoding="utf-8")
        (d / "body.tex").write_text(m.group(1).strip() + "\n", encoding="utf-8")
        return
    prompt = fill("transcribe-page.txt", {
        "TITLE": config()["title"], "PAGE": str(int(d.name[1:])), "PRINTED": a.printed,
        "PAGE_NOTES": a.notes or "No special notes.",
        "CONTRACT": path("contract").read_text(encoding="utf-8"),
        "OCR": (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")})
    out = run_pi(d, "transcribe", prompt, imgs)
    m = re.search(r"=====META=====\s*\n(.*?)\n=====BODY=====\s*\n(.*?)(?:\n=====NOTES=====|\Z)", out, re.S)
    assert m, "Pi output lacks META/BODY sections"
    meta = json.loads(m.group(1).strip())
    assert meta["printed_page"] == int(a.printed), f"printed page mismatch: {meta}"
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "body.tex").write_text(m.group(2).strip() + "\n", encoding="utf-8")
    print("ok", d.name, meta)


if __name__ == "__main__":
    main()
