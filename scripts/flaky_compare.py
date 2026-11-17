"""Pooled comparison of bundle arms on a task set (default flaky25), several passes per arm.

Usage:
  python scripts/flaky_compare.py --base v34=runs/v34-noedit-l4c2,runs/v34-noedit-l4c2b,runs/v34-noedit-flaky-p3 \
      v39=runs/v39-pipefail-flaky-p1,runs/v39-pipefail-flaky-p2 ...

Each arm is name=run_dir[,run_dir...]. Runs that are not finished yet are skipped. Rows of a full run are
restricted to the task set. Prints per-pass counts, the pooled sum, the mean per pass, the mean duration and
the difference to the base arm with a standard error taken from the per-task solve rates.
"""
import argparse
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def rows_of(run_dir):
    run_dir = ROOT / run_dir
    p = next(run_dir.rglob("task_results.jsonl"), None)
    if p is None:
        return None
    return {r["instance_id"]: r for r in map(json.loads, p.read_text().splitlines())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--base", required=True)
    ap.add_argument("--set", default="flaky25")
    a = ap.parse_args()
    ids = json.loads((ROOT / "data/task_sets.json").read_text())[a.set]
    arms = {}
    for spec in [a.base] + a.arms:
        name, dirs = spec.split("=")
        passes = []
        for d in dirs.split(","):
            rows = rows_of(d)
            if rows is None:
                continue
            missing = [i for i in ids if i not in rows]
            if missing:
                print(f"!! {d}: {len(missing)} tasks of the set missing, pass skipped")
                continue
            passes.append({i: rows[i] for i in ids})
        arms[name] = passes
    base = a.base.split("=")[0]

    def rate(name):  # per-task solve rate over the arm's passes
        ps = arms[name]
        return {i: sum(p[i]["resolved"] for p in ps) / len(ps) for i in ids} if ps else {}

    def var_of_mean(name):  # variance of the per-pass count mean, from per-task Bernoulli rates
        ps = arms[name]
        r = rate(name)
        return sum(v * (1 - v) for v in r.values()) / len(ps) if ps else float("nan")

    print(f"task set {a.set}: {len(ids)} tasks")
    for name, ps in arms.items():
        if not ps:
            print(f"{name:14s} no finished passes")
            continue
        counts = [sum(r["resolved"] for r in p.values()) for p in ps]
        dur = st.mean(r["duration_seconds"] for p in ps for r in p.values())
        capped = st.mean(sum(r["duration_seconds"] >= 415 for r in p.values()) for p in ps)
        empty = st.mean(sum(r["agent_patch_size"] == 0 for r in p.values()) for p in ps)
        line = (f"{name:14s} passes {counts}  pooled {sum(counts)}  mean {st.mean(counts):.2f}  "
                f"dur {dur:.0f}s  capped {capped:.1f}  empty {empty:.1f}")
        if name != base and arms[base]:
            bc = [sum(r["resolved"] for r in p.values()) for p in arms[base]]
            d = st.mean(counts) - st.mean(bc)
            # Bernoulli variance underestimates when rates are 0/1 from few passes; floor it with the
            # ten-run estimate for this set (sum p(1-p) ~ 4.4 per pass).
            se = math.sqrt(max(var_of_mean(name), 4.4 / len(ps)) + max(var_of_mean(base), 4.4 / len(arms[base])))
            line += f"  | vs {base}: {d:+.2f} per pass (SE {se:.2f}, z {d / se:+.2f})"
        print(line)
    names = [n for n in arms if arms[n]]
    if len(names) > 1:
        print("\nper-task solve counts (solved passes / passes):")
        print("task".ljust(16) + "".join(n[:10].ljust(11) for n in names))
        for i in ids:
            print(i.ljust(16) + "".join(f"{sum(p[i]['resolved'] for p in arms[n])}/{len(arms[n])}".ljust(11) for n in names))


if __name__ == "__main__":
    main()
