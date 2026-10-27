#!/usr/bin/env python3
"""Post-filter for sft_extract output: keep only trajectories whose assistant turns carry thoughts (train.py with
THINK=1 skips rows without them, so cap AFTER this filter), then keep the N shortest rows per task.
usage: sft_filter.py <in.jsonl> <out.jsonl> --cap 5"""
import argparse, collections, json

ap = argparse.ArgumentParser()
ap.add_argument("inp"); ap.add_argument("out"); ap.add_argument("--cap", type=int, default=5)
a = ap.parse_args()
rows = [json.loads(l) for l in open(a.inp)]
th = [r for r in rows if any(m.get("reasoning_content") for m in r["messages"] if m["role"] == "assistant")]
by = collections.defaultdict(list)
for r in th:
    by[r["instance_id"]].append(r)
out = [x for iid in sorted(by) for x in sorted(by[iid], key=lambda r: r["chars"])[: a.cap]]
with open(a.out, "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print(f"in {len(rows)} rows/{len({r['instance_id'] for r in rows})} tasks -> with thoughts {len(th)} -> cap {a.cap}: "
      f"{len(out)} rows over {len(by)} tasks; per run {dict(collections.Counter(r['run'] for r in out))}")
