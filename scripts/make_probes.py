"""Extract decision points from recorded traces for next-action probes.

A probe replays a recorded session up to a cut point (recorded model turns + recorded tool results)
and asks the real model, under a candidate prompt, for the next turn only. Kinds of points:
  first  - the very first model turn (tool-call formatting, first action)
  plan   - first turn (from turn PLAN_MIN on) before any edit whose recorded thought contained code but whose
           call was not edit_file
  late   - turn number LATE (default 12) when no source edit had been made yet

  make_probes.py runs/v05-skills-sound --set sound --out research/probes/v05_points.json
"""
import argparse
import json
import os
import re

CODE = re.compile(r"```")


def agent_steps(trace):
    return [s for s in trace["steps"] if s["source"] == "agent"]


def to_step(s):
    tc = (s.get("tool_calls") or [None])[0]
    obs = (s.get("observation") or {}).get("content", "")
    return {
        "thought": s.get("message") or "",
        "call": {"id": tc.get("tool_call_id"), "name": tc["function_name"], "args": tc.get("arguments") or {}},
        "obs": obs,
    }


def is_ok_edit(s):
    tc = (s.get("tool_calls") or [None])[0]
    obs = (s.get("observation") or {}).get("content", "")
    return tc and tc["function_name"] in ("edit_file", "write_file") and '"status": "ok"' in obs


def points_for(iid, trace, late, plan_min=5):
    steps = agent_steps(trace)
    user = next(s["message"] for s in trace["steps"] if s["source"] == "user")
    clean = []  # prefix of steps that each carry exactly one tool call
    for s in steps:
        if len(s.get("tool_calls") or []) != 1:
            break
        clean.append(s)
    out = [{"iid": iid, "kind": "first", "cut": 0}]
    plan_done = False
    for i, s in enumerate(clean):
        if is_ok_edit(s):
            break
        tc = s["tool_calls"][0]
        if (not plan_done and i >= plan_min and CODE.search(s.get("message") or "")
                and tc["function_name"] not in ("edit_file", "write_file")):
            out.append({"iid": iid, "kind": "plan", "cut": i})
            plan_done = True
        if i == late:
            out.append({"iid": iid, "kind": "late", "cut": i})
            break
    for p in out:
        p["user_prompt"] = user
        p["steps"] = [to_step(s) for s in clean[: p["cut"]]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--set", default=None)
    ap.add_argument("--late", type=int, default=12)
    ap.add_argument("--plan-min", type=int, default=5)
    ap.add_argument("--kinds", default="first,plan,late")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ids = json.load(open("research/task_sets.json"))[a.set] if a.set else None
    tdir = os.path.join(a.run, "output/results/traces")
    kinds = set(a.kinds.split(","))
    pts = []
    for fn in sorted(os.listdir(tdir)):
        iid = fn[6:-5]
        if ids and iid not in ids:
            continue
        pts += [p for p in points_for(iid, json.load(open(os.path.join(tdir, fn))), a.late, a.plan_min) if p["kind"] in kinds]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(pts, open(a.out, "w"))
    by = {}
    for p in pts:
        by[p["kind"]] = by.get(p["kind"], 0) + 1
    print(f"{len(pts)} points {by} -> {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
