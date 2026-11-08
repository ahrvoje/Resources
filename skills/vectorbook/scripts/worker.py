"""One OpenRouter worker call, logged for cost tracking.

Usage: py worker.py NAME MODEL [--page pNNN] [--role ROLE] [--max N]
                    [--effort none|low|medium|high] [--img PATH]...
Reads work/calls/NAME-prompt.txt. `@@include REL@@` inserts a project file (path relative to
the project root). Saves NAME-prompt.final.txt, NAME-response.json, NAME-result.txt.
Appends a record to work/costs.jsonl (page and role make per-page cost measurable).
The key comes from OPENROUTER_API_KEY or the project file `api-key`; it is sent only to
openrouter.ai and never printed or saved.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import project_root, work_dir


def api_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    lines = (project_root() / "api-key").read_text(encoding="utf-8-sig").splitlines()
    return next(s.strip() for s in lines if s.strip().startswith("sk-or-"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("model")
    ap.add_argument("--page", default="", help="pNNN this call is spent on ('' = one-time)")
    ap.add_argument("--role", default="", help="transcribe, review, labels, fix, design, code ...")
    ap.add_argument("--max", type=int, default=8000)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--img", action="append", default=[])
    a = ap.parse_args()
    root, calls = project_root(), work_dir() / "calls"
    calls.mkdir(exist_ok=True)
    raw = (calls / f"{a.name}-prompt.txt").read_text(encoding="utf-8")
    prompt = re.sub(r"@@include (.+?)@@",
                    lambda m: (root / m.group(1).strip()).read_text(encoding="utf-8"), raw)
    (calls / f"{a.name}-prompt.final.txt").write_text(prompt, encoding="utf-8")
    left = re.findall(r"\{[A-Z_]{3,}\}", prompt)
    assert not left, f"unfilled placeholders: {left}"
    content = [{"type": "text", "text": prompt}]
    for f in a.img:
        p = Path(f) if Path(f).is_absolute() else root / f
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}})
    body = {"model": a.model, "messages": [{"role": "user", "content": content}],
            "max_tokens": a.max, "usage": {"include": True},
            "reasoning": {"enabled": False} if a.effort == "none" else {"effort": a.effort}}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + api_key(),
                                          "Content-Type": "application/json"})
    rec = {"name": a.name, "model": a.model, "page": a.page, "role": a.role,
           "effort": a.effort, "max_tokens": a.max, "images": a.img, "time": time.time()}
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            obj = json.load(r)
        (calls / f"{a.name}-response.json").write_text(json.dumps(obj, indent=1, ensure_ascii=False),
                                                      encoding="utf-8")
        if "choices" not in obj:
            raise RuntimeError("no choices: " + json.dumps(obj)[:500])
        msg = obj["choices"][0]["message"]
        (calls / f"{a.name}-result.txt").write_text(msg.get("content") or "", encoding="utf-8")
        u = obj.get("usage", {})
        rec.update(served_model=obj.get("model"), provider=obj.get("provider"),
                   finish=obj["choices"][0].get("finish_reason"),
                   prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"),
                   reasoning_tokens=(u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                   cost=u.get("cost"), seconds=round(time.time() - t0, 1), ok=True)
        if rec["finish"] == "length":
            rec["warning"] = ("output cut at max_tokens" + (" - reasoning used the whole budget"
                              if rec["reasoning_tokens"] and rec["reasoning_tokens"] >= 0.9 * a.max else ""))
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)
        if hasattr(e, "read"):
            try:
                err += " " + e.read().decode()[:800]
            except Exception:
                pass
        (calls / f"{a.name}-error.txt").write_text(err, encoding="utf-8")
        rec.update(ok=False, error=err[:500], seconds=round(time.time() - t0, 1))
    with open(work_dir() / "costs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("name", "model", "ok", "finish", "cost", "seconds", "warning")
                      if rec.get(k) is not None}))


if __name__ == "__main__":
    main()
