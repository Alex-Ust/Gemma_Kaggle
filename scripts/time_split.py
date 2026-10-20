"""Split each task's wall time into model time and tool time from ATIF trace timestamps.

  time_split.py runs/v05-skills-sound [--set sound]
"""
import argparse
import glob
import json
import os
import statistics


def split(trace):
    llm, tool, toks, slow_tools = 0.0, 0.0, 0, []
    prev_end = None
    for s in trace["steps"]:
        if s["source"] != "agent":
            continue
        ex = s.get("extra") or {}
        ts = ex.get("timestamp")
        el = ex.get("elapsed_s")
        if ts is None:
            continue
        start = prev_end if prev_end is not None else ts - (el or 0)
        llm += max(0.0, ts - start)
        toks += (s.get("metrics") or {}).get("completion_tokens", 0)
        obs = s.get("observation") or {}
        ots = (obs.get("extra") or {}).get("timestamp")
        if ots:
            dt = max(0.0, ots - ts)
            tool += dt
            if dt > 20:
                name = (s.get("tool_calls") or [{}])[0].get("function_name")
                arg = json.dumps((s.get("tool_calls") or [{}])[0].get("arguments", {}))[:90]
                slow_tools.append((round(dt), name, arg))
            prev_end = ots
        else:
            prev_end = ts
    return llm, tool, toks, slow_tools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--set", default=None)
    ap.add_argument("--show-slow", action="store_true")
    a = ap.parse_args()
    ids = set(json.load(open("research/task_sets.json"))[a.set]) if a.set else None
    rows = {json.loads(l)["instance_id"]: json.loads(l)
            for l in open(os.path.join(a.run, "output/results/task_results.jsonl"))}
    agg = {"capped_time": [], "other": []}
    all_slow = []
    for f in sorted(glob.glob(os.path.join(a.run, "output/results/traces/*.json"))):
        iid = os.path.basename(f)[6:-5]
        if ids and iid not in ids:
            continue
        llm, tool, toks, slow = split(json.load(open(f)))
        err = (rows.get(iid) or {}).get("error") or ""
        key = "capped_time" if "timeout" in err else "other"
        agg[key].append((iid, llm, tool, toks))
        all_slow += [(iid,) + x for x in slow]
    for k, v in agg.items():
        if not v:
            continue
        L = sum(x[1] for x in v); T = sum(x[2] for x in v); K = sum(x[3] for x in v)
        print(f"{k:12s} n={len(v):3d}  model {L / len(v):6.0f}s  tools {T / len(v):5.0f}s per task  "
              f"model share {L / (L + T):.0%}  completion tok/task {K / len(v):.0f}  "
              f"model s per 100 tok {100 * L / max(K, 1):.1f}")
    print(f"tool calls > 20 s: {len(all_slow)}  total {sum(x[1] for x in all_slow)} s")
    if a.show_slow:
        for x in sorted(all_slow, key=lambda x: -x[1])[:25]:
            print("  ", x)


if __name__ == "__main__":
    main()
