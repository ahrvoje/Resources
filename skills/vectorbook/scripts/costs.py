"""Running cost ledger against the per-page baseline.

Usage: py costs.py                     summary (run it after every page or batch)
       py costs.py --orchestrator USD --note TEXT   record orchestrator cost (e.g. from /cost)
Sources: work/costs.jsonl (OpenRouter, from worker.py), work/pi-runs.jsonl (local Pi, from
pi_transcribe.py), work/orchestrator.jsonl (manual). A record with a page tag is per-page
work; without it, one-time work (code, design, calibration).
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import config, project_root, work_dir


def load(name):
    p = work_dir() / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orchestrator", type=float)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if a.orchestrator is not None:
        with open(work_dir() / "orchestrator.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"usd": a.orchestrator, "note": a.note, "time": time.time()}) + "\n")
    cfg = config()
    rate, eur_h = cfg["usd_per_eur"], cfg["local_model"]["eur_per_hour"]
    calls, pis, orch = load("costs.jsonl"), load("pi-runs.jsonl"), load("orchestrator.jsonl")
    per_page, one_time = collections.defaultdict(float), 0.0
    roles, models = collections.defaultdict(float), collections.defaultdict(float)
    for r in calls:
        c = r.get("cost") or 0.0
        if r.get("page"):
            per_page[r["page"]] += c
        else:
            one_time += c
        roles[r.get("role") or "-"] += c
        models[r["model"]] += c
    pi_usd = collections.defaultdict(float)
    for r in pis:
        pi_usd[r["page_dir"]] += r["seconds"] / 3600 * eur_h * rate
    orch_usd = sum(r["usd"] for r in orch)
    done = sorted(p.parent.name for p in (project_root() / "pages").glob("p*/page.pdf"))
    pages = sorted(set(per_page) | set(pi_usd))
    base = cfg["baseline_usd_per_page"]
    print(f"{'page':6s} {'openrouter':>10s} {'pi':>8s} {'total':>8s}  vs ${base:.3f}")
    for p in pages:
        t = per_page[p] + pi_usd[p]
        print(f"{p:6s} {per_page[p]:10.4f} {pi_usd[p]:8.4f} {t:8.4f}  {'OVER' if t > base else 'ok'}")
    page_total = sum(per_page.values()) + sum(pi_usd.values())
    n = max(1, len(done))
    print(f"\nfinished pages: {len(done)}")
    print(f"per-page work: ${page_total:.4f} = ${page_total / n:.4f} per finished page (baseline ${base:.3f})")
    print(f"one-time OpenRouter (code, design, calibration): ${one_time:.4f}")
    print(f"orchestrator recorded: ${orch_usd:.2f}  -> all-in ${ (page_total + one_time + orch_usd) / n:.3f} per page")
    print("by role:", {k: round(v, 4) for k, v in sorted(roles.items(), key=lambda kv: -kv[1])})
    print("by model:", {k: round(v, 4) for k, v in sorted(models.items(), key=lambda kv: -kv[1])})
    bad = [(r["name"], r.get("cost"), r.get("warning") or r.get("error", "")[:60]) for r in calls
           if not r.get("ok") or r.get("warning")]
    stalls = [(r["page_dir"], r["tag"], r.get("status")) for r in pis if r.get("status") not in (None, "ok")]
    if bad or stalls:
        print("failed or wasted:", bad, stalls)


if __name__ == "__main__":
    main()
