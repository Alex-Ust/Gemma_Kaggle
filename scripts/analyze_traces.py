"""Aggregate agent traces from an eval run: where time and tool calls go, when the first edit happens.

Usage: python3 scripts/analyze_traces.py runs/<run>
"""
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

EDIT_CMD = re.compile(r"sed -i|>\s*[\w./-]+\.py|open\([^)]*['\"]w|\.write_text\(|\bpatch\b|git apply|perl -pi")


def step_kind(tc):
    fn = tc["function_name"]
    if fn in ("edit_file", "write_file"):
        path = tc["arguments"].get("filepath", "")
        return "edit" if not path.startswith("/tmp") else "scratch"
    if fn == "run_command":
        cmd = tc["arguments"].get("command", "")
        if EDIT_CMD.search(cmd) and "/tmp/" not in cmd:
            return "edit_cmd"
        if re.search(r"pytest|unittest", cmd):
            return "test"
        if re.search(r"python3? -c|python3? /tmp", cmd):
            return "py_check"
        if re.search(r"git diff|git status", cmd):
            return "git"
        if re.search(r"grep|find |ls |git ls-files|rg ", cmd):
            return "search"
        if re.search(r"sed -n|cat |head |tail |nl ", cmd):
            return "read"
        return "cmd_other"
    return fn


def analyze(run):
    run = Path(run)
    res = {json.loads(line)["instance_id"]: json.loads(line)
           for line in next(run.rglob("task_results.jsonl")).read_text().splitlines()}
    traces = {p.stem.replace("trace_", ""): json.loads(p.read_text()) for p in run.rglob("trace_*.json")}
    lat, comp, prompt_tok, first_edit_t, first_edit_i = [], [], [], [], []
    kinds_all, kinds_empty, kinds_solved = Counter(), Counter(), Counter()
    no_edit = 0
    think_lens = []
    rows = []
    for iid, t in traces.items():
        r = res.get(iid, {})
        prev = None
        n_calls = 0
        fe = None
        last_t = 0
        steps = [s for s in t["steps"] if s["source"] == "agent"]
        for s in t["steps"]:
            el = s.get("extra", {}).get("elapsed_s")
            if s["source"] != "agent":
                prev = el if el is not None else prev
                continue
            if el is not None and prev is not None:
                lat.append(el - prev)
            m = s.get("metrics") or {}
            comp.append(m.get("completion_tokens", 0))
            prompt_tok.append(m.get("prompt_tokens", 0))
            think_lens.append(len(s.get("reasoning_content") or s.get("message") or ""))
            obs_el = (s.get("observation") or {}).get("extra", {}).get("elapsed_s") if isinstance(s.get("observation"), dict) else None
            prev = obs_el or el
            last_t = prev or last_t
            for tc in s.get("tool_calls") or []:
                k = step_kind(tc)
                n_calls += 1
                kinds_all[k] += 1
                if r.get("agent_patch_size", 1) == 0:
                    kinds_empty[k] += 1
                if r.get("resolved"):
                    kinds_solved[k] += 1
                if fe is None and k in ("edit", "edit_cmd"):
                    fe = (n_calls, el)
        if fe:
            first_edit_i.append(fe[0])
            first_edit_t.append(fe[1])
        else:
            no_edit += 1
        rows.append((iid, r.get("resolved"), r.get("agent_patch_size"), n_calls, len(steps), round(last_t),
                     fe[0] if fe else None, round(fe[1]) if fe and fe[1] else None))
    n = len(traces)
    print(f"traces {n}")
    print(f"LLM step latency s: median {st.median(lat):.1f} mean {st.mean(lat):.1f} p90 {sorted(lat)[int(.9 * len(lat))]:.1f}")
    print(f"completion tokens/step: median {st.median(comp)} mean {st.mean(comp):.0f} p90 {sorted(comp)[int(.9 * len(comp))]}")
    print(f"prompt tokens/step: median {st.median(prompt_tok)} max {max(prompt_tok)}")
    tot_comp = sum(comp)
    print(f"decode rate (completion tokens / summed latency) ~{tot_comp / sum(lat):.1f} tok/s at concurrency used")
    print(f"tasks with NO source edit at all: {no_edit}/{n}")
    if first_edit_i:
        print(f"first edit at call #: median {st.median(first_edit_i)}  p75 {sorted(first_edit_i)[int(.75 * len(first_edit_i))]}"
              f"   at time s: median {st.median([x for x in first_edit_t if x]):.0f}")
    print("tool-call kinds (all):", dict(kinds_all.most_common()))
    print("tool-call kinds (empty-patch tasks):", dict(kinds_empty.most_common()))
    print("tool-call kinds (solved tasks):", dict(kinds_solved.most_common()))
    return rows


if __name__ == "__main__":
    rows = analyze(sys.argv[1])
    if len(sys.argv) > 2:
        for r in sorted(rows, key=lambda x: (x[1] is not True, x[0])):
            print(r)
