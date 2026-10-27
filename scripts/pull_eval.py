"""Download an eval kernel's output and summarize it; optionally compare with another run.

Usage:
  python scripts/pull_eval.py runs/v02-no-graph-full            # pull (if needed) + summary
  python scripts/pull_eval.py runs/v03-locate-full --vs runs/v02-no-graph-full
"""
import argparse
import json
import os
import statistics as st
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
N_HIDDEN = 120  # approx hidden tasks, run sequentially by the scorer
LIMIT_H = 12.0


def pull(run_dir):
    out = run_dir / "output"
    if (out / "results" / "task_results.jsonl").exists():
        return out
    if (run_dir / "results" / "task_results.jsonl").exists():  # pod layout runs/<run>/results/
        return run_dir
    slug = json.loads((run_dir / "run.json").read_text())["slug"]
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "KAGGLE_API_TOKEN": str(ROOT / "kaggle/access_token")}
    st_ = subprocess.run([str(ROOT / ".venv/bin/kaggle"), "kernels", "status", slug],
                         env=env, capture_output=True, text=True).stdout.strip()
    print(st_)
    subprocess.run([str(ROOT / ".venv/bin/kaggle"), "kernels", "output", slug, "-p", str(out), "-o"],
                   env=env, capture_output=True, text=True)
    return out


def load(run_dir):
    out = pull(run_dir)
    p = next(out.rglob("task_results.jsonl"), None)
    if p is None:
        log = next(out.glob("*.log"), None)
        if log:
            print("no results; tail of log:\n", log.read_text()[-3000:])
        raise SystemExit("no task_results.jsonl")
    rows = {}
    for line in p.read_text().splitlines():
        r = json.loads(line)
        rows[r["instance_id"]] = r
    return rows


def summary(name, rows, concurrency):
    n = len(rows)
    solved = sum(r["resolved"] for r in rows.values())
    empty = sum(r["agent_patch_size"] == 0 for r in rows.values())
    errs = Counter((r["error"] or "")[:60] for r in rows.values() if r["error"])
    dur = [r["duration_seconds"] for r in rows.values()]
    calls = [r["tool_calls"] for r in rows.values()]
    print(f"== {name}: resolved {solved}/{n} = {solved / n:.3f}   empty patches {empty}")
    by_repo = Counter()
    tot_repo = Counter()
    for r in rows.values():
        tot_repo[r["repo"]] += 1
        by_repo[r["repo"]] += r["resolved"]
    print("   per repo:", {k: f"{by_repo[k]}/{v}" for k, v in tot_repo.items()})
    print(f"   duration s: median {st.median(dur):.0f}  mean {st.mean(dur):.0f}  max {max(dur):.0f}"
          f"   tool calls: median {st.median(calls)}  max {max(calls)}")
    # Projection caveats (audit 2026-10-27): duration_seconds includes container setup and Phase-2 verification
    # (the 12 h rule excludes validation), and runs at concurrency > 1 inflate per-task time because the agent
    # budget is wall-clock while vLLM queues requests. So report the time-capped share separately and show the
    # worst case where every hidden task is capped; the scorer runs tasks one at a time.
    capped = sum(1 for r in rows.values() if "timeout" in (r["error"] or "").lower())
    proj = N_HIDDEN * st.mean(dur) / 3600
    print(f"   time-capped tasks {capped}/{n} = {capped / n:.0%}; projected {N_HIDDEN} sequential tasks "
          f"~{proj:.1f} h from the mean (limit {LIMIT_H} h; measured at concurrency {concurrency}, includes "
          f"setup+verification, so biased upward unless concurrency is 1)")
    if errs:
        print("   errors:", dict(errs.most_common(5)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--vs")
    ap.add_argument("--set", help="restrict both runs to a task set from data/task_sets.json (sound, sound105, ood, ...)")
    a = ap.parse_args()
    run_dir = ROOT / a.run
    rows = load(run_dir)
    keep = set(json.load(open(ROOT / "data/task_sets.json"))[a.set]) if a.set else None
    if keep:
        rows = {k: v for k, v in rows.items() if k in keep}
    summary(run_dir.name, rows, json.loads((run_dir / "run.json").read_text()).get("concurrency"))
    if a.vs:
        base_dir = ROOT / a.vs
        base = load(base_dir)
        if keep:
            base = {k: v for k, v in base.items() if k in keep}
        summary(base_dir.name, base, json.loads((base_dir / "run.json").read_text()).get("concurrency"))
        common = sorted(set(rows) & set(base))
        wins = [i for i in common if rows[i]["resolved"] and not base[i]["resolved"]]
        losses = [i for i in common if base[i]["resolved"] and not rows[i]["resolved"]]
        print(f"== paired on {len(common)} tasks: +{len(wins)} wins  -{len(losses)} losses "
              f"(net {len(wins) - len(losses):+d})")
        print("   wins:", wins)
        print("   losses:", losses)


if __name__ == "__main__":
    main()
