"""Run mini-swe-agent (local model, text-based actions) on an iterative task in one page folder.

Usage: py mini_task.py pages/pNNN --task-file TASK.txt [--edit body.tex fig1.tex] [--steps 30]
Use it for loops with tools: build -> read log -> fix -> rebuild; run a check script and act on it.
Do not use it for single-shot work (use transcribe_local.py --via direct) or for exact multi-place
edits of LaTeX that a script can do.
Guarantees:
- only the files in --edit may change (others are compared before/after; changes are reported);
  the edit files are backed up as <name>.pre-miniK;
- the agent runs with a closed stdin, under the GPU watchdog, with a step limit and a time limit;
- after the run the page is rebuilt; if the page passed before and fails now, the backups are
  restored; the run is logged in work/local-runs.jsonl and the trajectory in work/mini/.
mini-swe-agent lives in its own Python environment: this script restarts itself under that
interpreter for the agent part (config "mini_python", env MINI_SWE_PYTHON, or `uv tool dir`).
"""
import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILL, config, gpu_lease, local_cfg, local_model_id, log_local, watch, work_dir

SHELL_NOTE = {
    "nt": "Commands run in Windows cmd.exe, each in a new process. Use `py` for Python.",
    "posix": "Commands run in a POSIX shell, each in a new process. Use `python3` for Python.",
}


def mini_python() -> str:
    cand = [config().get("mini_python"), os.environ.get("MINI_SWE_PYTHON")]
    try:
        tool_dir = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL).stdout.strip()
        if tool_dir:
            cand += [str(Path(tool_dir) / "mini-swe-agent" / "Scripts" / "python.exe"),
                     str(Path(tool_dir) / "mini-swe-agent" / "bin" / "python")]
    except FileNotFoundError:
        pass
    for c in cand:
        if c and Path(c).is_file():
            return c
    raise FileNotFoundError("mini-swe-agent Python not found: set mini_python in vectorbook.json")


def child(a):
    """Agent part; runs under the mini-swe-agent interpreter."""
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    import litellm
    litellm.suppress_debug_info = True  # local models have no price entry: silence the notices
    import yaml
    import minisweagent
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel
    cfg = yaml.safe_load((Path(minisweagent.__file__).parent / "config" / "mini_textbased.yaml")
                         .read_text(encoding="utf-8"))
    ag, mo, en = cfg.get("agent", {}), cfg.get("model", {}), cfg.get("environment", {})
    ag["system_template"] = ag.get("system_template", "") + "\n" + SHELL_NOTE["nt" if os.name == "nt" else "posix"]
    ag.update(step_limit=a.steps, cost_limit=0)
    mo.update(model_name="openai/" + a.model, cost_tracking="ignore_errors",
              model_kwargs={"api_base": a.url, "api_key": "local"})
    en.pop("environment_class", None)
    en.update(cwd=a.dir, timeout=300)
    flag = Path(a.flag)

    class LeasedModel(LitellmTextbasedModel):
        """Hold the shared GPU lease for each model query only (as the machine's own mini setup
        does), so shell commands between queries do not block other local GPU apps."""
        def _query(self, messages, **kwargs):
            with gpu_lease(waiting_flag=flag):
                return super()._query(messages, **kwargs)

    agent = DefaultAgent(LeasedModel(**mo), LocalEnvironment(**en), **ag)
    try:
        result = agent.run(Path(a.task_file).read_text(encoding="utf-8"))
    except Exception as e:  # limits and format errors end the run; the parent verifies the files
        result = {"exit_status": type(e).__name__, "submission": str(e)[:500]}
    try:
        traj = agent.serialize()
    except Exception:
        traj = {"messages": agent.messages}
    Path(a.traj).write_text(json.dumps(traj, indent=1, default=str), encoding="utf-8")
    print("MINI_RESULT " + json.dumps(result, default=str)[:2000])


def build_ok(d: Path) -> bool:
    subprocess.run([sys.executable, str(SKILL / "scripts" / "build_page.py"), str(d)],
                   capture_output=True, stdin=subprocess.DEVNULL)
    c = d / "checks.json"
    return c.exists() and json.loads(c.read_text(encoding="utf-8")).get("ok", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--task-file", required=True)
    ap.add_argument("--edit", nargs="*", default=["body.tex"])
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--model"); ap.add_argument("--url"); ap.add_argument("--traj"); ap.add_argument("--flag")
    a = ap.parse_args()
    if a.child:
        return child(a)
    d = Path(a.dir).resolve()
    k = len(list(d.glob("*.pre-mini*"))) // max(1, len(a.edit)) + 1
    before = {f.name: f.read_bytes() for f in d.iterdir() if f.is_file() and f.suffix in (".tex", ".json")}
    for n in a.edit:
        shutil.copy(d / n, d / f"{n}.pre-mini{k}")
    was_ok = build_ok(d)
    (work_dir() / "mini").mkdir(exist_ok=True)
    traj = work_dir() / "mini" / f"{d.name}-{k}.json"
    task = (SKILL / "prompts" / "mini-task.txt").read_text(encoding="utf-8").replace(
        "{TASK}", Path(a.task_file).read_text(encoding="utf-8")).replace(
        "{EDIT}", ", ".join(a.edit)).replace("{BUILD}", f'py "{SKILL / "scripts" / "build_page.py"}" .')
    tf = d / f"mini-task{k}.txt"
    tf.write_text(task, encoding="utf-8")
    cmd = [mini_python(), __file__, str(d), "--child", "--task-file", str(tf), "--steps", str(a.steps),
           "--model", local_model_id(), "--url", local_cfg()["url"], "--traj", str(traj)]
    flag = d / f"mini{k}.lease-wait"          # exists while the agent waits for the GPU lease
    cmd += ["--flag", str(flag)]
    t0 = time.time()
    with open(d / f"mini{k}.log", "wb") as lo:
        proc = subprocess.Popen(cmd, cwd=d, stdin=subprocess.DEVNULL, stdout=lo, stderr=subprocess.STDOUT,
                                start_new_session=(os.name != "nt"))
        rc, status, active = watch(proc, hard_limit=1800, waiting_flag=flag)
    flag.unlink(missing_ok=True)
    sec = round(time.time() - t0, 1)
    now_ok = build_ok(d)
    changed = {n: sum(1 for l in difflib.unified_diff(
        before[n].decode("utf-8", "replace").splitlines(), (d / n).read_text(encoding="utf-8").splitlines(),
        lineterm="") if l[:1] in "+-" and l[:3] not in ("+++", "---"))
        for n in before if (d / n).exists() and (d / n).read_bytes() != before[n]}
    outside = [n for n in changed if n not in a.edit and n not in ("checks.json", "page.tex")]
    restored = False
    if (was_ok and not now_ok) or outside:
        for n in a.edit:
            shutil.copy(d / f"{n}.pre-mini{k}", d / n)
        for n in outside:
            (d / n).write_bytes(before[n])
        build_ok(d)
        restored = True
    print(json.dumps(log_local({"page": d.name, "route": "mini", "tag": f"mini{k}", "seconds": sec,
                                "gpu_active_s": active, "rc": rc, "status": status, "build_before": was_ok,
                                "build_after": now_ok, "changed_lines": changed, "outside_edit": outside,
                                "restored": restored})))
    return 0 if (now_ok and not restored) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
