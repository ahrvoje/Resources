"""Transcribe or fix one extracted page with the local model.

Usage: py transcribe_local.py pages/pNNN --printed N [--notes TEXT] [--via direct|pi]
       py transcribe_local.py pages/pNNN --printed N --fix ISSUES_FILE [--via direct|pi]
Routes (references/local-workers.md):
- direct (default): one HTTP call to the local server. No harness, no stdin, no tools: the most
  reliable route for single-shot work.
- pi: the Pi agent CLI (no tools). Use it when the direct route fails for a harness-specific
  reason, or to compare. Pi gets a CLOSED stdin and runs under the GPU watchdog.
Transcribe writes meta.json and body.tex. Fix revises body.tex (old version kept as body.vK.tex);
an answer without a body section leaves body.tex unchanged. Every run is logged in
work/local-runs.jsonl. The page goes to the model as two overlapping halves (local image
readers downsize large images).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILL, config, gpu_lease, local_chat, log_local, path, watch


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


def via_direct(d: Path, tag: str, prompt: str, images: list[str]) -> str:
    (d / f"local-{tag}.prompt.txt").write_text(prompt, encoding="utf-8")
    try:
        out, usage, sec = local_chat(prompt, [d / n for n in images], max_tokens=12000)
        status = "ok" if usage.get("finish") != "length" else "cut at max_tokens"
    except Exception as e:
        out, usage, sec, status = "", {}, 0.0, f"error: {type(e).__name__}: {e}"[:300]
    (d / f"local-{tag}.out.txt").write_text(out, encoding="utf-8")
    print(json.dumps(log_local({"page": d.name, "route": "direct", "tag": tag, "seconds": sec,
                                "lease_wait_s": usage.get("lease_wait_s"), "status": status,
                                "completion_tokens": usage.get("completion_tokens")})))
    assert status == "ok", f"direct call {status}"
    return out


def via_pi(d: Path, tag: str, prompt: str, images: list[str]) -> str:
    (d / f"pi-{tag}.prompt.txt").write_text(prompt, encoding="utf-8")
    cmd = ["pi", "--no-session", "--no-tools", "--no-context-files", "--no-skills",
           "--no-extensions", "--thinking", "off", "-p", f"@pi-{tag}.prompt.txt",
           *[f"@{n}" for n in images], "Follow the instructions in the attached prompt file exactly."]
    for attempt in (1, 2):
        so, se = d / f"pi-{tag}.stdout.tmp", d / f"pi-{tag}.stderr.tmp"
        # the GPU lease is held for the whole Pi run (one model request); waiting is not work time
        with gpu_lease() as lease, open(so, "wb") as fo, open(se, "wb") as fe:
            t0 = time.time()
            # stdin MUST be closed: in -p mode Pi reads piped stdin and waits for EOF
            proc = subprocess.Popen(cmd, cwd=d, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, shell=True)
            rc, status, active = watch(proc)
            sec = round(time.time() - t0, 1)
        out = so.read_bytes().decode("utf-8", "replace")
        err = se.read_bytes().decode("utf-8", "replace")
        so.unlink(); se.unlink()
        (d / f"pi-{tag}.out.txt").write_text(out + ("\n--- stderr ---\n" + err if err else ""), encoding="utf-8")
        print(json.dumps(log_local({"page": d.name, "route": "pi", "tag": tag, "attempt": attempt,
                                    "seconds": sec, "lease_wait_s": lease.waited, "gpu_active_s": active,
                                    "rc": rc, "status": status})))
        if not (status == "stalled" and active == 0):   # never reached the model: retry once
            break
    assert status == "ok" and rc == 0, f"pi {status} (rc {rc}), see pi-{tag}.out.txt"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--printed", required=True)
    ap.add_argument("--notes", default=""); ap.add_argument("--fix")
    ap.add_argument("--via", choices=("direct", "pi"), default="direct")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    run = via_direct if a.via == "direct" else via_pi
    imgs = halves(d)
    if a.fix:
        prompt = fill("fix-body.txt", {"BODY": (d / "body.tex").read_text(encoding="utf-8"),
                                       "ISSUES": Path(a.fix).read_text(encoding="utf-8")})
        n = len(list(d.glob("body.v*.tex"))) + 1
        out = run(d, f"fix{n}", prompt, imgs)
        m = re.search(r"=====BODY=====\s*\n(.*?)(?:\n=====NOTES=====|\Z)", out, re.S)
        assert m and m.group(1).strip(), f"no BODY section in the answer (fix{n}); body.tex unchanged"
        (d / f"body.v{n}.tex").write_text((d / "body.tex").read_text(encoding="utf-8"), encoding="utf-8")
        (d / "body.tex").write_text(m.group(1).strip() + "\n", encoding="utf-8")
        return
    prompt = fill("transcribe-page.txt", {
        "TITLE": config()["title"], "PAGE": str(int(d.name[1:])), "PRINTED": a.printed,
        "PAGE_NOTES": a.notes or "No special notes.",
        "CONTRACT": path("contract").read_text(encoding="utf-8"),
        "OCR": (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")})
    out = run(d, "transcribe", prompt, imgs)
    m = re.search(r"=====META=====\s*\n(.*?)\n=====BODY=====\s*\n(.*?)(?:\n=====NOTES=====|\Z)", out, re.S)
    assert m, "answer lacks META/BODY sections"
    meta = json.loads(m.group(1).strip())
    assert meta["printed_page"] == int(a.printed), f"printed page mismatch: {meta}"
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "body.tex").write_text(m.group(2).strip() + "\n", encoding="utf-8")
    print("ok", d.name, meta)


if __name__ == "__main__":
    main()
