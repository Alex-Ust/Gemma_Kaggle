"""Offline check of skills_src/locate: how often the gold patch file lands in the top-k.

Usage: python3 scripts/eval_locate.py [--query-mode full|title]
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("locate", ROOT / "skills_src/locate/scripts/locate.py")
locate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locate)

TEST_RE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")


def gold(patch):
    out = {}
    cur = None
    for line in patch.splitlines():
        m = re.match(r"^\+\+\+ b/(\S+)", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? ", line)
        if m and cur:
            out[cur].append((int(m.group(1)), int(m.group(1)) + int(m.group(2) or 1)))
    return {f: r for f, r in out.items() if f.endswith(".py") and not TEST_RE.search(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-mode", default="full")
    ap.add_argument("--only", default=None)
    ap.add_argument("--tasks", default=str(ROOT / "data/tasks.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "work/repos"))
    ap.add_argument("--field", default="problem_statement", help="which statement field to use as the query source")
    a = ap.parse_args()
    rows = [json.loads(line) for line in open(a.tasks)]
    if a.only:
        rows = [r for r in rows if r["instance_id"].startswith(a.only)]
    stats = {"n": 0, "r1": 0, "r3": 0, "r5": 0, "sym5": 0, "newfile": 0}
    per_repo = {}
    times = []
    misses = []
    for r in rows:
        g = gold(r["patch"])
        repo_dir = Path(a.repos) / r["instance_id"]
        existing = {f: v for f, v in g.items() if (repo_dir / f).exists()}
        if not existing:
            stats["newfile"] += 1
            continue
        ps = r.get(a.field) or r["problem_statement"]
        if a.query_mode == "full":
            q = ps
        else:  # what an agent would type: title + identifiers/code spans
            clean = locate.clean_query(ps)
            ids = re.findall(r"`([^`]{2,60})`", clean) + re.findall(r"\b[A-Za-z]+_[A-Za-z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z0-9]*\b|\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b", clean)
            q = ps.strip().splitlines()[0] + " " + " ".join(dict.fromkeys(ids))
        t = time.time()
        files, by_file = locate.rank(str(repo_dir), q)
        times.append(time.time() - t)
        ranked = [p for p, _ in files]
        pos = min((ranked.index(f) for f in existing if f in ranked), default=999)
        stats["n"] += 1
        for k in (1, 3, 5):
            stats[f"r{k}"] += pos < k
        # symbol-level: does any of the top-5 symbols overall overlap a gold hunk?
        top_syms = sorted(((s, u) for lst in by_file.values() for s, u in lst if u.kind != "module"),
                          key=lambda x: -x[0])[:5]
        hit = any(u.path in existing and any(u.start <= hi and lo <= u.end for lo, hi in existing[u.path])
                  for _, u in top_syms)
        stats["sym5"] += hit
        repo = r["instance_id"].rsplit("_", 1)[0]
        pr = per_repo.setdefault(repo, [0, 0])
        pr[0] += 1
        pr[1] += pos < 5
        if pos >= 5:
            misses.append((r["instance_id"], sorted(existing), ranked[:3]))
    n = stats["n"]
    print(f"tasks scored {n} (skipped {stats['newfile']} new-file-only)")
    for k in ("r1", "r3", "r5", "sym5"):
        print(f"  {k}: {stats[k]}/{n} = {stats[k] / n:.2f}")
    print("  per repo recall@5:", {k: f"{v[1]}/{v[0]}" for k, v in per_repo.items()})
    print(f"  time per query: mean {sum(times) / len(times):.2f}s max {max(times):.2f}s")
    print("  sample misses:")
    for m in misses[:8]:
        print("   ", m)


if __name__ == "__main__":
    main()
