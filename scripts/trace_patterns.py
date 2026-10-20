"""Count behaviour patterns in ATIF traces of one or more runs.

  trace_patterns.py runs/v05-skills-sound [runs/v02-...] [--set sound]
"""
import argparse
import collections
import glob
import json
import os
import re

BT = re.compile(r"`,\s*\w+:")


def load(run):
    rows = {}
    for l in open(os.path.join(run, "output/results/task_results.jsonl")):
        r = json.loads(l)
        rows[r["instance_id"]] = r
    return rows


def calls(trace):
    for s in trace["steps"]:
        for i, tc in enumerate(s.get("tool_calls") or []):
            obs = (s.get("observation") or {}).get("content", "")
            yield s, (s.get("message") or "") if i == 0 else "", tc, obs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--set", default=None)
    a = ap.parse_args()
    ids = None
    if a.set:
        ids = set(json.load(open("research/task_sets.json"))[a.set])
    for run in a.runs:
        rows = load(run)
        c = collections.Counter()
        read_sizes = []
        planned_before_edit = []
        for f in glob.glob(os.path.join(run, "output/results/traces/*.json")):
            iid = os.path.basename(f)[6:-5]
            if ids and iid not in ids:
                continue
            t = json.load(open(f))
            seen_edit = False
            code_plans = 0
            reads = collections.defaultdict(list)
            for s, msg, tc, obs in calls(t):
                name = tc["function_name"]
                args = tc["arguments"]
                c["calls"] += 1
                c[f"call:{name}"] += 1
                if any(isinstance(v, str) and BT.search(v) for v in args.values()):
                    c["corrupt_backtick"] += 1
                    c[f"corrupt:{name}"] += 1
                if "INVALID_ARGUMENTS" in obs or "FileReadError" in obs and "`" in obs:
                    c["arg_error"] += 1
                if name == "run_command" and '"exit_code": 1' in obs and '"stdout": ""' in obs:
                    c["empty_grep_or_exit1"] += 1
                if "BudgetExceeded" in obs:
                    c["budget_exceeded_resp"] += 1
                    if name in ("edit_file", "write_file"):
                        c["edit_rejected_budget"] += 1
                if name == "read_file":
                    st, en = args.get("start_line"), args.get("end_line")
                    if isinstance(st, int) and isinstance(en, int):
                        read_sizes.append(en - st + 1)
                    else:
                        read_sizes.append(150 if st is None and en is None else -1)
                    reads[args.get("filepath")].append((st, en))
                if name in ("edit_file", "write_file") and '"status": "ok"' in obs:
                    seen_edit = True
                if not seen_edit and "```" in msg and re.search(r"```(python)?\s", msg):
                    code_plans += 1
            r = rows.get(iid, {})
            if r.get("agent_patch_size", 1) == 0:
                planned_before_edit.append((iid, code_plans))
            c["tasks"] += 1
            c["reread_same_file_3plus"] += sum(len(v) >= 3 for v in reads.values())
        print(f"== {run}  tasks {c['tasks']}  calls {c['calls']}")
        for k, v in sorted(c.items()):
            if k not in ("tasks", "calls"):
                print(f"  {k:28s} {v}")
        if read_sizes:
            rs = sorted(x for x in read_sizes if x > 0)
            print(f"  read_file windows: n={len(read_sizes)} median={rs[len(rs) // 2]} "
                  f"<=30 lines: {sum(x <= 30 for x in rs)}  full(no range): {sum(x == 150 for x in read_sizes)}")
        n_plan = sum(1 for _, k in planned_before_edit if k)
        print(f"  empty-patch tasks with code written in thoughts but never applied: {n_plan}/{len(planned_before_edit)}")
        print("   ", sorted(planned_before_edit, key=lambda x: -x[1]))


if __name__ == "__main__":
    main()
